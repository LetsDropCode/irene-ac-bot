import json
import os
import unittest
from contextlib import ExitStack
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from app.flows import admin_submission_flow as flow
from app.flows.webhook_dispatch import route_message
from app import webhook, whatsapp


class AdminSubmissionFlowTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.admin = {"id": 7, "profile_state": None}
        self.sent = self.stack.enter_context(patch.object(flow, "send_text"))
        self.buttons = self.stack.enter_context(patch.object(flow, "send_admin_submission_buttons"))
        self.calendar = self.stack.enter_context(patch.object(flow, "send_admin_date_calendar", return_value=False))
        self.save = self.stack.enter_context(patch.object(flow, "save_admin_submission", return_value={"status": "saved", "submission": {"id": 123}}))
        self.stack.enter_context(patch.object(flow, "set_profile_state", side_effect=self.set_state))
        self.stack.enter_context(patch.object(flow, "clear_profile_state", side_effect=lambda _id: self.set_state(_id, None)))
        self.stack.enter_context(patch.object(flow, "search_members_for_admin", return_value=[
            {"id": 42, "first_name": "Test", "last_name": "Member", "phone": "27000000001"}
        ]))
        self.stack.enter_context(patch.object(flow, "get_member_for_admin_submission", return_value={
            "id": 42, "first_name": "Test", "last_name": "Member", "popia_acknowledged": True,
        }))

    def set_state(self, _id, state):
        self.admin["profile_state"] = state

    def send(self, text=None, button=None, authorized=True):
        return flow.handle_admin_submission("27000000000", self.admin, text,
                                            {"id": button} if button else None, authorized)

    def review(self, workout=False):
        self.assertEqual(self.send("ADMIN SUBMIT")["status"], "admin_add_search")
        self.send("Test")
        self.send("1")
        self.send("06/10/2026")
        self.send(button="admin_add_workout" if workout else "admin_add_run")
        if not workout:
            self.send("6km")
        note = "Pyramid walk | 5.54km, 41:35" if workout else "42:00"
        self.assertEqual(self.send(note)["status"], "admin_add_review")
        self.save.assert_not_called()
        return json.loads(self.admin["profile_state"][len(flow.PREFIX):])

    def test_runner_and_workout_require_exact_review_button(self):
        for workout in (False, True):
            with self.subTest(workout=workout):
                self.save.reset_mock()
                draft = self.review(workout)
                self.assertIn("2026-10-06", self.buttons.call_args.args[1])
                self.assertEqual(self.send(button="admin_add_confirm:old")["status"], "admin_add_stale_button")
                self.save.assert_not_called()
                result = self.send(button=f"admin_add_confirm:{draft['token']}")
                self.assertEqual(result["status"], "admin_add_saved")
                self.save.assert_called_once_with("27000000000", 42, "2026-10-06", draft["mode"], draft["note"], draft.get("distance"))
                self.assertIsNone(self.admin["profile_state"])
                self.assertEqual(self.send(button=f"admin_add_confirm:{draft['token']}")["status"], "admin_add_expired")
                self.assertEqual(self.save.call_count, 1)

    def test_cancel_does_not_save(self):
        draft = self.review()
        self.assertEqual(self.send(button=f"admin_add_cancel:{draft['token']}")["status"], "admin_add_cancelled")
        self.save.assert_not_called()

    def test_calendar_opens_for_selected_member_and_accepts_only_current_draft(self):
        self.calendar.return_value = True
        self.admin["profile_state"] = "ADMIN_MEMBER|42"
        self.send(button="admin_add_tt")
        draft = json.loads(self.admin["profile_state"][len(flow.PREFIX):])
        self.calendar.assert_called_once_with("27000000000", "Test Member", draft["token"])
        for token, expected in (("old-token", "admin_add_stale_calendar"), (draft["token"], "admin_add_mode")):
            result = flow.handle_admin_submission("27000000000", self.admin, None, {
                "id": "admin_add_calendar", "flow_token": token, "event_date": "2026-10-06",
            }, True)
            self.assertEqual(result["status"], expected)
        current = json.loads(self.admin["profile_state"][len(flow.PREFIX):])
        self.assertEqual(current["date"], "2026-10-06")
        repeat = flow.handle_admin_submission("27000000000", self.admin, None, {
            "id": "admin_add_calendar", "flow_token": draft["token"], "event_date": "2026-10-13",
        }, True)
        self.assertEqual(repeat["status"], "admin_add_stale_calendar")
        self.save.assert_not_called()

    def test_calendar_rejects_future_missing_and_invalid_dates(self):
        self.admin["profile_state"] = "ADMIN_MEMBER|42"
        self.send(button="admin_add_tt")
        draft = json.loads(self.admin["profile_state"][len(flow.PREFIX):])
        for value in ("2999-01-01", "2026-02-30", None, {}, "CANCEL"):
            result = flow.handle_admin_submission("27000000000", self.admin, None, {
                "id": "admin_add_calendar", "flow_token": draft["token"], "event_date": value,
            }, True)
            self.assertEqual(result["status"], "admin_add_bad_date")
        self.save.assert_not_called()

    def test_flow_webhook_response_is_parsed_and_non_admin_cannot_use_it(self):
        for response in (json.dumps({"flow_token": "draft-token", "event_date": "2026-10-06"}), "not json", "[]"):
            payload = {"entry": [{"changes": [{"value": {"messages": [{
                "id": "test-flow-reply", "from": "27000000001", "type": "interactive",
                "interactive": {"type": "nfm_reply", "nfm_reply": {"response_json": response}},
            }]}}]}]}
            _, sender, text, button = webhook.extract_whatsapp_message(payload)
            self.assertEqual(button["id"], "admin_add_calendar")
            with patch.object(webhook, "ADMIN_NUMBERS", frozenset()):
                self.assertEqual(route_message(webhook, sender, text, button)["status"], "admin_add_forbidden")
        self.save.assert_not_called()

    def test_existing_result_is_never_reported_as_saved(self):
        draft = self.review()
        self.save.return_value = {"status": "exists"}
        self.assertEqual(self.send(button=f"admin_add_confirm:{draft['token']}")["status"], "admin_add_exists")
        self.assertIn("Correct result", self.sent.call_args.args[1])

    def test_selected_member_shortcut_and_invalid_dates(self):
        self.admin["profile_state"] = "ADMIN_MEMBER|42"
        self.assertEqual(self.send(button="admin_add_tt")["status"], "admin_add_date")
        for value in ("tomorrow", "2026-02-30", "2999-01-01"):
            self.assertEqual(self.send(value)["status"], "admin_add_bad_date")
        self.save.assert_not_called()

    def test_bad_distance_time_and_blank_workout_stay_in_entry(self):
        self.admin["profile_state"] = "ADMIN_MEMBER|42"
        self.send(button="admin_add_tt")
        self.send("2026-10-06")
        self.send("RUN")
        self.assertEqual(self.send("5")["status"], "admin_add_bad_distance")
        self.send("4")
        for value in ("00:00", "25:80", "hello"):
            self.assertEqual(self.send(value)["status"], "admin_add_bad_result")
        self.send("CANCEL")
        self.review(workout=True)
        draft = json.loads(self.admin["profile_state"][len(flow.PREFIX):])
        draft["step"] = "workout"
        self.set_state(7, flow.PREFIX + json.dumps(draft))
        for value in ("", "x" * 501):
            self.assertEqual(self.send(value)["status"], "admin_add_bad_result")
        self.save.assert_not_called()

    def test_non_admin_cannot_use_command_button_or_forged_confirmation(self):
        with patch.object(webhook, "ADMIN_NUMBERS", frozenset()), patch.object(webhook, "send_text"), patch.object(webhook, "get_member"):
            for text, button in (("ADMIN SUBMIT", None), (None, {"id": "admin_add_tt"}), (None, {"id": "admin_add_confirm:forged"})):
                self.assertEqual(route_message(webhook, "27000000001", text, button)["status"], "admin_add_forbidden")
        self.save.assert_not_called()

    def test_menu_exits_draft_and_admin_dispatch_routes_entry(self):
        self.admin["profile_state"] = "ADMIN_MEMBER|42"
        with patch.object(webhook, "ADMIN_NUMBERS", frozenset({"27000000000"})), patch.object(webhook, "get_member", return_value=self.admin):
            self.assertEqual(route_message(webhook, "27000000000", None, {"id": "admin_add_tt"})["status"], "admin_add_date")
            with patch.object(webhook, "clear_admin_edit_state_if_needed") as clear, patch.object(webhook, "send_help_menu"):
                self.assertEqual(route_message(webhook, "27000000000", "MENU", None)["status"], "help")
                clear.assert_called_once_with(self.admin)

    def test_confirmation_buttons_fit_whatsapp_limits(self):
        draft = self.review(workout=True)
        args = self.buttons.call_args.args
        with patch.object(whatsapp, "_send", return_value=True) as send:
            whatsapp.send_admin_submission_buttons(*args)
        card = send.call_args.args[0]["interactive"]
        self.assertLessEqual(len(card["body"]["text"]), 1024)
        self.assertEqual(card["action"]["buttons"][0]["reply"]["id"], f"admin_add_confirm:{draft['token']}")
