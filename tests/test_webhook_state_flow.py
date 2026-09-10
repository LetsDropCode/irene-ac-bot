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


def self_correction(**overrides):
    data = {
        "id": 501,
        "member_id": 42,
        "submission_id": 101,
        "mode": "RUN",
        "distance_text": None,
        "time_text": None,
        "seconds": None,
        "event_date": "2026-09-08",
        "original_distance_text": "8",
        "original_time_text": "43:21",
        "original_seconds": 2601,
    }
    data.update(overrides)
    return data


class WebhookStateFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_member_receives_irene_logo_when_public_url_is_configured(self):
        with patch.object(webhook_module, "get_member", return_value=None), patch.object(
            webhook_module, "create_member"
        ) as create_member, patch.object(webhook_module, "PUBLIC_BASE_URL", "https://bot.example.com"), patch.object(
            webhook_module, "send_image"
        ) as send_image, patch.object(webhook_module, "send_text") as send_text:
            result = webhook_module._process_webhook_message(
                "27999999999", "HI", None, BackgroundTasks()
            )

        self.assertEqual(result, {"status": "popia"})
        send_image.assert_called_once_with(
            "27999999999",
            "https://bot.example.com/assets/irene-tree-logo.jpeg",
            "Welcome to Irene Athletics Club — Serious about our frun.",
        )
        send_text.assert_called_once()
        create_member.assert_not_called()

    async def test_unknown_ok_creates_an_acknowledged_member(self):
        created = member(
            first_name="Unknown",
            last_name="Member",
            participation_type=None,
            popia_acknowledged=True,
        )
        with patch.object(webhook_module, "get_member", return_value=None), patch.object(
            webhook_module, "create_member", return_value=created
        ) as create_member, patch.object(webhook_module, "send_text") as send_text:
            result = webhook_module._process_webhook_message(
                "27999999999", "OK", None, BackgroundTasks()
            )

        self.assertEqual(result, {"status": "popia_ack"})
        create_member.assert_called_once_with("27999999999", popia_acknowledged=True)
        self.assertIn("first and last name", send_text.call_args.args[1])

    async def test_unknown_decline_does_not_create_member(self):
        with patch.object(webhook_module, "get_member", return_value=None), patch.object(
            webhook_module, "create_member"
        ) as create_member, patch.object(webhook_module, "send_text") as send_text:
            result = webhook_module._process_webhook_message(
                "27999999999", "NO THANKS", None, BackgroundTasks()
            )

        self.assertEqual(result, {"status": "consent_declined"})
        create_member.assert_not_called()
        self.assertIn("no TT profile or results", send_text.call_args.args[1])

    async def call_webhook(self, payload, member_data=None, submission_data=None, **patches):
        background_tasks = BackgroundTasks()

        with ExitStack() as stack:
            # Production has no built-in administrators.  Declare the fixture
            # admin explicitly so admin-routing tests do not depend on a
            # committed phone-number default.
            stack.enter_context(
                patch.object(webhook_module, "ADMIN_NUMBERS", frozenset({"27722135094"}))
            )
            patch_names = [
                "send_image",
                "send_text",
                "send_distance_buttons",
                "send_confirm_buttons",
                "send_workout_confirm_buttons",
                "send_self_correction_confirm_buttons",
                "send_participation_buttons",
                "send_leaderboard_visibility_buttons",
                "send_profile_buttons",
                "send_both_submission_buttons",
                "send_main_menu_list",
                "send_leaderboard_menu_list",
                "send_admin_menu_list",
                "send_admin_code",
                "send_admin_leaderboard_menu_list",
                "send_admin_edit_field_buttons",
                "send_admin_confirm_correction_buttons",
                "send_admin_member_center_buttons",
                "save_member_name",
                "save_participation_type",
                "set_leaderboard_visibility",
                "set_profile_state",
                "clear_profile_state",
                "reopen_submission_for_edit",
                "reopen_workout_submission_for_edit",
                "set_submission_mode",
                "set_submission_mode",
                "verify_tt_code",
                "release_pending_submissions",
                "get_resumable_submission",
                "get_active_submission",
                "ensure_tt_open",
                "mark_attendance",
                "save_distance",
                "save_time",
                "save_workout_for_confirmation",
                "confirm_workout_submission",
                "confirm_submission",
                "get_completed_submission_for_current_event",
                "get_self_correctable_tt_submission",
                "start_member_self_correction",
                "get_member_self_correction",
                "save_member_self_correction_distance",
                "save_member_self_correction_time",
                "save_member_self_correction_workout",
                "apply_member_self_correction",
                "cancel_member_self_correction",
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
                "opt_out_leaderboard",
                "opt_in_leaderboard",
                "enqueue_post_confirm_messages",
                "run_due_jobs",
                "get_queue_health",
                "get_failed_jobs",
                "retry_failed_jobs",
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
            mocks["get_resumable_submission"].return_value = None
            mocks["get_member_self_correction"].return_value = None
            mocks["get_completed_submission_for_current_event"].return_value = None
            mocks["ensure_tt_open"].return_value = (True, None)

            stack.enter_context(patch.object(webhook_module, "get_member", return_value=member_data or member()))
            stack.enter_context(patch.object(webhook_module, "create_member", side_effect=AssertionError))
            get_or_create_value = submission_data or submission()
            mocks["get_active_submission"].return_value = (
                get_or_create_value[0]
                if isinstance(get_or_create_value, list)
                else get_or_create_value
            )
            get_or_create_mock = stack.enter_context(
                patch.object(webhook_module, "get_or_create_submission")
            )
            if isinstance(get_or_create_value, list):
                get_or_create_mock.side_effect = get_or_create_value
            else:
                get_or_create_mock.return_value = get_or_create_value
            mocks["get_or_create_submission"] = get_or_create_mock

            for name, value in patches.items():
                if name in mocks:
                    if isinstance(value, Exception):
                        mocks[name].side_effect = value
                    else:
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

    async def test_existing_member_stop_leaderboard_hides_public_results_without_deleting_data(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(body="STOP LEADERBOARD"),
        )

        self.assertEqual(result, {"status": "opt_out"})
        mocks["opt_out_leaderboard"].assert_called_once_with("27999999999")
        mocks["opt_in_leaderboard"].assert_not_called()
        sent = mocks["send_text"].call_args.args[1]
        self.assertIn("hidden from public leaderboards", sent)
        self.assertIn("still saved privately", sent)

    async def test_opted_out_member_can_start_sharing_again(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(body="START SHARING"),
            member_data=member(leaderboard_opt_out=True),
        )

        self.assertEqual(result, {"status": "opt_in"})
        mocks["opt_in_leaderboard"].assert_called_once_with("27999999999")
        mocks["opt_out_leaderboard"].assert_not_called()
        self.assertIn("public leaderboards again", mocks["send_text"].call_args.args[1])

    async def test_existing_acknowledged_member_is_not_sent_to_onboarding(self):
        result, mocks, _ = await self.call_webhook(text_payload(body="PROFILE"))

        self.assertEqual(result, {"status": "profile"})
        mocks["send_profile_buttons"].assert_called_once()
        mocks["send_text"].assert_not_called()

    async def test_profile_onboarding_visibility_choice_is_public_and_never_creates_submission(self):
        incomplete = member(
            first_name="Unknown",
            last_name="Member",
            participation_type=None,
        )
        result, mocks, _ = await self.call_webhook(
            text_payload(body="Lindsay Bull"),
            member_data=incomplete,
            ensure_tt_open=(False, "⛔ Time Trials only happen on *Tuesdays*."),
        )

        self.assertEqual(result, {"status": "profile_done"})
        mocks["save_member_name"].assert_called_once_with(42, "Lindsay", "Bull")
        mocks["set_profile_state"].assert_called_once_with(42, "ONBOARDING_PARTICIPATION")
        mocks["get_or_create_submission"].assert_not_called()

        result, mocks, _ = await self.call_webhook(
            button_payload(button_id="RUNNER", title="Runner"),
            member_data=member(
                first_name="Lindsay",
                last_name="Bull",
                participation_type=None,
                profile_state="ONBOARDING_PARTICIPATION",
            ),
            ensure_tt_open=(False, "⏱ Submissions open at *17:00*."),
        )

        self.assertEqual(result, {"status": "onboarding_await_visibility"})
        mocks["save_participation_type"].assert_called_once_with(42, "RUNNER")
        mocks["set_profile_state"].assert_called_once_with(42, "ONBOARDING_LEADERBOARD")
        mocks["send_leaderboard_visibility_buttons"].assert_called_once_with("27999999999")
        mocks["get_or_create_submission"].assert_not_called()

        result, mocks, _ = await self.call_webhook(
            button_payload(button_id="onboarding_show_results", title="Show my results"),
            member_data=member(
                first_name="Lindsay",
                last_name="Bull",
                participation_type="RUNNER",
                profile_state="ONBOARDING_LEADERBOARD",
                leaderboard_visibility_set=False,
            ),
            ensure_tt_open=(False, "⏱ Submissions open at *17:00*."),
        )

        self.assertEqual(result, {"status": "profile_complete"})
        mocks["set_leaderboard_visibility"].assert_called_once_with(42, False)
        mocks["get_or_create_submission"].assert_not_called()

    async def test_profile_onboarding_visibility_choice_can_be_private(self):
        result, mocks, _ = await self.call_webhook(
            button_payload(button_id="onboarding_keep_private", title="Keep private"),
            member_data=member(
                profile_state="ONBOARDING_LEADERBOARD",
                leaderboard_visibility_set=False,
            ),
        )

        self.assertEqual(result, {"status": "profile_complete"})
        mocks["set_leaderboard_visibility"].assert_called_once_with(42, True)
        self.assertIn("stay private", mocks["send_text"].call_args.args[1])

    async def test_abandoned_visibility_onboarding_resumes_without_submission(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(body="HI"),
            member_data=member(
                profile_state="ONBOARDING_LEADERBOARD",
                leaderboard_visibility_set=False,
            ),
        )

        self.assertEqual(result, {"status": "onboarding_await_visibility"})
        mocks["send_leaderboard_visibility_buttons"].assert_called_once_with("27999999999")
        mocks["get_or_create_submission"].assert_not_called()

    async def test_private_member_can_still_view_own_progress(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(body="PROGRESS"),
            member_data=member(leaderboard_opt_out=True, leaderboard_visibility_set=True),
            get_user_profile={"total_runs": 0, "latest": None, "pbs": [], "recent": []},
        )

        self.assertEqual(result, {"status": "progress"})
        mocks["get_user_profile"].assert_called_once_with(42)

    async def test_non_tt_commands_and_greeting_never_create_submission(self):
        for command in ("HI", "PROFILE", "PROGRESS", "LEADERBOARDS", "SHOP", "LEAGUE"):
            with self.subTest(command=command):
                result, mocks, _ = await self.call_webhook(
                    text_payload(body=command),
                    get_active_submission=None,
                    ensure_tt_open=(False, "⛔ Time Trials only happen on *Tuesdays*."),
                    get_user_profile={"total_runs": 0, "latest": None, "pbs": [], "recent": []},
                )

                self.assertNotEqual(result["status"], "closed")
                mocks["get_or_create_submission"].assert_not_called()

    async def test_greeting_and_submit_availability_by_tt_state(self):
        cases = [
            ("Monday HI", "HI", None, (False, "⛔ Time Trials only happen on *Tuesdays*."), "greeting"),
            ("Monday SUBMIT", "SUBMIT", None, (False, "⛔ Time Trials only happen on *Tuesdays*."), "closed"),
            ("Tuesday before opening HI", "HI", None, (False, "⏱ Submissions open at *17:00*."), "greeting"),
            ("Tuesday before opening SUBMIT", "SUBMIT", None, (False, "⏱ Submissions open at *17:00*."), "closed"),
            ("Tuesday during TT HI", "HI", None, (True, None), "greeting"),
            ("Tuesday during TT SUBMIT", "SUBMIT", None, (True, None), "await_code"),
            ("Tuesday checked-in pending HI", "HI", submission(tt_code_verified=True), (True, None), "greeting_awaiting_distance"),
            ("Wednesday noon verified pending HI", "HI", submission(tt_code_verified=True, event_date="2026-09-08"), (True, None), "greeting_awaiting_distance"),
            ("Wednesday after deadline HI", "HI", submission(tt_code_verified=True, event_date="2026-09-08"), (False, "⛔ The deadline for the 8 September TT was *13:00* today."), "greeting"),
            ("Completed result HI", "HI", None, (False, "⛔ Time Trials only happen on *Tuesdays*."), "greeting"),
        ]

        for label, command, active, gate_result, expected_status in cases:
            with self.subTest(label=label):
                resumable = active if active and active.get("event_date") else None
                result, mocks, _ = await self.call_webhook(
                    text_payload(body=command),
                    get_active_submission=None if resumable else active,
                    get_resumable_submission=resumable,
                    ensure_tt_open=gate_result,
                )

                self.assertEqual(result, {"status": expected_status})
                mocks["get_or_create_submission"].assert_not_called()

                if expected_status == "greeting":
                    self.assertIn("Hi Lindsay", mocks["send_text"].call_args.args[1])
                    if active is None:
                        mocks["ensure_tt_open"].assert_not_called()
                if expected_status == "await_code":
                    self.assertIn("TT code", mocks["send_text"].call_args.args[1])

    async def test_closed_new_tt_request_does_not_create_submission(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(body="SUBMIT"),
            get_active_submission=None,
            ensure_tt_open=(False, "⏱ Submissions open at *17:00*."),
        )

        self.assertEqual(result, {"status": "closed"})
        mocks["get_or_create_submission"].assert_not_called()

    async def test_new_submission_is_created_only_after_open_gate_and_valid_code(self):
        unverified = submission(tt_code_verified=False)
        verified = submission(tt_code_verified=True)
        result, mocks, _ = await self.call_webhook(
            text_payload(body="9793"),
            get_active_submission=None,
            ensure_tt_open=(True, None),
            is_valid_tt_code=lambda _code: True,
            verify_tt_code=verified,
            release_pending_submissions=lambda _member_id: None,
            mark_attendance=lambda _member_id: None,
            submission_data=unverified,
        )

        self.assertEqual(result, {"status": "code_ok_distance"})
        mocks["get_or_create_submission"].assert_called_once_with(42)

    async def test_expired_verified_tuesday_submission_cannot_resume(self):
        tuesday_pending = submission(event_date="2026-09-01", tt_code_verified=True)
        result, mocks, _ = await self.call_webhook(
            text_payload(body="RESUME"),
            submission_data=tuesday_pending,
            ensure_tt_open=(False, "⛔ The deadline for the 1 September TT was *13:00* today."),
        )

        self.assertEqual(result, {"status": "closed"})
        mocks["send_distance_buttons"].assert_not_called()
        mocks["get_or_create_submission"].assert_not_called()

    async def test_webhook_rejects_invalid_signature_when_secret_configured(self):
        background_tasks = BackgroundTasks()

        with patch.object(webhook_module, "WHATSAPP_APP_SECRET", "secret"), patch.object(webhook_module, "ENV", "production"):
            with self.assertRaises(webhook_module.HTTPException) as ctx:
                await webhook_module.webhook(
                    FakeRequest(text_payload(body="help"), headers={"x-hub-signature-256": "sha256=bad"}),
                    background_tasks,
                )

        self.assertEqual(ctx.exception.status_code, 403)

    async def test_webhook_rejects_missing_signature_in_production(self):
        with patch.object(webhook_module, "WHATSAPP_APP_SECRET", "secret"), patch.object(
            webhook_module, "ENV", "production"
        ):
            with self.assertRaises(webhook_module.HTTPException) as ctx:
                await webhook_module.webhook(FakeRequest(text_payload(body="help")), BackgroundTasks())

        self.assertEqual(ctx.exception.status_code, 403)

    async def test_webhook_rejects_unsigned_request_when_production_secret_is_missing(self):
        with patch.object(webhook_module, "WHATSAPP_APP_SECRET", None), patch.object(
            webhook_module, "ENV", "production"
        ):
            self.assertFalse(webhook_module.verify_webhook_signature(b"{}", None))

    async def test_webhook_accepts_valid_signature_when_secret_configured(self):
        payload = text_payload(body="help")
        request = FakeRequest(payload)
        raw_body = await request.body()
        digest = hmac.new(b"secret", raw_body, hashlib.sha256).hexdigest()
        request.headers["x-hub-signature-256"] = f"sha256={digest}"

        with patch.object(webhook_module, "WHATSAPP_APP_SECRET", "secret"), patch.object(webhook_module, "ENV", "production"):
            result, mocks, _ = await self.call_webhook_with_request(request)

        self.assertEqual(result, {"status": "help"})
        mocks["send_main_menu_list"].assert_called_once_with("27999999999", False, member())

    async def call_webhook_with_request(self, request, member_data=None, submission_data=None, **patches):
        return await self._call_webhook_request(request, member_data, submission_data, **patches)

    async def _call_webhook_request(self, request, member_data=None, submission_data=None, **patches):
        background_tasks = BackgroundTasks()

        with ExitStack() as stack:
            patch_names = [
                "send_text",
                "send_distance_buttons",
                "send_confirm_buttons",
                "send_workout_confirm_buttons",
                "send_self_correction_confirm_buttons",
                "send_participation_buttons",
                "send_leaderboard_visibility_buttons",
                "send_profile_buttons",
                "send_both_submission_buttons",
                "send_main_menu_list",
                "send_leaderboard_menu_list",
                "send_admin_menu_list",
                "send_admin_leaderboard_menu_list",
                "send_admin_edit_field_buttons",
                "send_admin_confirm_correction_buttons",
                "send_admin_member_center_buttons",
                "save_member_name",
                "save_participation_type",
                "set_leaderboard_visibility",
                "set_profile_state",
                "clear_profile_state",
                "reopen_submission_for_edit",
                "reopen_workout_submission_for_edit",
                "set_submission_mode",
                "verify_tt_code",
                "release_pending_submissions",
                "get_resumable_submission",
                "get_active_submission",
                "ensure_tt_open",
                "mark_attendance",
                "save_distance",
                "save_time",
                "save_workout_for_confirmation",
                "confirm_workout_submission",
                "confirm_submission",
                "get_completed_submission_for_current_event",
                "get_self_correctable_tt_submission",
                "start_member_self_correction",
                "get_member_self_correction",
                "save_member_self_correction_distance",
                "save_member_self_correction_time",
                "save_member_self_correction_workout",
                "apply_member_self_correction",
                "cancel_member_self_correction",
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
                "opt_out_leaderboard",
                "opt_in_leaderboard",
                "enqueue_post_confirm_messages",
                "run_due_jobs",
                "get_queue_health",
                "get_failed_jobs",
                "retry_failed_jobs",
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
            mocks["get_resumable_submission"].return_value = None
            mocks["get_member_self_correction"].return_value = None
            mocks["get_completed_submission_for_current_event"].return_value = None
            mocks["ensure_tt_open"].return_value = (True, None)

            stack.enter_context(patch.object(webhook_module, "get_member", return_value=member_data or member()))
            stack.enter_context(patch.object(webhook_module, "create_member", side_effect=AssertionError))
            get_or_create_value = submission_data or submission()
            mocks["get_active_submission"].return_value = (
                get_or_create_value[0]
                if isinstance(get_or_create_value, list)
                else get_or_create_value
            )
            get_or_create_mock = stack.enter_context(
                patch.object(webhook_module, "get_or_create_submission")
            )
            if isinstance(get_or_create_value, list):
                get_or_create_mock.side_effect = get_or_create_value
            else:
                get_or_create_mock.return_value = get_or_create_value
            mocks["get_or_create_submission"] = get_or_create_mock

            for name, value in patches.items():
                if name in mocks:
                    if isinstance(value, Exception):
                        mocks[name].side_effect = value
                    else:
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
        mocks["send_main_menu_list"].assert_called_once_with("27999999999", False, member())
        mocks["send_text"].assert_not_called()

    async def test_help_menu_for_admin_includes_admin_commands(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(sender="27722135094", body="menu"),
            member_data=member(phone="27722135094"),
        )

        self.assertEqual(result, {"status": "help"})
        mocks["send_main_menu_list"].assert_called_once_with(
            "27722135094", True, member(phone="27722135094")
        )

    async def test_admin_menu_text_clears_active_admin_edit_state(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(sender="27722135094", body="menu"),
            member_data=member(id=7, phone="27722135094", profile_state="ADMIN_CONFIRM|101|4|26:59"),
        )

        self.assertEqual(result, {"status": "help"})
        mocks["clear_profile_state"].assert_called_once_with(7)
        mocks["send_main_menu_list"].assert_called_once_with(
            "27722135094", True,
            member(id=7, phone="27722135094", profile_state="ADMIN_CONFIRM|101|4|26:59"),
        )

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

    async def test_admin_text_tt_code_uses_admin_code_intent(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(sender="27722135094", body="TT CODE"),
            member_data=member(phone="27722135094"),
        )

        self.assertEqual(result, {"status": "admin_code"})
        mocks["send_admin_code"].assert_called_once_with("27722135094")
        mocks["get_or_create_submission"].assert_not_called()

    async def test_interactive_admin_tt_code_still_uses_admin_code_intent(self):
        result, mocks, _ = await self.call_webhook(
            button_payload(sender="27722135094", button_id="admin_tt_code", title="TT Code"),
            member_data=member(phone="27722135094"),
        )

        self.assertEqual(result, {"status": "admin_code"})
        mocks["send_admin_code"].assert_called_once_with("27722135094")

    async def test_member_tt_code_retains_submit_shortcut(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(body="TT CODE"),
            submission_data=submission(tt_code_verified=False),
        )

        self.assertEqual(result, {"status": "menu_submit_await_code"})
        mocks["send_admin_code"].assert_not_called()
        mocks["send_text"].assert_called_once_with(
            "27999999999", "🔑 Send tonight's TT code to check in. You can type MENU anytime."
        )

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

    async def test_admin_jobs_status_returns_queue_summary(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(sender="27722135094", body="jobs status"),
            member_data=member(phone="27722135094"),
            get_queue_health={
                "pending_jobs": 2,
                "running_jobs": 1,
                "failed_jobs": 0,
                "done_jobs": 8,
                "oldest_pending_seconds": 30,
            },
        )

        self.assertEqual(result, {"status": "jobs_status"})
        sent = mocks["send_text"].call_args.args[1]
        self.assertIn("Job Queue Status", sent)
        self.assertIn("Pending: 2", sent)
        self.assertIn("Failed: 0", sent)

    async def test_admin_jobs_run_processes_queue(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(sender="27722135094", body="jobs run"),
            member_data=member(phone="27722135094"),
            run_due_jobs=3,
            get_queue_health={
                "pending_jobs": 0,
                "running_jobs": 0,
                "failed_jobs": 0,
                "done_jobs": 11,
                "oldest_pending_seconds": 0,
            },
        )

        self.assertEqual(result, {"status": "jobs_run", "processed": 3})
        mocks["run_due_jobs"].assert_called_once_with()
        sent = mocks["send_text"].call_args.args[1]
        self.assertIn("processed 3 job", sent)

    async def test_admin_jobs_failed_lists_recent_failures(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(sender="27722135094", body="jobs failed"),
            member_data=member(phone="27722135094"),
            get_failed_jobs=[
                {
                    "id": 7,
                    "job_type": "whatsapp_send",
                    "attempts": 3,
                    "max_attempts": 3,
                    "last_error": "WhatsApp send returned false",
                }
            ],
        )

        self.assertEqual(result, {"status": "jobs_failed", "count": 1})
        sent = mocks["send_text"].call_args.args[1]
        self.assertIn("Failed Jobs", sent)
        self.assertIn("#7 whatsapp_send", sent)

    async def test_admin_jobs_retry_requeues_failed_jobs(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(sender="27722135094", body="jobs retry"),
            member_data=member(phone="27722135094"),
            retry_failed_jobs=2,
        )

        self.assertEqual(result, {"status": "jobs_retry", "retried": 2})
        mocks["retry_failed_jobs"].assert_called_once_with()
        sent = mocks["send_text"].call_args.args[1]
        self.assertIn("Retried 2 failed job", sent)

    async def test_admin_find_button_starts_member_search_state(self):
        result, mocks, _ = await self.call_webhook(
            button_payload(sender="27722135094", button_id="admin_find", title="Find member"),
            member_data=member(phone="27722135094"),
        )

        self.assertEqual(result, {"status": "member_lookup_prompt"})
        mocks["set_profile_state"].assert_called_once_with(42, "ADMIN_FIND")
        self.assertIn("member name or phone number", mocks["send_text"].call_args.args[1])

    async def test_admin_find_state_accepts_plain_member_query(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(sender="27722135094", body="Lindsay"),
            member_data=member(phone="27722135094", profile_state="ADMIN_FIND"),
            search_members_for_admin=[],
        )

        self.assertEqual(result, {"status": "admin_find_results", "count": 0})
        mocks["search_members_for_admin"].assert_called_once_with("Lindsay")

    async def test_admin_history_button_guides_captain_through_find_member(self):
        result, mocks, _ = await self.call_webhook(
            button_payload(sender="27722135094", button_id="admin_history", title="Member history"),
            member_data=member(phone="27722135094"),
        )

        self.assertEqual(result, {"status": "submission_history_prompt"})
        self.assertIn("Find member first", mocks["send_text"].call_args.args[1])

    async def test_admin_queue_status_button_uses_existing_queue_handler(self):
        result, mocks, _ = await self.call_webhook(
            button_payload(sender="27722135094", button_id="admin_jobs_status", title="Queue status"),
            member_data=member(phone="27722135094"),
            get_queue_health={
                "pending_jobs": 1,
                "running_jobs": 0,
                "failed_jobs": 0,
                "done_jobs": 4,
                "oldest_pending_seconds": 0,
            },
        )

        self.assertEqual(result, {"status": "jobs_status"})
        self.assertIn("Job Queue Status", mocks["send_text"].call_args.args[1])

    async def test_admin_failed_jobs_button_uses_existing_failed_jobs_handler(self):
        result, mocks, _ = await self.call_webhook(
            button_payload(sender="27722135094", button_id="admin_jobs_failed", title="Failed jobs"),
            member_data=member(phone="27722135094"),
            get_failed_jobs=[],
        )

        self.assertEqual(result, {"status": "jobs_failed", "count": 0})
        mocks["get_failed_jobs"].assert_called_once_with()

    async def test_admin_retry_failed_button_uses_existing_retry_handler(self):
        result, mocks, _ = await self.call_webhook(
            button_payload(sender="27722135094", button_id="admin_jobs_retry", title="Retry failed"),
            member_data=member(phone="27722135094"),
            retry_failed_jobs=2,
        )

        self.assertEqual(result, {"status": "jobs_retry", "retried": 2})
        mocks["retry_failed_jobs"].assert_called_once_with()

    async def test_admin_leaderboards_button_opens_leaderboard_submenu(self):
        result, mocks, _ = await self.call_webhook(
            button_payload(sender="27722135094", button_id="admin_leaderboards", title="Leaderboard views"),
            member_data=member(phone="27722135094"),
        )

        self.assertEqual(result, {"status": "admin_leaderboards"})
        mocks["send_admin_leaderboard_menu_list"].assert_called_once_with("27722135094")

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
        mocks["send_text"].assert_called_once_with(
            "27999999999",
            "✅ Welcome back, Lindsay! You’re checked in. Let’s capture your TT result.",
        )
        mocks["send_distance_buttons"].assert_called_once_with("27999999999")

    async def test_returning_walker_code_checks_in_and_prompts_for_workout(self):
        unverified = submission(tt_code_verified=False)
        verified = submission(tt_code_verified=True)

        result, mocks, _ = await self.call_webhook(
            text_payload(body="9793"),
            member_data=member(participation_type="WALKER"),
            submission_data=[unverified, verified],
            is_valid_tt_code=lambda _code: True,
            verify_tt_code=verified,
            release_pending_submissions=lambda _member_id: None,
            mark_attendance=lambda _member_id: None,
        )

        self.assertEqual(result, {"status": "code_ok_walk"})
        self.assertEqual(
            mocks["send_text"].call_args_list,
            [
                (
                    ("27999999999", "✅ Welcome back, Lindsay! You’re checked in. Let’s capture your TT result."),
                    {},
                ),
                (
                    ("27999999999", "🚶 Send a short note about your walk or workout, e.g. 45 min walk."),
                    {},
                ),
            ],
        )

    async def test_returning_both_member_code_checks_in_and_prompts_for_activity(self):
        unverified = submission(tt_code_verified=False)
        verified = submission(tt_code_verified=True)

        result, mocks, _ = await self.call_webhook(
            text_payload(body="9793"),
            member_data=member(participation_type="BOTH"),
            submission_data=[unverified, verified],
            is_valid_tt_code=lambda _code: True,
            verify_tt_code=verified,
            release_pending_submissions=lambda _member_id: None,
            mark_attendance=lambda _member_id: None,
        )

        self.assertEqual(result, {"status": "code_ok_both_choice"})
        mocks["send_both_submission_buttons"].assert_called_once_with("27999999999")

    async def test_valid_code_verifies_fresh_submission_after_clearing_abandoned_attempts(self):
        abandoned = submission(id=101, tt_code_verified=False)
        fresh = submission(id=102, tt_code_verified=False)
        verified = submission(id=102, tt_code_verified=True)

        result, mocks, _ = await self.call_webhook(
            text_payload(body="9793"),
            submission_data=fresh,
            get_active_submission=abandoned,
            is_valid_tt_code=lambda _code: True,
            verify_tt_code=verified,
            release_pending_submissions=lambda _member_id: None,
            mark_attendance=lambda _member_id: None,
        )

        self.assertEqual(result, {"status": "code_ok_distance"})
        mocks["release_pending_submissions"].assert_called_once_with(42)
        mocks["verify_tt_code"].assert_called_once_with(102, "9793")
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
        self.assertEqual(
            mocks["send_text"].call_args_list[0].args,
            (
                "27999999999",
                "✅ Welcome back, Lindsay! You’re checked in. Let’s capture your TT result.",
            ),
        )
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
            "🔑 Send tonight's TT code to check in. You can type MENU anytime.",
        )

    async def test_submit_after_completed_result_does_not_restart_check_in(self):
        completed = submission(
            status="COMPLETE",
            distance_text="4",
            time_text="27:41",
            seconds=1661,
        )
        result, mocks, _ = await self.call_webhook(
            text_payload(body="SUBMIT"),
            get_active_submission=None,
            get_completed_submission_for_current_event=completed,
        )

        self.assertEqual(result, {"status": "already_submitted"})
        mocks["get_or_create_submission"].assert_not_called()
        sent = mocks["send_text"].call_args.args[1]
        self.assertIn("already submitted", sent)
        self.assertIn("4km — 27:41", sent)

    async def test_valid_code_after_completed_result_does_not_restart_check_in(self):
        completed = submission(
            status="COMPLETE",
            distance_text="6",
            time_text="42:00",
            seconds=2520,
        )
        result, mocks, _ = await self.call_webhook(
            text_payload(body="9793"),
            get_active_submission=None,
            get_completed_submission_for_current_event=completed,
            is_valid_tt_code=lambda _code: True,
        )

        self.assertEqual(result, {"status": "already_submitted"})
        mocks["get_or_create_submission"].assert_not_called()

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
            mocks["send_text"].assert_called_once_with(
                "27999999999",
                "⏱ Send your time, e.g. 27:41. I’ll show a confirmation before saving.",
            )

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

    async def test_runner_edit_resets_reviewed_result_on_the_same_submission(self):
        reopened = submission(
            id=101,
            status="PENDING",
            distance_text=None,
            time_text="",
            seconds=0,
            confirmed=False,
            mode="RUN",
            event_date="2026-09-08",
        )
        result, mocks, _ = await self.call_webhook(
            button_payload(button_id="edit", title="Edit"),
            submission_data=submission(
                id=101,
                distance_text="6",
                time_text="42:00",
                seconds=2520,
                confirmed=False,
                mode="RUN",
                event_date="2026-09-08",
            ),
            reopen_submission_for_edit=reopened,
        )

        self.assertEqual(result, {"status": "edit"})
        mocks["reopen_submission_for_edit"].assert_called_once_with(101)
        mocks["get_or_create_submission"].assert_not_called()
        mocks["clear_profile_state"].assert_called_once_with(42)
        mocks["send_distance_buttons"].assert_called_once_with("27999999999")
        self.assertEqual(reopened["id"], 101)
        self.assertEqual(reopened["event_date"], "2026-09-08")
        self.assertEqual(reopened["distance_text"], None)
        self.assertEqual(reopened["time_text"], "")
        self.assertEqual(reopened["seconds"], 0)
        self.assertFalse(reopened["confirmed"])
        self.assertEqual(reopened["status"], "PENDING")
        self.assertEqual(reopened["mode"], "RUN")

    async def test_runner_edit_then_resume_returns_to_distance_selection(self):
        reset = submission(distance_text=None, time_text="", seconds=0, mode="RUN")
        result, mocks, _ = await self.call_webhook(
            text_payload(body="RESUME"),
            submission_data=reset,
            get_resumable_submission=reset,
        )

        self.assertEqual(result, {"status": "resume_awaiting_distance"})
        mocks["send_distance_buttons"].assert_called_once_with("27999999999")
        mocks["send_confirm_buttons"].assert_not_called()

    async def test_runner_edit_rejects_a_delayed_confirm_from_old_card(self):
        reset = submission(distance_text=None, time_text="", seconds=0, mode="RUN")
        result, mocks, _ = await self.call_webhook(
            button_payload(button_id="confirm", title="Confirm"),
            submission_data=reset,
        )

        self.assertEqual(result, {"status": "confirm_not_ready_awaiting_distance"})
        mocks["confirm_submission"].assert_not_called()
        mocks["send_distance_buttons"].assert_called_once_with("27999999999")

    async def test_runner_edit_accepts_a_reentered_result_and_confirm(self):
        reset = submission(distance_text=None, time_text="", seconds=0, mode="RUN")
        after_distance = submission(distance_text="8", time_text="", seconds=0, mode="RUN")
        after_time = submission(distance_text="8", time_text="55:00", seconds=3300, mode="RUN")
        completed = submission(
            status="COMPLETE", distance_text="8", time_text="55:00", seconds=3300
        )

        edit_result, edit_mocks, _ = await self.call_webhook(
            button_payload(button_id="edit", title="Edit"),
            submission_data=submission(distance_text="6", time_text="42:00", seconds=2520),
            reopen_submission_for_edit=reset,
        )
        distance_result, distance_mocks, _ = await self.call_webhook(
            button_payload(button_id="8km", title="8 km"),
            submission_data=reset,
            save_distance=after_distance,
        )
        time_result, time_mocks, _ = await self.call_webhook(
            text_payload(body="55:00"),
            submission_data=after_distance,
            save_time=after_time,
        )
        confirm_result, confirm_mocks, _ = await self.call_webhook(
            button_payload(button_id="confirm", title="Confirm"),
            submission_data=after_time,
            confirm_submission=completed,
        )

        self.assertEqual(edit_result, {"status": "edit"})
        edit_mocks["reopen_submission_for_edit"].assert_called_once_with(101)
        self.assertEqual(distance_result, {"status": "distance"})
        distance_mocks["save_distance"].assert_called_once_with(101, "8")
        self.assertEqual(time_result, {"status": "confirm"})
        time_mocks["save_time"].assert_called_once_with(101, "55:00", 3300)
        self.assertEqual(confirm_result, {"status": "done"})
        confirm_mocks["confirm_submission"].assert_called_once_with(101)

    async def test_wednesday_resumable_runner_can_edit_to_a_safe_distance_state(self):
        reviewed = submission(
            distance_text="6",
            time_text="42:00",
            seconds=2520,
            event_date="2026-09-08",
        )
        reset = submission(
            distance_text=None,
            time_text="",
            seconds=0,
            mode="RUN",
            event_date="2026-09-08",
        )
        result, mocks, _ = await self.call_webhook(
            button_payload(button_id="edit", title="Edit"),
            submission_data=reviewed,
            get_resumable_submission=reviewed,
            reopen_submission_for_edit=reset,
        )

        self.assertEqual(result, {"status": "edit"})
        mocks["ensure_tt_open"].assert_called_once_with(submission_event_date="2026-09-08")
        mocks["reopen_submission_for_edit"].assert_called_once_with(101)
        mocks["get_or_create_submission"].assert_not_called()
        mocks["send_distance_buttons"].assert_called_once_with("27999999999")

    async def test_fresh_walker_workout_is_saved_for_confirmation(self):
        saved = submission(distance_text=None, time_text="EASY 5KM WALK", seconds=0, mode="WORKOUT")

        result, mocks, _ = await self.call_webhook(
            text_payload(body="Easy 5km walk"),
            member_data=member(participation_type="WALKER"),
            submission_data=submission(distance_text=None, time_text=""),
            save_workout_for_confirmation=saved,
        )

        self.assertEqual(result, {"status": "walker_workout_confirm"})
        mocks["save_workout_for_confirmation"].assert_called_once_with(101, "EASY 5KM WALK")
        mocks["confirm_submission"].assert_not_called()
        mocks["confirm_workout_submission"].assert_not_called()
        mocks["send_workout_confirm_buttons"].assert_called_once_with(
            "27999999999", "EASY 5KM WALK"
        )

    async def test_walker_workout_confirm_completes_the_saved_submission(self):
        completed = submission(status="COMPLETE", distance_text=None, time_text="45 MIN BRISK WALK", seconds=0, mode="WORKOUT")
        result, mocks, _ = await self.call_webhook(
            button_payload(button_id="confirm", title="Confirm"),
            member_data=member(participation_type="WALKER"),
            submission_data=submission(distance_text=None, time_text="45 MIN BRISK WALK", mode="WORKOUT"),
            confirm_workout_submission=completed,
        )

        self.assertEqual(result, {"status": "workout_confirmed"})
        mocks["confirm_workout_submission"].assert_called_once_with(101)
        mocks["confirm_submission"].assert_not_called()
        mocks["send_text"].assert_called_once_with("27999999999", "🚶 Workout logged! Well done.")

    async def test_walker_workout_edit_clears_only_the_workout_note(self):
        reopened = submission(distance_text=None, time_text="", seconds=0, mode="WORKOUT")
        result, mocks, _ = await self.call_webhook(
            button_payload(button_id="edit", title="Edit"),
            member_data=member(participation_type="WALKER"),
            submission_data=submission(distance_text=None, time_text="45 MIN BRISK WALK", mode="WORKOUT"),
            reopen_workout_submission_for_edit=reopened,
        )

        self.assertEqual(result, {"status": "workout_edit"})
        mocks["reopen_workout_submission_for_edit"].assert_called_once_with(101)
        mocks["get_or_create_submission"].assert_not_called()
        mocks["send_text"].assert_called_once_with(
            "27999999999", "🚶 Send the corrected walk or workout note."
        )

    async def test_unconfirmed_walker_workout_resumes_at_confirmation(self):
        pending = submission(
            distance_text=None,
            time_text="45 MIN BRISK WALK",
            seconds=0,
            mode="WORKOUT",
        )
        result, mocks, _ = await self.call_webhook(
            text_payload(body="RESUME"),
            member_data=member(participation_type="WALKER"),
            submission_data=pending,
        )

        self.assertEqual(result, {"status": "resume_awaiting_workout_confirm"})
        mocks["send_workout_confirm_buttons"].assert_called_once_with(
            "27999999999", "45 MIN BRISK WALK"
        )

    async def test_legacy_saved_walker_workout_resumes_with_confirmation(self):
        legacy_pending = submission(
            distance_text=None,
            time_text="Easy 5km walk",
            seconds=0,
            mode="WORKOUT",
        )
        result, mocks, _ = await self.call_webhook(
            text_payload(body="RESUME"),
            member_data=member(participation_type="WALKER"),
            submission_data=legacy_pending,
        )

        self.assertEqual(result, {"status": "resume_awaiting_workout_confirm"})
        mocks["send_workout_confirm_buttons"].assert_called_once_with(
            "27999999999", "Easy 5km walk"
        )

    async def test_wednesday_recovery_of_unconfirmed_workout_keeps_review_screen(self):
        pending = submission(
            distance_text=None,
            time_text="45 MIN BRISK WALK",
            seconds=0,
            mode="WORKOUT",
            event_date="2026-09-08",
        )
        result, mocks, _ = await self.call_webhook(
            text_payload(body="RESUME"),
            member_data=member(participation_type="WALKER"),
            submission_data=pending,
            get_resumable_submission=pending,
            ensure_tt_open=(True, None),
        )

        self.assertEqual(result, {"status": "resume_awaiting_workout_confirm"})
        mocks["send_workout_confirm_buttons"].assert_called_once_with(
            "27999999999", "45 MIN BRISK WALK"
        )

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
            mocks["send_text"].assert_called_once_with(
                "27999999999",
                "🚶 Send a short note about your walk or workout, e.g. 45 min walk.",
            )

    async def test_both_workout_is_saved_for_confirmation(self):
        saved = submission(distance_text=None, time_text="EASY 5KM WALK", seconds=0, mode="WORKOUT")
        result, mocks, _ = await self.call_webhook(
            text_payload(body="Easy 5km walk"),
            member_data=member(participation_type="BOTH", profile_state="BOTH_WORKOUT"),
            submission_data=submission(distance_text=None, time_text="", mode="WORKOUT"),
            save_workout_for_confirmation=saved,
        )

        self.assertEqual(result, {"status": "both_workout_confirm"})
        mocks["save_workout_for_confirmation"].assert_called_once_with(101, "EASY 5KM WALK")
        mocks["clear_profile_state"].assert_called_once_with(42)
        mocks["send_workout_confirm_buttons"].assert_called_once_with(
            "27999999999", "EASY 5KM WALK"
        )

    async def test_both_workout_confirm_completes_the_saved_submission(self):
        completed = submission(status="COMPLETE", distance_text=None, time_text="EASY 5KM WALK", seconds=0, mode="WORKOUT")
        result, mocks, _ = await self.call_webhook(
            button_payload(button_id="confirm", title="Confirm"),
            member_data=member(participation_type="BOTH"),
            submission_data=submission(distance_text=None, time_text="EASY 5KM WALK", mode="WORKOUT"),
            confirm_workout_submission=completed,
        )

        self.assertEqual(result, {"status": "workout_confirmed"})
        mocks["confirm_workout_submission"].assert_called_once_with(101)

    async def test_both_workout_edit_reopens_the_same_submission(self):
        reopened = submission(distance_text=None, time_text="", seconds=0, mode="WORKOUT")
        result, mocks, _ = await self.call_webhook(
            button_payload(button_id="edit", title="Edit"),
            member_data=member(participation_type="BOTH"),
            submission_data=submission(distance_text=None, time_text="EASY 5KM WALK", mode="WORKOUT"),
            reopen_workout_submission_for_edit=reopened,
        )

        self.assertEqual(result, {"status": "workout_edit"})
        mocks["reopen_workout_submission_for_edit"].assert_called_once_with(101)
        mocks["get_or_create_submission"].assert_not_called()

    async def test_both_workout_edit_journey_uses_same_submission_and_mode(self):
        unverified = submission(tt_code_verified=False, event_date="2026-09-08")
        checked_in = submission(tt_code_verified=True, event_date="2026-09-08")
        workout_mode = submission(
            tt_code_verified=True, mode="WORKOUT", event_date="2026-09-08"
        )
        original_note = submission(
            tt_code_verified=True,
            mode="WORKOUT",
            distance_text=None,
            time_text="45 MIN WALK",
            seconds=0,
            event_date="2026-09-08",
        )
        reopened = submission(
            tt_code_verified=True,
            mode="WORKOUT",
            distance_text=None,
            time_text="",
            seconds=0,
            confirmed=False,
            event_date="2026-09-08",
        )
        corrected_note = submission(
            tt_code_verified=True,
            mode="WORKOUT",
            distance_text=None,
            time_text="50 MIN BRISK WALK",
            seconds=0,
            event_date="2026-09-08",
        )
        completed = submission(
            status="COMPLETE",
            tt_code_verified=True,
            mode="WORKOUT",
            distance_text=None,
            time_text="50 MIN BRISK WALK",
            seconds=0,
            confirmed=True,
            event_date="2026-09-08",
        )
        both_member = member(participation_type="BOTH")

        code_result, code_mocks, _ = await self.call_webhook(
            text_payload(body="9793"),
            member_data=both_member,
            submission_data=unverified,
            verify_tt_code=checked_in,
            is_valid_tt_code=lambda _value: True,
        )
        choice_result, choice_mocks, _ = await self.call_webhook(
            button_payload(button_id="submit_workout", title="Workout"),
            member_data=both_member,
            submission_data=checked_in,
        )
        original_result, original_mocks, _ = await self.call_webhook(
            text_payload(body="45 min walk"),
            member_data=member(participation_type="BOTH", profile_state="BOTH_WORKOUT"),
            submission_data=workout_mode,
            save_workout_for_confirmation=original_note,
        )
        edit_result, edit_mocks, _ = await self.call_webhook(
            button_payload(button_id="edit", title="Edit"),
            member_data=both_member,
            submission_data=original_note,
            reopen_workout_submission_for_edit=reopened,
        )
        corrected_result, corrected_mocks, _ = await self.call_webhook(
            text_payload(body="50 min brisk walk"),
            member_data=both_member,
            submission_data=reopened,
            save_workout_for_confirmation=corrected_note,
        )
        confirm_result, confirm_mocks, _ = await self.call_webhook(
            button_payload(button_id="confirm", title="Confirm"),
            member_data=both_member,
            submission_data=corrected_note,
            confirm_workout_submission=completed,
        )

        self.assertEqual(code_result, {"status": "code_ok_both_choice"})
        self.assertEqual(choice_result, {"status": "both_workout"})
        choice_mocks["set_submission_mode"].assert_called_once_with(101, "WORKOUT")
        self.assertEqual(original_result, {"status": "both_workout_confirm"})
        original_mocks["save_workout_for_confirmation"].assert_called_once_with(101, "45 MIN WALK")
        self.assertEqual(edit_result, {"status": "workout_edit"})
        edit_mocks["reopen_workout_submission_for_edit"].assert_called_once_with(101)
        self.assertEqual(corrected_result, {"status": "both_workout_confirm"})
        corrected_mocks["save_workout_for_confirmation"].assert_called_once_with(101, "50 MIN BRISK WALK")
        corrected_mocks["send_both_submission_buttons"].assert_not_called()
        self.assertEqual(confirm_result, {"status": "workout_confirmed"})
        confirm_mocks["confirm_workout_submission"].assert_called_once_with(101)

        for row in (checked_in, workout_mode, original_note, reopened, corrected_note, completed):
            self.assertEqual(row["id"], 101)
            self.assertEqual(row["event_date"], "2026-09-08")
            self.assertTrue(row["tt_code_verified"])
        self.assertEqual(reopened["mode"], "WORKOUT")
        self.assertEqual(completed["mode"], "WORKOUT")
        self.assertTrue(completed["confirmed"])
        edit_mocks["get_or_create_submission"].assert_not_called()

    async def test_both_workout_edit_then_resume_prompts_for_corrected_note(self):
        reopened = submission(
            mode="WORKOUT", distance_text=None, time_text="", seconds=0
        )
        result, mocks, _ = await self.call_webhook(
            text_payload(body="RESUME"),
            member_data=member(participation_type="BOTH"),
            submission_data=reopened,
            get_resumable_submission=reopened,
        )

        self.assertEqual(result, {"status": "resume_awaiting_workout"})
        mocks["send_text"].assert_called_once_with(
            "27999999999", "🚶 Send a short note about your walk or workout, e.g. 45 min walk."
        )
        mocks["send_both_submission_buttons"].assert_not_called()

    async def test_both_workout_edit_on_wednesday_keeps_workout_mode(self):
        reviewed = submission(
            mode="WORKOUT",
            distance_text=None,
            time_text="45 MIN WALK",
            seconds=0,
            event_date="2026-09-08",
        )
        reopened = submission(
            mode="WORKOUT",
            distance_text=None,
            time_text="",
            seconds=0,
            event_date="2026-09-08",
        )
        result, mocks, _ = await self.call_webhook(
            button_payload(button_id="edit", title="Edit"),
            member_data=member(participation_type="BOTH"),
            submission_data=reviewed,
            get_resumable_submission=reviewed,
            reopen_workout_submission_for_edit=reopened,
        )

        self.assertEqual(result, {"status": "workout_edit"})
        mocks["ensure_tt_open"].assert_called_once_with(submission_event_date="2026-09-08")
        mocks["reopen_workout_submission_for_edit"].assert_called_once_with(101)
        mocks["send_text"].assert_called_once_with(
            "27999999999", "🚶 Send the corrected walk or workout note."
        )

    async def test_legacy_mode_less_both_workout_resumes_at_review(self):
        legacy = submission(
            mode=None,
            distance_text=None,
            time_text="45 MIN WALK",
            seconds=0,
        )
        result, mocks, _ = await self.call_webhook(
            text_payload(body="RESUME"),
            member_data=member(participation_type="BOTH"),
            submission_data=legacy,
        )

        self.assertEqual(result, {"status": "resume_awaiting_workout_confirm"})
        mocks["send_workout_confirm_buttons"].assert_called_once_with(
            "27999999999", "45 MIN WALK"
        )

    async def test_both_workout_duplicate_confirm_is_harmless(self):
        completed = submission(
            status="COMPLETE",
            mode="WORKOUT",
            distance_text=None,
            time_text="50 MIN BRISK WALK",
            seconds=0,
            confirmed=True,
        )
        result, mocks, _ = await self.call_webhook(
            button_payload(button_id="confirm", title="Confirm"),
            member_data=member(participation_type="BOTH"),
            submission_data=None,
            get_active_submission=None,
            get_completed_submission_for_current_event=completed,
        )

        self.assertEqual(result, {"status": "already_confirmed"})
        mocks["confirm_workout_submission"].assert_not_called()
        mocks["get_or_create_submission"].assert_not_called()

    async def test_duplicate_workout_confirm_is_harmless(self):
        completed = submission(
            status="COMPLETE",
            distance_text=None,
            time_text="45 MIN BRISK WALK",
            seconds=0,
            mode="WORKOUT",
        )
        result, mocks, _ = await self.call_webhook(
            button_payload(button_id="confirm", title="Confirm"),
            member_data=member(participation_type="WALKER"),
            submission_data=None,
            get_active_submission=None,
            get_completed_submission_for_current_event=completed,
        )

        self.assertEqual(result, {"status": "already_confirmed"})
        mocks["confirm_workout_submission"].assert_not_called()
        mocks["get_or_create_submission"].assert_not_called()
        mocks["send_text"].assert_called_once_with("27999999999", "✅ Already confirmed.")

    async def test_profile_name_edit_clears_state(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(body="Lindsay Bull"),
            member_data=member(profile_state="EDIT_NAME"),
        )

        self.assertEqual(result, {"status": "profile_name_updated"})
        mocks["save_member_name"].assert_called_once_with(42, "Lindsay", "Bull")
        mocks["clear_profile_state"].assert_called_once_with(42)
        mocks["send_text"].assert_called_once_with("27999999999", "✅ Name updated.")

    async def test_complete_submission_edit_starts_non_destructive_correction(self):
        correction = self_correction()
        result, mocks, _ = await self.call_webhook(
            button_payload(button_id="edit", title="Edit"),
            submission_data=submission(
                status="COMPLETE",
                distance_text="8",
                time_text="43:21",
                seconds=2601,
            ),
            start_member_self_correction=correction,
        )

        self.assertEqual(result, {"status": "edit_existing"})
        mocks["start_member_self_correction"].assert_called_once_with(42, 101, "RUN")
        mocks["reopen_submission_for_edit"].assert_not_called()
        mocks["send_distance_buttons"].assert_called_once_with("27999999999")

    async def test_fix_result_abandon_leaves_complete_runner_unchanged(self):
        completed = submission(status="COMPLETE", distance_text="8", time_text="43:21", seconds=2601)
        result, mocks, _ = await self.call_webhook(
            text_payload(body="FIX RESULT"),
            get_self_correctable_tt_submission=completed,
            start_member_self_correction=self_correction(),
        )

        self.assertEqual(result, {"status": "fix_result"})
        mocks["reopen_submission_for_edit"].assert_not_called()
        mocks["apply_member_self_correction"].assert_not_called()
        mocks["get_or_create_submission"].assert_not_called()
        mocks["send_distance_buttons"].assert_called_once_with("27999999999")

    async def test_tuesday_completed_result_can_be_fixed(self):
        completed = submission(
            status="COMPLETE", distance_text="4", time_text="27:41", event_date="2026-09-08"
        )
        result, mocks, _ = await self.call_webhook(
            text_payload(body="FIX RESULT"),
            get_self_correctable_tt_submission=completed,
            ensure_tt_open=(True, None),
            start_member_self_correction=self_correction(),
        )

        self.assertEqual(result, {"status": "fix_result"})
        mocks["ensure_tt_open"].assert_called_once_with(submission_event_date="2026-09-08")
        mocks["start_member_self_correction"].assert_called_once_with(42, 101, "RUN")
        mocks["reopen_submission_for_edit"].assert_not_called()
        mocks["get_or_create_submission"].assert_not_called()

    async def test_wednesday_0800_tuesday_result_can_be_fixed(self):
        completed = submission(
            status="COMPLETE", distance_text="6", time_text="42:00", event_date="2026-09-08"
        )
        result, mocks, _ = await self.call_webhook(
            text_payload(body="FIX RESULT"),
            get_self_correctable_tt_submission=completed,
            ensure_tt_open=(True, None),
            start_member_self_correction=self_correction(),
        )

        self.assertEqual(result, {"status": "fix_result"})
        mocks["start_member_self_correction"].assert_called_once_with(42, 101, "RUN")
        mocks["get_or_create_submission"].assert_not_called()

    async def test_wednesday_1259_tuesday_result_can_be_fixed(self):
        completed = submission(
            status="COMPLETE", distance_text="8", time_text="55:00", event_date="2026-09-08"
        )
        result, mocks, _ = await self.call_webhook(
            text_payload(body="FIX RESULT"),
            get_self_correctable_tt_submission=completed,
            ensure_tt_open=(True, None),
            start_member_self_correction=self_correction(),
        )

        self.assertEqual(result, {"status": "fix_result"})
        mocks["start_member_self_correction"].assert_called_once_with(42, 101, "RUN")

    async def test_wednesday_after_deadline_closes_self_fix(self):
        completed = submission(
            status="COMPLETE", distance_text="4", time_text="27:41", event_date="2026-09-08"
        )
        result, mocks, _ = await self.call_webhook(
            text_payload(body="FIX RESULT"),
            get_self_correctable_tt_submission=completed,
            ensure_tt_open=(False, "⛔ The deadline for the 8 September TT was *13:00* today."),
        )

        self.assertEqual(result, {"status": "closed"})
        mocks["reopen_submission_for_edit"].assert_not_called()
        mocks["get_or_create_submission"].assert_not_called()

    async def test_active_self_correction_expires_without_changing_original_result(self):
        correction = self_correction(distance_text="8", time_text="42:58", seconds=2578)
        result, mocks, _ = await self.call_webhook(
            text_payload(body="RESUME"),
            get_member_self_correction=correction,
            ensure_tt_open=(False, "⛔ The correction deadline has passed."),
        )

        self.assertEqual(result, {"status": "self_correction_expired"})
        mocks["cancel_member_self_correction"].assert_called_once_with(501, 42)
        mocks["apply_member_self_correction"].assert_not_called()
        mocks["reopen_submission_for_edit"].assert_not_called()

    async def test_self_correction_runner_updates_same_submission_only_after_confirm(self):
        started = self_correction()
        with_distance = self_correction(distance_text="8")
        reviewed = self_correction(distance_text="8", time_text="42:58", seconds=2578)

        result, mocks, _ = await self.call_webhook(
            button_payload(button_id="8km", title="8km"),
            get_member_self_correction=started,
            save_member_self_correction_distance=with_distance,
        )
        self.assertEqual(result, {"status": "self_correction_awaiting_time"})
        mocks["apply_member_self_correction"].assert_not_called()

        result, mocks, _ = await self.call_webhook(
            text_payload(body="42:58"),
            get_member_self_correction=with_distance,
            save_member_self_correction_time=reviewed,
        )
        self.assertEqual(result, {"status": "self_correction_awaiting_confirm"})
        body = mocks["send_self_correction_confirm_buttons"].call_args.args[1]
        self.assertIn("Was: 8km — 43:21", body)
        self.assertIn("New: 8km — 42:58", body)
        mocks["apply_member_self_correction"].assert_not_called()

        result, mocks, _ = await self.call_webhook(
            button_payload(button_id="self_correction_confirm", title="Confirm"),
            get_member_self_correction=reviewed,
            apply_member_self_correction=submission(
                status="COMPLETE", distance_text="8", time_text="42:58", seconds=2578
            ),
        )
        self.assertEqual(result, {"status": "self_correction_confirmed", "submission_id": 101})
        mocks["apply_member_self_correction"].assert_called_once_with(501, 42)
        mocks["get_or_create_submission"].assert_not_called()

    async def test_self_correction_cancel_keeps_original_result(self):
        result, mocks, _ = await self.call_webhook(
            button_payload(button_id="self_correction_cancel", title="Cancel"),
            get_member_self_correction=self_correction(distance_text="8", time_text="42:58", seconds=2578),
        )

        self.assertEqual(result, {"status": "self_correction_cancelled"})
        mocks["cancel_member_self_correction"].assert_called_once_with(501, 42)
        mocks["apply_member_self_correction"].assert_not_called()
        self.assertIn("original TT result is unchanged", mocks["send_text"].call_args.args[1])

    async def test_duplicate_or_delayed_confirm_cannot_apply_stale_correction(self):
        reviewed = self_correction(distance_text="8", time_text="42:58", seconds=2578)
        result, mocks, _ = await self.call_webhook(
            button_payload(button_id="confirm", title="Confirm"),
            get_member_self_correction=reviewed,
        )
        self.assertEqual(result, {"status": "self_correction_awaiting_confirm"})
        mocks["apply_member_self_correction"].assert_not_called()

        result, mocks, _ = await self.call_webhook(
            button_payload(button_id="self_correction_confirm", title="Confirm"),
            get_member_self_correction=reviewed,
            apply_member_self_correction=None,
        )
        self.assertEqual(result, {"status": "self_correction_already_handled"})
        mocks["apply_member_self_correction"].assert_called_once_with(501, 42)

    async def test_workout_self_correction_is_non_destructive_and_reviewed(self):
        started = self_correction(
            mode="WORKOUT",
            original_distance_text=None,
            original_time_text="45 min walk",
            original_seconds=0,
        )
        reviewed = self_correction(
            mode="WORKOUT",
            time_text="50 min brisk walk",
            seconds=0,
            original_distance_text=None,
            original_time_text="45 min walk",
        )
        result, mocks, _ = await self.call_webhook(
            text_payload(body="50 min brisk walk"),
            get_member_self_correction=started,
            save_member_self_correction_workout=reviewed,
        )

        self.assertEqual(result, {"status": "self_correction_awaiting_confirm"})
        body = mocks["send_self_correction_confirm_buttons"].call_args.args[1]
        self.assertIn("Was: 45 min walk", body)
        self.assertIn("New: 50 min brisk walk", body)
        mocks["reopen_workout_submission_for_edit"].assert_not_called()

    async def test_previous_tuesday_cannot_be_fixed(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(body="FIX RESULT"),
            get_self_correctable_tt_submission=None,
        )

        self.assertEqual(result, {"status": "no_result_to_fix"})
        mocks["ensure_tt_open"].assert_not_called()
        mocks["reopen_submission_for_edit"].assert_not_called()
        mocks["get_or_create_submission"].assert_not_called()

    async def test_fix_result_without_a_completed_tt_gives_helpful_message(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(body="FIX RESULT"),
            get_self_correctable_tt_submission=None,
        )

        self.assertEqual(result, {"status": "no_result_to_fix"})
        self.assertIn("completed result from the current TT", mocks["send_text"].call_args.args[1])

    async def test_resume_command_continues_pending_submission(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(body="resume"),
            submission_data=submission(distance_text="4", time_text=""),
        )

        self.assertEqual(result, {"status": "resume_awaiting_time"})
        mocks["send_text"].assert_called_once_with(
            "27999999999",
            "⏱ Send your time, for example 27:41 or 01:27:41. I’ll show a confirmation before saving.",
        )

    async def test_runner_submission_survives_profile_change_to_walker(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(body="RESUME"),
            member_data=member(participation_type="WALKER"),
            submission_data=submission(mode="RUN", distance_text="8", time_text=""),
        )

        self.assertEqual(result, {"status": "resume_awaiting_time"})
        mocks["send_text"].assert_called_once_with(
            "27999999999",
            "⏱ Send your time, for example 27:41 or 01:27:41. I’ll show a confirmation before saving.",
        )

    async def test_workout_submission_survives_profile_change_to_runner(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(body="RESUME"),
            member_data=member(participation_type="RUNNER"),
            submission_data=submission(mode="WORKOUT", distance_text=None, time_text="Easy 5km walk"),
        )

        self.assertEqual(result, {"status": "resume_awaiting_workout_confirm"})
        mocks["send_workout_confirm_buttons"].assert_called_once_with(
            "27999999999", "Easy 5km walk"
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
        mocks["send_main_menu_list"].assert_called_once_with("27999999999", False, member())

    async def test_help_menu_passes_opted_out_member_preference_to_menu(self):
        hidden_member = member(leaderboard_opt_out=True)
        result, mocks, _ = await self.call_webhook(
            text_payload(body="HELP"),
            member_data=hidden_member,
        )

        self.assertEqual(result, {"status": "help"})
        mocks["send_main_menu_list"].assert_called_once_with(
            "27999999999", False, hidden_member
        )

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

    async def test_stale_runner_confirm_reprompts_without_completing_an_incomplete_result(self):
        result, mocks, _ = await self.call_webhook(
            button_payload(button_id="confirm", title="Confirm"),
            submission_data=submission(distance_text=None, time_text="", seconds=0),
        )

        self.assertEqual(result, {"status": "confirm_not_ready_awaiting_distance"})
        mocks["confirm_submission"].assert_not_called()
        mocks["enqueue_post_confirm_messages"].assert_not_called()
        mocks["send_distance_buttons"].assert_called_once_with("27999999999")

    async def test_followup_queue_failure_does_not_affect_saved_result(self):
        completed = submission(status="COMPLETE", distance_text="4", time_text="27:41", seconds=1661)
        result, mocks, _ = await self.call_webhook(
            button_payload(button_id="confirm", title="Confirm"),
            submission_data=submission(distance_text="4", time_text="27:41", seconds=1661),
            confirm_submission=completed,
            enqueue_post_confirm_messages=RuntimeError("coaching unavailable"),
        )

        self.assertEqual(result, {"status": "done"})
        mocks["confirm_submission"].assert_called_once_with(101)
        mocks["send_text"].assert_called_once_with("27999999999", "TT recorded.")

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
            coach_reply = stack.enter_context(
                patch.object(webhook_module, "coach_reply", return_value="Keep building steadily.")
            )
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
                42,
                "Lindsay",
                submission(status="COMPLETE", distance_text="4", time_text="27:41", seconds=1661),
                previous_best=1800,
            )

        self.assertEqual(len(messages), 1)
        self.assertIn("🏁 *Lindsay, your TT result is saved*", messages[0])
        self.assertIn("Distance: 4 km", messages[0])
        self.assertIn("Time: 27:41", messages[0])
        self.assertIn("Pace: 6:55/km", messages[0])
        self.assertIn("- PB by 2:19", messages[0])
        self.assertIn("Season TTs: 5", messages[0])
        self.assertIn("Tonight's 4 km position: #2", messages[0])
        self.assertIn("🎉 Milestone: 5 TTs logged", messages[0])
        self.assertIn("🥇 Badge: 4km PB", messages[0])
        self.assertIn("*Coach note*", messages[0])
        self.assertIn("Keep building steadily.", messages[0])
        prompt = coach_reply.call_args.args[0]
        self.assertIn("4km", prompt)
        self.assertIn("27:41", prompt)
        self.assertIn("pace", prompt)
        self.assertIn("Trend:", prompt)
        self.assertNotIn("Lindsay", prompt)
        self.assertNotIn("27999999999", prompt)
        self.assertNotIn("42", prompt)
        self.assertIsInstance(prompt, str)


if __name__ == "__main__":
    unittest.main()
