"""Offline contract tests. Every send uses a mocked transport or queue."""

import json
import asyncio
import hashlib
import hmac
import io
import os
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch, Mock, AsyncMock

import requests
from fastapi import BackgroundTasks

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from app import config, whatsapp, webhook
from app.meta_api import graph_base_url, MetaSendError
from app.native_messages import reply_buttons, selection_list, static_flow
from app.services import job_queue_service as jobs
from app.services.flow_session_service import parse_completion
from app.services.proactive_template_service import proactive_template_payload
from app.flows.help_flow import resolve_interactive_action, resolve_menu_action


class NativeWhatsAppTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(whatsapp, "WHATSAPP_TOKEN", "test-token"))
        self.stack.enter_context(patch.object(whatsapp, "PHONE_NUMBER_ID", "test-phone-id"))
        self.stack.enter_context(patch.object(config, "WHATSAPP_DELIVERY_STATUS_ENABLED", False))
        self.post = self.stack.enter_context(patch.object(whatsapp._session, "post"))
        self.post.return_value = SimpleNamespace(ok=True, status_code=200, json=lambda: {"messages": [{"id": "wamid.test"}]})

    def test_version_default_and_invalid_configuration(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(graph_base_url(), "https://graph.facebook.com/v22.0")
        for value in ("", "latest", "v27.0/path", "https://other.invalid", "v27.1", None):
            with self.subTest(value=value), patch.dict(os.environ, {"WHATSAPP_GRAPH_API_VERSION": "bad"}):
                with self.assertRaises(ValueError):
                    graph_base_url(value)

    def test_all_existing_payload_categories_use_configured_url_and_queue(self):
        with patch.object(jobs, "enqueue_whatsapp_send", return_value=7) as enqueue:
            whatsapp.send_text("test-recipient", "Result saved")
            whatsapp.send_image("test-recipient", "https://example.invalid/logo.png", "Club")
            whatsapp.send_main_menu_list("test-recipient", admin=True)
            whatsapp.send_confirm_buttons("test-recipient", "4", "27:41")
            whatsapp.send_admin_pending_actions("test-recipient", "Pending members")
        payloads = [call.args[0] for call in enqueue.call_args_list]
        payloads.append(static_flow("test-recipient", "Choose", flow_id="test-flow", token="a" * 32,
                                    cta="Choose date", screen="TT_DATE", data={"max_date": "2026-11-18"}))
        with patch.dict(os.environ, {"TEST_TEMPLATE": "test_recap"}):
            payloads.append(proactive_template_payload("test-recipient", "TEST_TEMPLATE", ["November", "3"]))
        self.post.assert_not_called()
        for version in ("v22.0", "v27.0"):
            for payload in payloads:
                with self.subTest(version=version, kind=payload["type"]), patch.object(config, "WHATSAPP_GRAPH_API_VERSION", version):
                    self.assertTrue(whatsapp._send_direct(payload))
                    self.assertIn(f"/{version}/test-phone-id/messages", self.post.call_args.args[0])
                    self.assertEqual(self.post.call_args.kwargs["json"], payload)
                    self.assertEqual(self.post.call_args.kwargs["timeout"], (whatsapp.CONNECT_TIMEOUT, whatsapp.READ_TIMEOUT))

    def test_safe_classification_for_rejected_expired_permission_and_transient_errors(self):
        for status, code, permanent in [(400, 100, True), (400, 190, True), (403, 200, True),
                                         (400, 131047, True), (429, 130429, False), (503, 2, False)]:
            with self.subTest(status=status, code=code):
                self.post.return_value = SimpleNamespace(ok=False, status_code=status,
                    json=lambda: {"error": {"code": code, "message": "test-token private response"}})
                with self.assertRaises(MetaSendError) as caught:
                    whatsapp._send_direct({"to": "test-recipient", "type": "text"})
                self.assertEqual(caught.exception.permanent, permanent)
                self.assertNotIn("test-token", str(caught.exception))
                self.assertNotIn("private", str(caught.exception))

    def test_network_errors_are_bounded_and_do_not_echo_request_details(self):
        self.post.side_effect = requests.Timeout("secret request body test-token")
        with self.assertRaises(MetaSendError) as caught:
            whatsapp._send_direct({"to": "test-recipient", "type": "text"})
        self.assertFalse(caught.exception.permanent)
        self.assertNotIn("secret", str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)

    def test_permanent_errors_fail_first_attempt_transient_retries_stay_bounded(self):
        for permanent, attempt, expected in [(True, 1, "FAILED"), (False, 1, "PENDING"), (False, 3, "FAILED")]:
            cur = Mock()
            with patch.object(jobs, "get_cursor") as ctx:
                ctx.return_value.__enter__.return_value = cur
                jobs._mark_job_failed({"id": 1, "attempts": attempt, "max_attempts": 3}, MetaSendError("test", permanent=permanent))
            self.assertEqual(cur.execute.call_args.args[1][0], expected)

    def test_delivery_diagnostic_failure_does_not_resend_accepted_message(self):
        with patch.object(config, "WHATSAPP_DELIVERY_STATUS_ENABLED", True), patch(
            "app.services.delivery_status_service.record_acceptance", side_effect=RuntimeError("database unavailable")
        ), whatsapp.outbound_job(8):
            self.assertTrue(whatsapp._send_direct({"type": "text", "to": "test-recipient"}))
        self.post.assert_called_once()
        self.assertEqual(self.post.call_args.kwargs["json"]["biz_opaque_callback_data"], "job:8")

    def test_erasure_confirmation_does_not_retain_delivery_diagnostics(self):
        with patch.object(config, "WHATSAPP_DELIVERY_STATUS_ENABLED", True), patch(
            "app.services.delivery_status_service.record_acceptance"
        ) as record:
            whatsapp._send_direct({"type": "text", "to": "test-recipient"})
        record.assert_not_called()
        self.assertNotIn("biz_opaque_callback_data", self.post.call_args.kwargs["json"])

    def test_buttons_limits_unique_identifiers_and_labels(self):
        self.assertEqual(reply_buttons("test", "Review", [("confirm:abc", "Confirm"), ("cancel:abc", "Cancel")])
                         ["interactive"]["action"]["buttons"][0]["reply"]["id"], "confirm:abc")
        for choices in ([], [(str(i), str(i)) for i in range(4)], [("id", "x" * 21)],
                        [("id", "Yes"), ("id", "No")], [("a", "Yes"), ("b", "Yes")], [(" a", "Yes")]):
            with self.subTest(choices=choices), self.assertRaises(ValueError):
                reply_buttons("test", "Body", choices)
        with self.assertRaises(ValueError):
            reply_buttons("test", "x" * 1025, [("id", "Yes")])

    def test_lists_enforce_total_rows_lengths_and_stable_ids(self):
        sections = [{"title": "Dates", "rows": [{"id": "date:2026-12-13", "title": "13 December", "description": "Available"}]}]
        payload = selection_list("test", "Choose", sections)
        sections[0]["rows"][0]["id"] = "changed"
        self.assertEqual(payload["interactive"]["action"]["sections"][0]["rows"][0]["id"], "date:2026-12-13")
        for sections in ([], [{"title": "x", "rows": []}],
                         [{"title": "x", "rows": [{"id": str(i), "title": "Date"} for i in range(11)]}],
                         [{"title": "x", "rows": [{"id": "a", "title": "x" * 25}]}],
                         [{"title": "x", "rows": [{"id": "a", "title": "A", "description": "x" * 73}]}],
                         [{"title": "x", "rows": [{"id": "a", "title": "A"}]}] * 2):
            with self.subTest(sections=sections), self.assertRaises(ValueError):
                selection_list("test", "Choose", sections)

    def test_flagged_menu_has_nine_member_entries_and_one_authorized_admin_entry(self):
        with patch.object(config, "WHATSAPP_NATIVE_UX_ENABLED", True), patch.object(whatsapp, "_send", return_value=True) as send:
            for admin in (False, True):
                whatsapp.send_main_menu_list("test", admin=admin)
                sections = send.call_args.args[0]["interactive"]["action"]["sections"]
                ids = [row["id"] for section in sections for row in section["rows"]]
                self.assertEqual(len(ids), 10 if admin else 9)
                self.assertEqual("admin_menu" in ids, admin)
                self.assertIn("menu_activities", ids)
                self.assertIn("menu_privacy", ids)

    def test_contextual_actions_replace_text_with_one_message_and_long_text_falls_back(self):
        with patch.object(config, "WHATSAPP_NATIVE_UX_ENABLED", True), patch.object(whatsapp, "_send", return_value=True) as send:
            for context in ("result", "progress", "profile"):
                send.reset_mock()
                whatsapp.send_contextual_text("test", "Saved", context)
                send.assert_called_once()
                self.assertEqual(send.call_args.args[0]["interactive"]["type"], "button")
            send.reset_mock()
            whatsapp.send_contextual_text("test", "x" * 1025, "progress")
            send.assert_called_once()
            self.assertEqual(send.call_args.args[0]["type"], "text")

    def test_navigation_aliases_survive_flag_rollback(self):
        self.assertEqual(resolve_menu_action("MY PROGRESS"), "PROGRESS")
        self.assertEqual(resolve_menu_action("CLUB ACTIVITIES"), "ACTIVITIES")
        self.assertEqual(resolve_interactive_action("menu_progress_hub"), "PROGRESS_HUB")
        self.assertIsNone(resolve_interactive_action("unrecognized-stale-button"))

    def test_flow_gates_require_all_readiness_settings(self):
        for enabled, published, flow_id in ((False, True, "123"), (True, False, "123"), (True, True, "")):
            with patch.object(config, "WHATSAPP_FLOWS_ENABLED", enabled), patch.object(
                config, "WHATSAPP_ADMIN_DATE_FLOW_PUBLISHED", published
            ), patch.object(whatsapp, "WHATSAPP_ADMIN_DATE_FLOW_ID", flow_id), patch(
                "app.services.flow_session_service.launch_admin_calendar"
            ) as launch:
                self.assertFalse(whatsapp.send_admin_date_calendar("test", "Test Member", "draft"))
                launch.assert_not_called()

    def test_flow_parser_rejects_malformed_payloads_and_preserves_fields_for_validation(self):
        for value in (None, [], "not-json", "[]", "null", '{"flow_token":42}', '{"flow_token":"short"}', "x" * 16385):
            self.assertEqual(parse_completion(value), {})
        data = {"flow_token": "a" * 32, "event_date": "2026-11-17"}
        self.assertEqual(parse_completion(json.dumps(data)), data)

    def test_template_parameters_are_validated_without_free_form_fallback(self):
        with patch.dict(os.environ, {"TEST_TEMPLATE": "test_template", "WHATSAPP_TEMPLATE_LANGUAGE": "en_GB"}):
            for params in ([None], [""], [42], "invalid"):
                with self.assertRaises(ValueError):
                    proactive_template_payload("test", "TEST_TEMPLATE", params)
        with patch.dict(os.environ, {"TEST_TEMPLATE": ""}), self.assertRaises(RuntimeError):
            proactive_template_payload("test", "TEST_TEMPLATE", ["1"])

    def test_approved_template_url_buttons_validate_and_encode_parameters(self):
        with patch.dict(os.environ, {"TEST_TEMPLATE": "test_template"}):
            payload = proactive_template_payload("test", "TEST_TEMPLATE", ["1"], expected_parameters=1,
                                                 url_buttons=[(0, "date:2026-12-13")])
            component = payload["template"]["components"][1]
            self.assertEqual(component, {"type": "button", "sub_type": "url", "index": "0",
                                        "parameters": [{"type": "text", "text": "date%3A2026-12-13"}]})
            with self.assertRaises(ValueError):
                proactive_template_payload("test", "TEST_TEMPLATE", ["1"], expected_parameters=2)
            for buttons in ([(0, "a"), (0, "b")], [(10, "a")], [(0, "")], [(0, "a"), (1, "b"), (2, "c")]):
                with self.assertRaises(ValueError):
                    proactive_template_payload("test", "TEST_TEMPLATE", ["1"], url_buttons=buttons)

    def test_rollback_submenu_replies_use_text_recovery(self):
        with patch.object(config, "WHATSAPP_NATIVE_UX_ENABLED", False), patch.object(whatsapp, "_send", return_value=True) as send:
            whatsapp.send_progress_menu("test")
            self.assertEqual(send.call_args.args[0]["type"], "text")
            whatsapp.send_club_activities("test")
            self.assertEqual(send.call_args.args[0]["type"], "text")

    def test_calendar_inspection_is_read_only_and_uses_configured_version(self):
        from scripts import configure_admin_date_flow as script
        session = Mock()
        session.headers = {}
        responses = [
            {"data": [{"id": "test-phone"}]},
            {"data": [{"id": "test-flow", "name": script.FLOW_NAME, "status": "PUBLISHED"}]},
            {"status": "PUBLISHED", "validation_errors": [], "health_status": {"can_send_message": "AVAILABLE"}},
        ]
        session.request.side_effect = [SimpleNamespace(ok=True, json=lambda value=value: value) for value in responses]
        with patch.object(script.requests, "Session", return_value=session), patch.object(script, "dotenv_values", return_value={}), patch.dict(
            os.environ, {"WHATSAPP_TOKEN": "test-token", "PHONE_NUMBER_ID": "test-phone", "WHATSAPP_GRAPH_API_VERSION": "v27.0"}
        ), patch("sys.argv", ["configure_admin_date_flow", "--waba-id", "test-account", "--inspect"]), patch("sys.stdout", new_callable=io.StringIO):
            script.main()
        self.assertEqual(len(session.request.call_args_list), 3)
        for call in session.request.call_args_list:
            self.assertEqual(call.args[0], "GET")
            self.assertTrue(call.args[1].startswith("https://graph.facebook.com/v27.0/"))

    def test_status_callbacks_require_valid_signature_before_database_processing(self):
        payload = {"entry": [{"changes": [{"value": {"statuses": [{"status": "read"}]}}]}]}
        raw = json.dumps(payload).encode()
        request = SimpleNamespace(body=AsyncMock(return_value=raw), headers={"x-hub-signature-256": "sha256=bad"})
        with patch.object(webhook, "WHATSAPP_APP_SECRET", "test-secret"), patch.object(webhook, "ENV", "production"), patch.object(
            config, "WHATSAPP_DELIVERY_STATUS_ENABLED", True
        ), patch("app.services.delivery_status_service.record_status") as record:
            with self.assertRaises(webhook.HTTPException) as caught:
                asyncio.run(webhook.webhook(request, BackgroundTasks()))
            self.assertEqual(caught.exception.status_code, 403)
            record.assert_not_called()
            request.headers["x-hub-signature-256"] = "sha256=" + hmac.new(b"test-secret", raw, hashlib.sha256).hexdigest()
            self.assertEqual(asyncio.run(webhook.webhook(request, BackgroundTasks())), {"status": "ignored"})
            record.assert_called_once()

    def test_status_only_callbacks_never_enter_member_processing(self):
        payload = {"entry": [{"changes": [{"value": {"statuses": [{"id": "wamid.test", "status": "read"}]}}]}]}
        with patch.object(config, "WHATSAPP_DELIVERY_STATUS_ENABLED", True), patch(
            "app.services.delivery_status_service.record_status"
        ) as status, patch.object(webhook, "_process_webhook_message") as route:
            self.assertEqual(webhook.process_webhook_payload(payload, BackgroundTasks()), {"status": "ignored"})
        status.assert_called_once()
        route.assert_not_called()

    def test_mixed_webhook_batches_preserve_every_message_and_status(self):
        messages = [{"id": "a", "from": "test", "type": "text", "text": {"body": "MENU"}},
                    {"id": "b", "from": "test", "type": "text", "text": {"body": "MY HISTORY"}}]
        payload = {"entry": [{"changes": [{"value": {"messages": messages, "statuses": [{"status": "sent"}]}}]}]}
        with patch.object(config, "WHATSAPP_DELIVERY_STATUS_ENABLED", True), patch(
            "app.services.delivery_status_service.record_status"
        ) as status, patch.object(webhook, "_process_single_webhook_payload", return_value={"status": "ok"}) as process:
            result = webhook.process_webhook_payload(payload, BackgroundTasks())
        self.assertEqual(result["status"], "batch")
        self.assertEqual(process.call_count, 2)
        status.assert_called_once()

    def test_unknown_webhook_shapes_are_ignored(self):
        for payload in (None, [], {"entry": None}, {"entry": [None, {"changes": None}]},
                        {"entry": [{"changes": [{"value": {"messages": [None, {"type": "unknown"}]}}]}]}):
            self.assertEqual(webhook.process_webhook_payload(payload, BackgroundTasks()), {"status": "ignored"})


if __name__ == "__main__":
    unittest.main()
