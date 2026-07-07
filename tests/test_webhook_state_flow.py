import os
import hashlib
import hmac
import json
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from fastapi import BackgroundTasks

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from app import webhook as webhook_module
from app.flows import admin_flow as admin_flow_module


class FakeRequest:
    def __init__(self, payload, headers=None):
        self.payload = payload
        self.headers = headers or {}

    async def json(self):
        return self.payload

    async def body(self):
        return json.dumps(self.payload).encode("utf-8")


def text_payload(sender="27999999999", body="hello", message_id=None):
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": message_id,
                                    "from": sender,
                                    "type": "text",
                                    "text": {"body": body},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }


def button_payload(sender="27999999999", button_id="confirm", title="Confirm", message_id=None):
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": message_id,
                                    "from": sender,
                                    "type": "interactive",
                                    "interactive": {
                                        "button_reply": {
                                            "id": button_id,
                                            "title": title,
                                        }
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }


def member(**overrides):
    data = {
        "id": 42,
        "phone": "27999999999",
        "first_name": "Lindsay",
        "last_name": "Bull",
        "participation_type": "RUNNER",
        "profile_state": None,
        "popia_acknowledged": True,
        "last_seen_whats_new_version": None,
    }
    data.update(overrides)
    return data


def submission(**overrides):
    data = {
        "id": 101,
        "member_id": 42,
        "activity": "TT",
        "status": "PENDING",
        "tt_code_verified": True,
        "distance_text": None,
        "time_text": "",
        "seconds": 0,
    }
    data.update(overrides)
    return data


class WebhookStateFlowTests(unittest.IsolatedAsyncioTestCase):
    async def call_webhook(self, payload, member_data=None, submission_data=None, **patches):
        background_tasks = BackgroundTasks()

        with ExitStack() as stack:
            patch_names = [
                "send_text",
                "send_distance_buttons",
                "send_confirm_buttons",
                "send_participation_buttons",
                "send_profile_buttons",
                "send_both_submission_buttons",
                "send_main_menu_list",
                "send_leaderboard_menu_list",
                "send_admin_menu_list",
                "send_admin_edit_field_buttons",
                "send_admin_confirm_correction_buttons",
                "send_admin_member_center_buttons",
                "save_member_name",
                "set_profile_state",
                "clear_profile_state",
                "reopen_submission_for_edit",
                "verify_tt_code",
                "release_pending_submissions",
                "mark_attendance",
                "save_distance",
                "save_time",
                "confirm_submission",
                "get_previous_best",
                "get_runner_leaderboard",
                "get_overall_leaderboard",
                "get_member_rankings",
                "get_walker_feed",
                "get_tt_status",
                "get_pending_members",
                "get_tonight_unprompted_checked_in_members",
                "generate_tt_code",
                "get_admin_dashboard",
                "get_member_submission_history",
                "get_submission_for_admin",
                "search_members_for_admin",
                "correct_submission_by_id",
                "correct_submission_time_by_id",
                "correct_runner_pb",
                "correct_runner_time",
                "correct_runner_time_on_date",
                "send_admin_pending_actions",
                "get_user_profile",
                "has_seen_whats_new",
                "mark_whats_new_seen",
                "enqueue_post_confirm_messages",
                "run_due_jobs",
                "register_inbound_message",
                "mark_inbound_message_processed",
            ]
            mocks = {}
            for name in patch_names:
                primary = webhook_module if hasattr(webhook_module, name) else admin_flow_module
                mock = stack.enter_context(patch.object(primary, name))
                secondary = admin_flow_module if primary is webhook_module else webhook_module
                if hasattr(secondary, name):
                    stack.enter_context(patch.object(secondary, name, mock))
                mocks[name] = mock
            mocks["has_seen_whats_new"].return_value = True
            mocks["register_inbound_message"].return_value = True

            stack.enter_context(patch.object(webhook_module, "get_member", return_value=member_data or member()))
            stack.enter_context(patch.object(webhook_module, "create_member", side_effect=AssertionError))
            get_or_create_value = submission_data or submission()
            get_or_create_mock = stack.enter_context(
                patch.object(webhook_module, "get_or_create_submission")
            )
            if isinstance(get_or_create_value, list):
                get_or_create_mock.side_effect = get_or_create_value
            else:
                get_or_create_mock.return_value = get_or_create_value

            stack.enter_context(patch.object(webhook_module, "ensure_tt_open", return_value=(True, None)))

            for name, value in patches.items():
                if name in mocks:
                    mocks[name].side_effect = None
                    mocks[name].return_value = value
                else:
                    target = webhook_module if hasattr(webhook_module, name) else admin_flow_module
                    stack.enter_context(patch.object(target, name, value))

            result = await webhook_module.webhook(FakeRequest(payload), background_tasks)

        return result, mocks, background_tasks

    async def test_duplicate_whatsapp_message_is_ignored(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(body="help", message_id="wamid.duplicate"),
            register_inbound_message=False,
        )

        self.assertEqual(result, {"status": "duplicate"})
        mocks["register_inbound_message"].assert_called_once_with(
            "wamid.duplicate",
            "27999999999",
        )
        mocks["send_main_menu_list"].assert_not_called()
        mocks["mark_inbound_message_processed"].assert_not_called()

    async def test_webhook_rejects_invalid_signature_when_secret_configured(self):
        background_tasks = BackgroundTasks()

        with patch.object(webhook_module, "WHATSAPP_APP_SECRET", "secret"), patch.object(webhook_module, "ENV", "production"):
            with self.assertRaises(webhook_module.HTTPException) as ctx:
                await webhook_module.webhook(
                    FakeRequest(text_payload(body="help"), headers={"x-hub-signature-256": "sha256=bad"}),
                    background_tasks,
                )

        self.assertEqual(ctx.exception.status_code, 403)

    async def test_webhook_accepts_valid_signature_when_secret_configured(self):
        payload = text_payload(body="help")
        request = FakeRequest(payload)
        raw_body = await request.body()
        digest = hmac.new(b"secret", raw_body, hashlib.sha256).hexdigest()
        request.headers["x-hub-signature-256"] = f"sha256={digest}"

        with patch.object(webhook_module, "WHATSAPP_APP_SECRET", "secret"), patch.object(webhook_module, "ENV", "production"):
            result, mocks, _ = await self.call_webhook_with_request(request)

        self.assertEqual(result, {"status": "help"})
        mocks["send_main_menu_list"].assert_called_once_with("27999999999", False)

    async def call_webhook_with_request(self, request, member_data=None, submission_data=None, **patches):
        return await self._call_webhook_request(request, member_data, submission_data, **patches)

    async def _call_webhook_request(self, request, member_data=None, submission_data=None, **patches):
        background_tasks = BackgroundTasks()

        with ExitStack() as stack:
            patch_names = [
                "send_text",
                "send_distance_buttons",
                "send_confirm_buttons",
                "send_participation_buttons",
                "send_profile_buttons",
                "send_both_submission_buttons",
                "send_main_menu_list",
                "send_leaderboard_menu_list",
                "send_admin_menu_list",
                "send_admin_edit_field_buttons",
                "send_admin_confirm_correction_buttons",
                "send_admin_member_center_buttons",
                "save_member_name",
                "set_profile_state",
                "clear_profile_state",
                "reopen_submission_for_edit",
                "verify_tt_code",
                "release_pending_submissions",
                "mark_attendance",
                "save_distance",
                "save_time",
                "confirm_submission",
                "get_previous_best",
                "get_runner_leaderboard",
                "get_overall_leaderboard",
                "get_member_rankings",
                "get_walker_feed",
                "get_tt_status",
                "get_pending_members",
                "get_tonight_unprompted_checked_in_members",
                "generate_tt_code",
                "get_admin_dashboard",
                "get_member_submission_history",
                "get_submission_for_admin",
                "search_members_for_admin",
                "correct_submission_by_id",
                "correct_submission_time_by_id",
                "correct_runner_pb",
                "correct_runner_time",
                "correct_runner_time_on_date",
                "send_admin_pending_actions",
                "get_user_profile",
                "has_seen_whats_new",
                "mark_whats_new_seen",
                "enqueue_post_confirm_messages",
                "run_due_jobs",
                "register_inbound_message",
                "mark_inbound_message_processed",
            ]
            mocks = {}
            for name in patch_names:
                primary = webhook_module if hasattr(webhook_module, name) else admin_flow_module
                mock = stack.enter_context(patch.object(primary, name))
                secondary = admin_flow_module if primary is webhook_module else webhook_module
                if hasattr(secondary, name):
                    stack.enter_context(patch.object(secondary, name, mock))
                mocks[name] = mock
            mocks["has_seen_whats_new"].return_value = True
            mocks["register_inbound_message"].return_value = True

            stack.enter_context(patch.object(webhook_module, "get_member", return_value=member_data or member()))
            stack.enter_context(patch.object(webhook_module, "create_member", side_effect=AssertionError))
            get_or_create_value = submission_data or submission()
            get_or_create_mock = stack.enter_context(
                patch.object(webhook_module, "get_or_create_submission")
            )
            if isinstance(get_or_create_value, list):
                get_or_create_mock.side_effect = get_or_create_value
            else:
                get_or_create_mock.return_value = get_or_create_value

            stack.enter_context(patch.object(webhook_module, "ensure_tt_open", return_value=(True, None)))

            for name, value in patches.items():
                if name in mocks:
                    mocks[name].side_effect = None
                    mocks[name].return_value = value
                else:
                    target = webhook_module if hasattr(webhook_module, name) else admin_flow_module
                    stack.enter_context(patch.object(target, name, value))

            result = await webhook_module.webhook(request, background_tasks)

        return result, mocks, background_tasks

    async def test_verified_runner_resending_code_prompts_distance(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(body="9793"),
            submission_data=submission(distance_text=None, time_text=""),
        )

        self.assertEqual(result, {"status": "recover_awaiting_distance"})
        mocks["send_distance_buttons"].assert_called_once_with("27999999999")
        mocks["send_text"].assert_not_called()

    async def test_help_menu_for_member(self):
        result, mocks, _ = await self.call_webhook(text_payload(body="\\Help"))

        self.assertEqual(result, {"status": "help"})
        mocks["send_main_menu_list"].assert_called_once_with("27999999999", False)
        mocks["send_text"].assert_not_called()

    async def test_help_menu_for_admin_includes_admin_commands(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(sender="27722135094", body="menu"),
            member_data=member(phone="27722135094"),
        )

        self.assertEqual(result, {"status": "help"})
        mocks["send_main_menu_list"].assert_called_once_with("27722135094", True)

    async def test_admin_menu_text_clears_active_admin_edit_state(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(sender="27722135094", body="menu"),
            member_data=member(id=7, phone="27722135094", profile_state="ADMIN_CONFIRM|101|4|26:59"),
        )

        self.assertEqual(result, {"status": "help"})
        mocks["clear_profile_state"].assert_called_once_with(7)
        mocks["send_main_menu_list"].assert_called_once_with("27722135094", True)

    async def test_admin_menu_selection_opens_admin_tools(self):
        result, mocks, _ = await self.call_webhook(
            button_payload(sender="27722135094", button_id="admin_menu", title="Admin tools"),
            member_data=member(phone="27722135094"),
            generate_tt_code="1234",
            get_admin_dashboard={
                "summary": {
                    "checked_in": 12,
                    "submitted": 8,
                    "pending": 4,
                    "runners": 9,
                    "walkers": 2,
                    "both": 1,
                    "last_submission_at": None,
                },
                "pending": [{"first_name": "Asha", "last_name": "Runner"}],
            },
        )

        self.assertEqual(result, {"status": "admin_menu"})
        dashboard = mocks["send_text"].call_args.args[1]
        self.assertIn("Admin Dashboard", dashboard)
        self.assertIn("TT code: *1234*", dashboard)
        self.assertIn("Top pending: Asha Runner", dashboard)
        mocks["send_admin_menu_list"].assert_called_once_with("27722135094")

    async def test_admin_tools_text_clears_active_admin_edit_state(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(sender="27722135094", body="admin"),
            member_data=member(id=7, phone="27722135094", profile_state="ADMIN_SELECTED|101"),
            generate_tt_code="1234",
            get_admin_dashboard={
                "summary": {
                    "checked_in": 12,
                    "submitted": 8,
                    "pending": 4,
                    "runners": 9,
                    "walkers": 2,
                    "both": 1,
                    "last_submission_at": None,
                },
                "pending": [],
            },
        )

        self.assertEqual(result, {"status": "admin_menu"})
        mocks["clear_profile_state"].assert_called_once_with(7)
        mocks["send_admin_menu_list"].assert_called_once_with("27722135094")

    async def test_admin_menu_button_clears_active_admin_edit_state(self):
        result, mocks, _ = await self.call_webhook(
            button_payload(sender="27722135094", button_id="admin_menu", title="Admin tools"),
            member_data=member(id=7, phone="27722135094", profile_state="ADMIN_EDIT_TIME|101"),
            generate_tt_code="1234",
            get_admin_dashboard={
                "summary": {
                    "checked_in": 12,
                    "submitted": 8,
                    "pending": 4,
                    "runners": 9,
                    "walkers": 2,
                    "both": 1,
                    "last_submission_at": None,
                },
                "pending": [],
            },
        )

        self.assertEqual(result, {"status": "admin_menu"})
        mocks["clear_profile_state"].assert_called_once_with(7)
        mocks["send_admin_menu_list"].assert_called_once_with("27722135094")

    async def test_admin_status_command_returns_status_with_tools_hint(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(sender="27722135094", body="status"),
            member_data=member(phone="27722135094"),
            get_tt_status="TT status body",
        )

        self.assertEqual(result, {"status": "status"})
        mocks["send_text"].assert_called_once_with(
            "27722135094",
            "TT status body\n\nType ADMIN for tools.",
        )

    async def test_admin_recover_tonight_resends_prompts(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(sender="27722135094", body="recover tonight"),
            member_data=member(phone="27722135094"),
            get_tonight_unprompted_checked_in_members=[
                {"phone": "2771", "participation_type": "RUNNER"},
                {"phone": "2772", "participation_type": "WALKER"},
            ],
        )

        self.assertEqual(result, {"status": "recover_tonight", "count": 2})
        mocks["send_distance_buttons"].assert_called_once_with("2771")
        self.assertEqual(mocks["send_text"].call_args.args[0], "27722135094")
        self.assertIn("Resent tonight", mocks["send_text"].call_args.args[1])

    async def test_admin_pending_uses_action_buttons(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(sender="27722135094", body="pending"),
            member_data=member(phone="27722135094"),
            get_pending_members=[
                {
                    "first_name": "Lindsay",
                    "last_name": "Bull",
                    "phone": "27999999999",
                },
            ],
        )

        self.assertEqual(result, {"status": "pending_list"})
        mocks["send_admin_pending_actions"].assert_called_once()
        body = mocks["send_admin_pending_actions"].call_args.args[1]
        self.assertIn("Lindsay Bull", body)
        mocks["send_text"].assert_not_called()

    async def test_admin_find_member_lookup(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(sender="27722135094", body="find Lindsay"),
            member_data=member(phone="27722135094"),
            search_members_for_admin=[
                {
                    "id": 42,
                    "first_name": "Lindsay",
                    "last_name": "Bull",
                    "phone": "27999999999",
                    "participation_type": "RUNNER",
                    "leaderboard_opt_out": False,
                    "today_status": "COMPLETE",
                    "tt_code_verified": True,
                    "distance_text": "4",
                    "time_text": "27:41",
                },
            ],
        )

        self.assertEqual(result, {"status": "member_lookup", "count": 1})
        mocks["search_members_for_admin"].assert_called_once_with("Lindsay")
        sent = mocks["send_text"].call_args.args[1]
        self.assertIn("Member lookup: Lindsay", sent)
        self.assertIn("Member ID: 42", sent)
        self.assertIn("4km — 27:41", sent)
        self.assertIn("Reply with a number", sent)
        mocks["set_profile_state"].assert_called_once_with(42, "ADMIN_MEMBER_SEARCH|Lindsay")

    async def test_admin_member_search_selection_opens_command_center(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(sender="27722135094", body="1"),
            member_data=member(id=7, phone="27722135094", profile_state="ADMIN_MEMBER_SEARCH|Lindsay"),
            search_members_for_admin=[
                {
                    "id": 72,
                    "first_name": "Asha",
                    "last_name": "Runner",
                    "phone": "27999999999",
                    "participation_type": "BOTH",
                    "leaderboard_opt_out": False,
                    "today_status": "COMPLETE",
                    "tt_code_verified": True,
                    "distance_text": "6",
                    "time_text": "42:00",
                },
            ],
        )

        self.assertEqual(result, {"status": "admin_member_selected", "member_id": 72})
        mocks["set_profile_state"].assert_called_once_with(7, "ADMIN_MEMBER|72")
        body = mocks["send_admin_member_center_buttons"].call_args.args[1]
        self.assertIn("Member command center", body)
        self.assertIn("Member ID: 72", body)
        self.assertIn("Today: COMPLETE · 6km — 42:00", body)

    async def test_admin_member_center_correct_opens_history_selection(self):
        result, mocks, _ = await self.call_webhook(
            button_payload(sender="27722135094", button_id="admin_member_correct", title="Correct result"),
            member_data=member(id=7, phone="27722135094", profile_state="ADMIN_MEMBER|72"),
            get_member_submission_history=[
                {
                    "submission_id": 101,
                    "member_id": 72,
                    "first_name": "Asha",
                    "last_name": "Runner",
                    "event_date": "2026-06-09",
                    "distance_text": "6",
                    "time_text": "42:00",
                    "status": "COMPLETE",
                },
            ],
        )

        self.assertEqual(result, {"status": "admin_correct_history", "count": 1})
        mocks["get_member_submission_history"].assert_called_once_with("72")
        mocks["set_profile_state"].assert_called_once_with(7, "ADMIN_HISTORY|72")
        sent = mocks["send_text"].call_args.args[1]
        self.assertIn("Submission history: Asha Runner", sent)

    async def test_admin_history_lists_member_submission_dates_and_times(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(sender="27722135094", body="history 42"),
            member_data=member(phone="27722135094"),
            get_member_submission_history=[
                {
                    "member_id": 42,
                    "first_name": "Lindsay",
                    "last_name": "Bull",
                    "event_date": "2026-06-09",
                    "distance_text": "4",
                    "time_text": "27:41",
                    "status": "COMPLETE",
                },
                {
                    "member_id": 42,
                    "first_name": "Lindsay",
                    "last_name": "Bull",
                    "event_date": "2026-06-02",
                    "distance_text": "6",
                    "time_text": "42:00",
                    "status": "COMPLETE",
                },
            ],
        )

        self.assertEqual(result, {"status": "submission_history", "count": 2})
        mocks["get_member_submission_history"].assert_called_once_with("42")
        mocks["set_profile_state"].assert_called_once_with(42, "ADMIN_HISTORY|42")
        sent = mocks["send_text"].call_args.args[1]
        self.assertIn("Submission history: Lindsay Bull", sent)
        self.assertIn("Member ID: 42", sent)
        self.assertIn("2026-06-09: 4km — 27:41", sent)
        self.assertIn("2026-06-02: 6km — 42:00", sent)
        self.assertIn("Reply with a number", sent)

    async def test_admin_history_selection_opens_submission_details(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(sender="27722135094", body="1"),
            member_data=member(id=7, phone="27722135094", profile_state="ADMIN_HISTORY|42"),
            get_member_submission_history=[
                {
                    "submission_id": 101,
                    "member_id": 42,
                    "first_name": "Lindsay",
                    "last_name": "Bull",
                    "event_date": "2026-06-09",
                    "distance_text": "4",
                    "time_text": "27:41",
                    "status": "COMPLETE",
                },
            ],
        )

        self.assertEqual(result, {"status": "admin_history_selected", "submission_id": 101})
        mocks["set_profile_state"].assert_called_once_with(7, "ADMIN_SELECTED|101")
        sent = mocks["send_admin_edit_field_buttons"].call_args.args[1]
        self.assertIn("Selected submission", sent)
        self.assertIn("Date: 2026-06-09", sent)
        self.assertIn("Distance: 4km", sent)
        self.assertIn("Reply TIME, DISTANCE, or BOTH", sent)

    async def test_admin_selected_submission_prompts_for_time_edit(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(sender="27722135094", body="time"),
            member_data=member(id=7, phone="27722135094", profile_state="ADMIN_SELECTED|101"),
            get_submission_for_admin={
                "submission_id": 101,
                "first_name": "Lindsay",
                "last_name": "Bull",
                "event_date": "2026-06-09",
                "distance_text": "4",
                "time_text": "27:41",
            },
        )

        self.assertEqual(result, {"status": "admin_edit_time_prompt"})
        mocks["set_profile_state"].assert_called_once_with(7, "ADMIN_EDIT_TIME|101")
        mocks["send_text"].assert_called_once_with("27722135094", "Send the corrected time, e.g. 27:41.")

    async def test_admin_selected_submission_button_prompts_for_time_edit(self):
        result, mocks, _ = await self.call_webhook(
            button_payload(sender="27722135094", button_id="admin_edit_time", title="Time"),
            member_data=member(id=7, phone="27722135094", profile_state="ADMIN_SELECTED|101"),
            get_submission_for_admin={
                "submission_id": 101,
                "first_name": "Lindsay",
                "last_name": "Bull",
                "event_date": "2026-06-09",
                "distance_text": "4",
                "time_text": "27:41",
            },
        )

        self.assertEqual(result, {"status": "admin_edit_time_prompt"})
        mocks["set_profile_state"].assert_called_once_with(7, "ADMIN_EDIT_TIME|101")

    async def test_admin_time_edit_asks_for_confirmation_before_saving(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(sender="27722135094", body="26:59"),
            member_data=member(id=7, phone="27722135094", profile_state="ADMIN_EDIT_TIME|101"),
            get_submission_for_admin={
                "submission_id": 101,
                "first_name": "Lindsay",
                "last_name": "Bull",
                "event_date": "2026-06-09",
                "distance_text": "4",
                "time_text": "27:41",
            },
        )

        self.assertEqual(result, {"status": "admin_correction_confirmation", "submission_id": 101})
        mocks["set_profile_state"].assert_called_once_with(7, "ADMIN_CONFIRM_TIME|101|26:59")
        mocks["correct_submission_by_id"].assert_not_called()
        sent = mocks["send_admin_confirm_correction_buttons"].call_args.args[1]
        self.assertIn("Confirm correction", sent)
        self.assertIn("Change: 4km — 27:41", sent)
        self.assertIn("To: 4km — 26:59", sent)

    async def test_admin_time_edit_with_missing_distance_still_confirms_time_only(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(sender="27722135094", body="26:59"),
            member_data=member(id=7, phone="27722135094", profile_state="ADMIN_EDIT_TIME|101"),
            get_submission_for_admin={
                "submission_id": 101,
                "first_name": "Runner",
                "last_name": "MissingDistance",
                "event_date": "2026-06-09",
                "distance_text": None,
                "time_text": "",
            },
        )

        self.assertEqual(result, {"status": "admin_correction_confirmation", "submission_id": 101})
        mocks["set_profile_state"].assert_called_once_with(7, "ADMIN_CONFIRM_TIME|101|26:59")
        sent = mocks["send_admin_confirm_correction_buttons"].call_args.args[1]
        self.assertIn("Change: none", sent)
        self.assertIn("To: 26:59", sent)
        mocks["correct_submission_by_id"].assert_not_called()
        mocks["correct_submission_time_by_id"].assert_not_called()

    async def test_admin_time_confirmation_yes_saves_only_time(self):
        result, mocks, _ = await self.call_webhook(
            button_payload(sender="27722135094", button_id="admin_confirm_correction", title="Yes"),
            member_data=member(id=7, phone="27722135094", profile_state="ADMIN_CONFIRM_TIME|101|26:59"),
            correct_submission_time_by_id={
                "id": 101,
                "first_name": "Runner",
                "last_name": "MissingDistance",
                "distance_text": None,
                "old_distance_text": None,
                "old_time_text": "",
                "time_text": "26:59",
            },
        )

        self.assertEqual(result, {"status": "admin_submission_corrected", "submission_id": 101})
        mocks["correct_submission_time_by_id"].assert_called_once_with(101, "26:59", 1619, 7)
        mocks["correct_submission_by_id"].assert_not_called()
        sent = mocks["send_text"].call_args.args[1]
        self.assertIn("Now: 26:59", sent)

    async def test_admin_confirmation_yes_saves_selected_submission(self):
        result, mocks, _ = await self.call_webhook(
            button_payload(sender="27722135094", button_id="admin_confirm_correction", title="Yes"),
            member_data=member(id=7, phone="27722135094", profile_state="ADMIN_CONFIRM|101|4|26:59"),
            correct_submission_by_id={
                "id": 101,
                "first_name": "Lindsay",
                "last_name": "Bull",
                "old_distance_text": "4",
                "old_time_text": "27:41",
                "distance_text": "4",
                "time_text": "26:59",
            },
        )

        self.assertEqual(result, {"status": "admin_submission_corrected", "submission_id": 101})
        mocks["correct_submission_by_id"].assert_called_once_with(101, "4", "26:59", 1619, 7)
        mocks["correct_submission_time_by_id"].assert_not_called()
        mocks["clear_profile_state"].assert_called_once_with(7)
        sent = mocks["send_text"].call_args.args[1]
        self.assertIn("Submission corrected", sent)

    async def test_admin_confirmation_no_cancels_selected_submission(self):
        result, mocks, _ = await self.call_webhook(
            button_payload(sender="27722135094", button_id="admin_cancel_correction", title="No"),
            member_data=member(id=7, phone="27722135094", profile_state="ADMIN_CONFIRM|101|4|26:59"),
        )

        self.assertEqual(result, {"status": "admin_correction_cancelled"})
        mocks["correct_submission_by_id"].assert_not_called()
        mocks["correct_submission_time_by_id"].assert_not_called()
        mocks["clear_profile_state"].assert_called_once_with(7)

    async def test_admin_both_edit_asks_for_confirmation(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(sender="27722135094", body="6 42:00"),
            member_data=member(id=7, phone="27722135094", profile_state="ADMIN_EDIT_BOTH|101"),
            get_submission_for_admin={
                "submission_id": 101,
                "first_name": "Lindsay",
                "last_name": "Bull",
                "event_date": "2026-06-09",
                "distance_text": "4",
                "time_text": "27:41",
            },
        )

        self.assertEqual(result, {"status": "admin_correction_confirmation", "submission_id": 101})
        mocks["set_profile_state"].assert_called_once_with(7, "ADMIN_CONFIRM|101|6|42:00")
        mocks["correct_submission_by_id"].assert_not_called()

    async def test_admin_correct_date_updates_specific_submission_date(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(sender="27722135094", body="correct date 42 2026-06-09 6 42:00"),
            member_data=member(phone="27722135094"),
        )

        self.assertEqual(result, {"status": "admin_correct_confirmation"})
        mocks["set_profile_state"].assert_called_once_with(
            42,
            "ADMIN_CONFIRM_TYPED|DATE|42|2026-06-09|6|42:00",
        )
        mocks["correct_runner_time_on_date"].assert_not_called()
        mocks["correct_runner_time"].assert_not_called()
        mocks["correct_runner_pb"].assert_not_called()
        sent = mocks["send_admin_confirm_correction_buttons"].call_args.args[1]
        self.assertIn("Confirm correction", sent)
        self.assertIn("Result on 2026-06-09", sent)
        self.assertIn("New value: 6km — 42:00", sent)

    async def test_admin_correct_runner_time_updates_tonight_submission(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(sender="27722135094", body="correct 42 4 26:59"),
            member_data=member(phone="27722135094"),
        )

        self.assertEqual(result, {"status": "admin_correct_confirmation"})
        mocks["set_profile_state"].assert_called_once_with(
            42,
            "ADMIN_CONFIRM_TYPED|TODAY|42|-|4|26:59",
        )
        mocks["correct_runner_time"].assert_not_called()
        mocks["correct_runner_pb"].assert_not_called()
        sent = mocks["send_admin_confirm_correction_buttons"].call_args.args[1]
        self.assertIn("Tonight's result", sent)
        self.assertIn("New value: 4km — 26:59", sent)

    async def test_admin_correct_runner_time_rejects_bad_time(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(sender="27722135094", body="correct 42 4 soon"),
            member_data=member(phone="27722135094"),
        )

        self.assertEqual(result, {"status": "admin_correct_bad_time"})
        mocks["correct_runner_time"].assert_not_called()
        mocks["correct_runner_pb"].assert_not_called()
        mocks["send_text"].assert_called_once_with(
            "27722135094",
            "Time format must be 27:41 or 01:27:41.",
        )

    async def test_admin_correct_pb_updates_best_submission_across_dates(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(sender="27722135094", body="correct pb 42 4 26:59"),
            member_data=member(phone="27722135094"),
        )

        self.assertEqual(result, {"status": "admin_correct_confirmation"})
        mocks["set_profile_state"].assert_called_once_with(
            42,
            "ADMIN_CONFIRM_TYPED|PB|42|-|4|26:59",
        )
        mocks["correct_runner_pb"].assert_not_called()
        mocks["correct_runner_time"].assert_not_called()
        sent = mocks["send_admin_confirm_correction_buttons"].call_args.args[1]
        self.assertIn("Overall PB result", sent)
        self.assertIn("New value: 4km — 26:59", sent)

    async def test_admin_typed_confirmation_yes_saves_date_correction(self):
        result, mocks, _ = await self.call_webhook(
            button_payload(sender="27722135094", button_id="admin_confirm_correction", title="Yes"),
            member_data=member(
                id=7,
                phone="27722135094",
                profile_state="ADMIN_CONFIRM_TYPED|DATE|42|2026-06-09|6|42:00",
            ),
            correct_runner_time_on_date={
                "id": 101,
                "first_name": "Lindsay",
                "last_name": "Bull",
                "old_distance_text": "4",
                "old_time_text": "27:41",
                "distance_text": "6",
                "time_text": "42:00",
            },
        )

        self.assertEqual(result, {"status": "admin_date_corrected", "submission_id": 101})
        mocks["correct_runner_time_on_date"].assert_called_once_with(
            "42",
            "2026-06-09",
            "6",
            "42:00",
            2520,
            7,
        )
        sent = mocks["send_text"].call_args.args[1]
        self.assertIn("Dated result corrected", sent)
        self.assertIn("Was: 4km — 27:41", sent)
        self.assertIn("Now: 6km — 42:00", sent)

    async def test_admin_typed_confirmation_no_cancels_without_saving(self):
        result, mocks, _ = await self.call_webhook(
            button_payload(sender="27722135094", button_id="admin_cancel_correction", title="No"),
            member_data=member(
                id=7,
                phone="27722135094",
                profile_state="ADMIN_CONFIRM_TYPED|TODAY|42|-|4|26:59",
            ),
        )

        self.assertEqual(result, {"status": "admin_correction_cancelled"})
        mocks["correct_runner_time"].assert_not_called()
        mocks["correct_runner_time_on_date"].assert_not_called()
        mocks["correct_runner_pb"].assert_not_called()
        mocks["clear_profile_state"].assert_called_once_with(7)

    async def test_admin_correct_button_starts_guided_flow(self):
        result, mocks, _ = await self.call_webhook(
            button_payload(sender="27722135094", button_id="admin_correct", title="Correct result"),
            member_data=member(phone="27722135094"),
        )

        self.assertEqual(result, {"status": "admin_correct_find_prompt"})
        mocks["set_profile_state"].assert_called_once_with(42, "ADMIN_FIND_FOR_CORRECT")
        mocks["correct_runner_time"].assert_not_called()
        mocks["correct_runner_pb"].assert_not_called()
        sent = mocks["send_text"].call_args.args[1]
        self.assertIn("Send the member name or phone number", sent)

    async def test_help_menu_falls_back_to_text_if_list_send_fails(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(body="HELP"),
            send_main_menu_list=False,
        )

        self.assertEqual(result, {"status": "help"})
        sent = mocks["send_text"].call_args.args[1]
        self.assertIn("Irene AC Bot Menu", sent)
        self.assertIn("1 - Submit TT result", sent)

    async def test_unknown_button_during_pending_submission_recovers_prompt(self):
        result, mocks, _ = await self.call_webhook(
            button_payload(button_id="not_expected", title="Old button"),
            submission_data=submission(distance_text=None, time_text=""),
        )

        self.assertEqual(result, {"status": "unknown_button_awaiting_distance"})
        mocks["send_distance_buttons"].assert_called_once_with("27999999999")

    async def test_runner_with_distance_and_bad_time_gets_format_hint(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(body="soon"),
            submission_data=submission(distance_text="4", time_text=""),
        )

        self.assertEqual(result, {"status": "bad_time"})
        mocks["send_text"].assert_called_once_with("27999999999", "⏱ Format: 27:41 or 01:27:41")

    async def test_runner_valid_code_checks_in_and_prompts_distance(self):
        unverified = submission(tt_code_verified=False)
        verified = submission(tt_code_verified=True)

        result, mocks, _ = await self.call_webhook(
            text_payload(body="9793"),
            submission_data=[unverified, verified],
            is_valid_tt_code=lambda _code: True,
            verify_tt_code=verified,
            release_pending_submissions=lambda _member_id: None,
            mark_attendance=lambda _member_id: None,
        )

        self.assertEqual(result, {"status": "code_ok_distance"})
        mocks["send_text"].assert_called_once_with("27999999999", "✅ Checked in!")
        mocks["send_distance_buttons"].assert_called_once_with("27999999999")

    async def test_runner_valid_code_sends_whats_new_once_when_unseen(self):
        unverified = submission(tt_code_verified=False)
        verified = submission(tt_code_verified=True)

        result, mocks, _ = await self.call_webhook(
            text_payload(body="9793"),
            submission_data=[unverified, verified],
            is_valid_tt_code=lambda _code: True,
            verify_tt_code=verified,
            release_pending_submissions=lambda _member_id: None,
            mark_attendance=lambda _member_id: None,
            has_seen_whats_new=False,
        )

        self.assertEqual(result, {"status": "code_ok_distance"})
        self.assertEqual(mocks["send_text"].call_count, 2)
        self.assertEqual(mocks["send_text"].call_args_list[0].args, ("27999999999", "✅ Checked in!"))
        whats_new = mocks["send_text"].call_args_list[1].args[1]
        self.assertIn("What’s new", whats_new)
        self.assertIn("The Irene Shop", whats_new)
        self.assertIn("Irene League Standings", whats_new)
        mocks["mark_whats_new_seen"].assert_called_once_with(42, webhook_module.WHATS_NEW_VERSION)
        mocks["send_distance_buttons"].assert_called_once_with("27999999999")

    async def test_menu_submit_shortcut_asks_for_code_when_not_checked_in(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(body="1"),
            submission_data=submission(tt_code_verified=False),
        )

        self.assertEqual(result, {"status": "menu_submit_await_code"})
        mocks["send_text"].assert_called_once_with(
            "27999999999",
            "🔑 Send tonight's TT code to check in, or type MENU to go back.",
        )

    async def test_menu_profile_shortcut_opens_profile(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(body="2"),
            get_user_profile={"total_runs": 0, "pbs": [], "recent": []},
        )

        self.assertEqual(result, {"status": "profile"})
        mocks["send_profile_buttons"].assert_called_once()

    async def test_menu_leaderboard_shortcut_opens_leaderboard_menu(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(body="4"),
        )

        self.assertEqual(result, {"status": "leaderboards_menu"})
        mocks["send_leaderboard_menu_list"].assert_called_once_with("27999999999")

    async def test_tonight_leaderboard_command_sends_tonight_results(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(body="tonight"),
            get_runner_leaderboard=[],
            get_walker_feed=[],
        )

        self.assertEqual(result, {"status": "leaderboard"})
        mocks["send_text"].assert_called_once()

    async def test_menu_overall_leaderboard_marks_member_rank(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(body="5"),
            get_overall_leaderboard=[
                {
                    "member_id": 7,
                    "first_name": "Asha",
                    "last_name": "Runner",
                    "distance_text": "8",
                    "time_text": "35:10",
                    "best_seconds": 2110,
                    "position": 1,
                },
                {
                    "member_id": 42,
                    "first_name": "Lindsay",
                    "last_name": "Bull",
                    "distance_text": "8",
                    "time_text": "42:00",
                    "best_seconds": 2520,
                    "position": 11,
                },
            ],
        )

        self.assertEqual(result, {"status": "overall_leaderboard"})
        mocks["get_overall_leaderboard"].assert_called_once_with(42)
        sent = mocks["send_text"].call_args.args[1]
        self.assertIn("Overall TT Leaderboard", sent)
        self.assertIn("Asha Runner", sent)
        self.assertIn("Lindsay Bull — 42:00 ← you", sent)

    async def test_my_ranking_command_sends_private_rankings(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(body="my ranking"),
            get_member_rankings=[
                {
                    "member_id": 42,
                    "first_name": "Lindsay",
                    "last_name": "Bull",
                    "distance_text": "4",
                    "time_text": "27:41",
                    "best_seconds": 1661,
                    "position": 12,
                },
            ],
        )

        self.assertEqual(result, {"status": "my_ranking"})
        mocks["get_member_rankings"].assert_called_once_with(42)
        sent = mocks["send_text"].call_args.args[1]
        self.assertIn("your PB rankings", sent)
        self.assertIn("4km — #12 · PB 27:41", sent)

    async def test_progress_command_sends_personal_progress(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(body="3"),
            get_user_profile={
                "total_runs": 6,
                "latest": {
                    "distance_text": "4",
                    "time_text": "27:41",
                    "seconds": 1661,
                },
                "pbs": [
                    {
                        "distance_text": "4",
                        "best_seconds": 1661,
                    }
                ],
                "recent": [],
            },
        )

        self.assertEqual(result, {"status": "progress"})
        sent = mocks["send_text"].call_args.args[1]
        self.assertIn("Lindsay, your progress", sent)
        self.assertIn("Latest: 4km — 27:41", sent)

    async def test_list_menu_progress_selection_sends_personal_progress(self):
        result, mocks, _ = await self.call_webhook(
            button_payload(button_id="menu_progress", title="My progress"),
            get_user_profile={
                "total_runs": 0,
                "latest": None,
                "pbs": [],
                "recent": [],
            },
        )

        self.assertEqual(result, {"status": "progress"})
        mocks["send_text"].assert_called_once()

    async def test_shop_menu_selection_sends_shop_link(self):
        result, mocks, _ = await self.call_webhook(
            button_payload(button_id="menu_shop", title="The Irene Shop"),
        )

        self.assertEqual(result, {"status": "shop"})
        sent = mocks["send_text"].call_args.args[1]
        self.assertIn("The Irene Shop", sent)
        self.assertIn("https://store126837536.shop.netcash.co.za/products", sent)

    async def test_shop_text_alias_sends_shop_link(self):
        result, mocks, _ = await self.call_webhook(text_payload(body="SHOP"))

        self.assertEqual(result, {"status": "shop"})
        self.assertIn("store126837536.shop.netcash.co.za/products", mocks["send_text"].call_args.args[1])

    async def test_league_standings_menu_selection_sends_link(self):
        result, mocks, _ = await self.call_webhook(
            button_payload(button_id="menu_league_standings", title="League standings"),
        )

        self.assertEqual(result, {"status": "league_standings"})
        sent = mocks["send_text"].call_args.args[1]
        self.assertIn("The Irene League Standings", sent)
        self.assertIn("https://iac-league-web.onrender.com", sent)

    async def test_league_text_alias_sends_link(self):
        result, mocks, _ = await self.call_webhook(text_payload(body="LEAGUE"))

        self.assertEqual(result, {"status": "league_standings"})
        self.assertIn("iac-league-web.onrender.com", mocks["send_text"].call_args.args[1])

    async def test_runner_distance_then_time_prompts_confirmation(self):
        with self.subTest("distance button"):
            updated = submission(distance_text="4", time_text="")
            result, mocks, _ = await self.call_webhook(
                button_payload(button_id="4km", title="4 km"),
                submission_data=submission(distance_text=None, time_text=""),
                save_distance=updated,
            )

            self.assertEqual(result, {"status": "distance"})
            mocks["save_distance"].assert_called_once_with(101, "4")
            mocks["send_text"].assert_called_once_with("27999999999", "⏱ Send your time.")

        with self.subTest("time text"):
            saved = submission(distance_text="4", time_text="27:41", seconds=1661)
            result, mocks, _ = await self.call_webhook(
                text_payload(body="27:41"),
                submission_data=submission(distance_text="4", time_text=""),
                save_time=saved,
            )

            self.assertEqual(result, {"status": "confirm"})
            mocks["save_time"].assert_called_once_with(101, "27:41", 1661)
            mocks["send_confirm_buttons"].assert_called_once_with("27999999999", "4", "27:41")

    async def test_walker_logs_workout(self):
        saved = submission(distance_text=None, time_text="Easy 5km walk", seconds=0)
        completed = submission(status="COMPLETE", distance_text=None, time_text="Easy 5km walk", seconds=0)

        result, mocks, _ = await self.call_webhook(
            text_payload(body="Easy 5km walk"),
            member_data=member(participation_type="WALKER"),
            submission_data=submission(distance_text=None, time_text=""),
            save_time=saved,
            confirm_submission=completed,
        )

        self.assertEqual(result, {"status": "walker_done"})
        mocks["save_time"].assert_called_once_with(101, "EASY 5KM WALK", 0)
        mocks["confirm_submission"].assert_called_once_with(101)
        mocks["send_text"].assert_called_once_with("27999999999", "🚶 Workout logged! Well done.")

    async def test_both_user_can_choose_distance_or_workout(self):
        with self.subTest("distance choice"):
            result, mocks, _ = await self.call_webhook(
                button_payload(button_id="submit_distance", title="Distance"),
                member_data=member(participation_type="BOTH"),
                submission_data=submission(distance_text=None, time_text=""),
            )

            self.assertEqual(result, {"status": "both_distance"})
            mocks["clear_profile_state"].assert_called_once_with(42)
            mocks["send_distance_buttons"].assert_called_once_with("27999999999")

        with self.subTest("workout choice"):
            result, mocks, _ = await self.call_webhook(
                button_payload(button_id="submit_workout", title="Workout"),
                member_data=member(participation_type="BOTH"),
                submission_data=submission(distance_text=None, time_text=""),
            )

            self.assertEqual(result, {"status": "both_workout"})
            mocks["send_text"].assert_called_once_with("27999999999", "🚶 Describe your workout.")

    async def test_profile_name_edit_clears_state(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(body="Lindsay Bull"),
            member_data=member(profile_state="EDIT_NAME"),
        )

        self.assertEqual(result, {"status": "profile_name_updated"})
        mocks["save_member_name"].assert_called_once_with(42, "Lindsay", "Bull")
        mocks["clear_profile_state"].assert_called_once_with(42)
        mocks["send_text"].assert_called_once_with("27999999999", "✅ Name updated.")

    async def test_complete_submission_edit_reopens_and_prompts_distance(self):
        reopened = submission(status="PENDING", distance_text=None, time_text="")
        result, mocks, _ = await self.call_webhook(
            button_payload(button_id="edit", title="Edit"),
            submission_data=submission(
                status="COMPLETE",
                distance_text="4",
                time_text="27:41",
                seconds=1661,
            ),
            reopen_submission_for_edit=reopened,
        )

        self.assertEqual(result, {"status": "edit_existing"})
        mocks["reopen_submission_for_edit"].assert_called_once_with(101)
        mocks["send_text"].assert_called_once_with(
            "27999999999",
            "No problem. Let’s fix your result from the start.",
        )
        mocks["send_distance_buttons"].assert_called_once_with("27999999999")

    async def test_fix_result_command_reopens_and_prompts_distance(self):
        reopened = submission(status="PENDING", distance_text=None, time_text="")
        result, mocks, _ = await self.call_webhook(
            text_payload(body="wrong time"),
            submission_data=submission(
                status="COMPLETE",
                distance_text="4",
                time_text="27:41",
                seconds=1661,
            ),
            reopen_submission_for_edit=reopened,
        )

        self.assertEqual(result, {"status": "fix_result"})
        mocks["reopen_submission_for_edit"].assert_called_once_with(101)
        mocks["send_distance_buttons"].assert_called_once_with("27999999999")

    async def test_resume_command_continues_pending_submission(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(body="hi"),
            submission_data=submission(distance_text="4", time_text=""),
        )

        self.assertEqual(result, {"status": "resume_awaiting_time"})
        mocks["send_text"].assert_called_once_with(
            "27999999999",
            "⏱ Send your time, for example 27:41 or 01:27:41.",
        )

    async def test_unknown_text_opens_menu_recovery(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(body="banana"),
            submission_data=submission(
                status="CANCELLED",
                tt_code_verified=True,
                distance_text=None,
                time_text="",
            ),
        )

        self.assertEqual(result, {"status": "fallback_help"})
        mocks["send_text"].assert_called_once_with(
            "27999999999",
            "I can help with submitting a result, checking progress, or leaderboards.",
        )
        mocks["send_main_menu_list"].assert_called_once_with("27999999999", False)

    async def test_confirm_replies_fast_and_schedules_followups(self):
        completed = submission(
            status="COMPLETE",
            distance_text="4",
            time_text="27:41",
            seconds=1661,
        )

        result, mocks, background_tasks = await self.call_webhook(
            button_payload(button_id="confirm", title="Confirm"),
            submission_data=submission(distance_text="4", time_text="27:41", seconds=1661),
            get_previous_best=1800,
            confirm_submission=completed,
        )

        self.assertEqual(result, {"status": "done"})
        mocks["send_text"].assert_called_once_with("27999999999", "TT recorded.")
        mocks["enqueue_post_confirm_messages"].assert_called_once()
        mocks["get_runner_leaderboard"].assert_not_called()
        self.assertEqual(len(background_tasks.tasks), 1)

    async def test_post_confirm_followup_sends_fallback_coach_message(self):
        messages = []

        with ExitStack() as stack:
            stack.enter_context(patch.object(webhook_module, "send_text", side_effect=lambda _to, body: messages.append(body)))
            stack.enter_context(
                patch.object(
                    webhook_module,
                    "get_user_profile",
                    return_value={
                        "total_runs": 5,
                        "recent": [{"seconds": 1600}, {"seconds": 1660}, {"seconds": 1720}],
                    },
                )
            )
            stack.enter_context(patch.object(webhook_module, "coach_reply", return_value="Keep building steadily."))
            stack.enter_context(
                patch.object(
                    webhook_module,
                    "get_runner_leaderboard",
                    return_value=[
                        {
                            "member_id": 42,
                            "distance_text": "4",
                            "position": 2,
                        }
                    ],
                )
            )
            stack.enter_context(patch.object(webhook_module, "get_walker_feed", return_value=[]))

            webhook_module.send_post_confirm_messages(
                "27999999999",
                member(),
                submission(status="COMPLETE", distance_text="4", time_text="27:41", seconds=1661),
                previous_best=1800,
            )

        self.assertEqual(len(messages), 1)
        self.assertIn("*Lindsay, here’s your TT recap*", messages[0])
        self.assertIn("4km — 27:41", messages[0])
        self.assertIn("Pace: 6:55/km", messages[0])
        self.assertIn("🚀 PB by 2:19", messages[0])
        self.assertIn("Season TTs: 5", messages[0])
        self.assertIn("🏆 Position: 2", messages[0])
        self.assertIn("🎉 Milestone: 5 TTs logged", messages[0])
        self.assertIn("🥇 Badge: 4km PB", messages[0])
        self.assertIn("🧠 Coach: Keep building steadily.", messages[0])


if __name__ == "__main__":
    unittest.main()
