import os
import unittest
from datetime import date, datetime, timezone
from unittest.mock import Mock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from app import webhook, whatsapp
from app.flows.help_flow import resolve_menu_action, resolve_interactive_action
from app.flows.member_dispatch import handle_member_message
from app.flows.season_flow import handle_season_message
from app.services import season_service as seasons


class SeasonTests(unittest.TestCase):
    def test_rollover_is_at_south_african_midnight_every_year(self):
        for year in (2026, 2027, 2031):
            self.assertEqual(seasons.current_season(datetime(year, 12, 31, 21, 59, 59, tzinfo=timezone.utc)), year)
            self.assertEqual(seasons.current_season(datetime(year, 12, 31, 22, tzinfo=timezone.utc)), year + 1)
        self.assertEqual(seasons.season_bounds(2028), (date(2028, 1, 1), date(2029, 1, 1)))

    def test_history_aliases_keep_admin_member_lookup_unambiguous(self):
        self.assertEqual(resolve_menu_action("HISTORY 2026"), "MEMBER_HISTORY")
        self.assertEqual(resolve_menu_action("MY HISTORY 2026", admin=True), "MEMBER_HISTORY")
        self.assertEqual(resolve_menu_action("HISTORY", admin=True), "ADMIN_HISTORY")
        self.assertIsNone(resolve_menu_action("HISTORY 2026", admin=True))
        self.assertEqual(resolve_interactive_action("menu_season"), "SEASON")
        self.assertEqual(resolve_interactive_action("menu_progress"), "PROGRESS")
        self.assertEqual(resolve_menu_action("SEASON PBS"), "SEASON_LEADERBOARD")

    def test_history_validates_year_and_page_before_querying(self):
        actions = Mock()
        member = {"id": 42}
        with patch("app.flows.season_flow.current_season", return_value=2027):
            for command in ("MY HISTORY 2028", "MY HISTORY 0000", "MY HISTORY 2026 PAGE 0",
                            "MY HISTORY 2026 PAGE 99999", "MY HISTORY bad", "MY HISTORY 2026 PAGE 1;DELETE"):
                result = handle_season_message(actions, "2771", member, command, "MEMBER_HISTORY")
                self.assertEqual(result["status"], "invalid_season_command")
            actions.send_member_history.assert_not_called()
            handle_season_message(actions, "2771", member, "MY HISTORY 2026 PAGE 2", "MEMBER_HISTORY")
            actions.send_member_history.assert_called_once_with("2771", member, 2026, 2)

    def test_numeric_season_and_button_use_current_season(self):
        for text in ("3", None):
            actions = Mock()
            handle_season_message(actions, "2771", {"id": 42}, text, "SEASON")
            actions.send_member_season.assert_called_once_with("2771", {"id": 42}, None)

    def test_season_welcome_repeats_only_when_year_changes(self):
        member = {"id": 42, "first_name": "Test", "participation_type": "RUNNER",
                  "popia_acknowledged": True, "last_seen_season": 2026}
        with patch.object(webhook, "current_season", return_value=2027), patch.object(
            webhook, "send_text", return_value=True
        ) as send, patch.object(webhook, "mark_season_seen") as mark:
            self.assertTrue(webhook.send_season_welcome_once("2771", member))
            self.assertFalse(webhook.send_season_welcome_once("2771", member))
            self.assertIn("2027", send.call_args.args[1])
            mark.assert_called_once_with(42, 2027)

    def test_welcome_does_not_mark_failed_send_or_contact_incomplete_or_withdrawn_member(self):
        member = {"id": 42, "first_name": "Test", "participation_type": "RUNNER",
                  "popia_acknowledged": True}
        with patch.object(webhook, "send_text", return_value=False) as send, patch.object(webhook, "mark_season_seen") as mark:
            self.assertFalse(webhook.send_season_welcome_once("2771", member))
            mark.assert_not_called()
            send.reset_mock()
            for changes in ({"popia_acknowledged": False}, {"profile_state": "ONBOARDING_LEADERBOARD"},
                            {"leaderboard_visibility_set": False}):
                self.assertFalse(webhook.send_season_welcome_once("2771", dict(member, **changes)))
            send.assert_not_called()

    def test_private_history_is_scoped_to_requesting_member_and_shows_pagination(self):
        with patch.object(webhook, "get_member_history", return_value=([
            {"id": 1, "event_date": date(2026, 12, 29), "distance_text": "4", "time_text": "25:00"}
        ], True)) as history, patch.object(webhook, "send_text") as send:
            webhook.send_member_history("2771", {"id": 42, "leaderboard_opt_out": True}, 2026)
        history.assert_called_once_with(42, 2026, 1)
        self.assertIn("MY HISTORY 2026 PAGE 2", send.call_args.args[1])

    def test_empty_season_and_long_workout_pages_are_readable(self):
        message = seasons.format_season_summary({"year": 2027, "attendance": 0, "total": 0, "walks": 0, "pbs": []})
        self.assertIn("first completed TT", message)
        self.assertIn("MY PBS", message)
        rows = [{"id": i, "event_date": date(2026, 12, 29), "time_text": "x" * 4000} for i in range(8)]
        self.assertLess(len(seasons.format_history(2026, 2, rows, True)), 4096)


class OnboardingTests(unittest.TestCase):
    def member(self, **overrides):
        return dict({"id": 42, "first_name": "New", "last_name": "Member", "popia_acknowledged": True,
                     "participation_type": None, "leaderboard_visibility_set": False,
                     "profile_state": "ONBOARDING_PARTICIPATION"}, **overrides)

    def actions(self):
        actions = Mock()
        actions.DELETE_CONFIRMATION_STATE = "DELETE_CONFIRMATION"
        actions.is_admin.return_value = False
        return actions

    def test_typed_participation_resumes_saved_setup(self):
        for text, choice in (("RUNNER", "RUNNER"), ("WALK", "WALKER"), ("BOTH", "BOTH")):
            actions = self.actions()
            result = handle_member_message(actions, "2771", text, text, None, None, self.member())
            self.assertEqual(result["status"], "onboarding_await_visibility")
            actions.save_onboarding_participation_and_advance.assert_called_once_with(42, choice)
            actions.complete_onboarding_visibility.assert_not_called()

    def test_typed_visibility_finishes_with_next_steps_without_submitting(self):
        for text, private in (("PRIVATE", True), ("SHOW MY RESULTS", False)):
            actions = self.actions()
            result = handle_member_message(actions, "2771", text, text, None, None,
                self.member(profile_state="ONBOARDING_LEADERBOARD", participation_type="WALKER"))
            self.assertEqual(result["status"], "profile_complete")
            actions.complete_onboarding_visibility.assert_called_once_with(42, private)
            actions.send_onboarding_next_steps.assert_called_once_with("2771")
            actions.get_or_create_submission.assert_not_called()

    def test_returning_member_keeps_profile_when_renewing_consent(self):
        actions = self.actions()
        handle_member_message(actions, "2771", "OK", "OK", None, None,
            self.member(popia_acknowledged=False, profile_state=None,
                        participation_type="RUNNER", leaderboard_visibility_set=True))
        actions.acknowledge_popia.assert_called_once_with("2771")
        actions.save_onboarding_name_and_advance.assert_not_called()
        self.assertIn("existing profile", actions.send_text.call_args.args[1])
        actions.send_help_menu.assert_called_once()

    def test_invalid_visibility_does_not_finish_or_default_to_public(self):
        actions = self.actions()
        handle_member_message(actions, "2771", "YES", "yes", None, None,
            self.member(profile_state="ONBOARDING_LEADERBOARD", participation_type="RUNNER"))
        actions.complete_onboarding_visibility.assert_not_called()
        actions.send_leaderboard_visibility_buttons.assert_called_once()

    def test_pause_preserves_participation_step(self):
        actions = self.actions()
        result = handle_member_message(actions, "2771", "CANCEL", "cancel", None, None, self.member())
        self.assertEqual(result["status"], "onboarding_paused")
        actions.clear_profile_state.assert_not_called()

    def test_next_steps_only_offer_checkin_when_available(self):
        for available in (False, True):
            with patch.object(whatsapp, "_send", return_value=True) as send:
                whatsapp.send_onboarding_actions("2771", available)
            buttons = send.call_args.args[0]["interactive"]["action"]["buttons"]
            self.assertEqual("menu_submit" in [b["reply"]["id"] for b in buttons], available)
            self.assertLessEqual(len(buttons), 3)

    def test_member_and_admin_menus_stay_within_ten_rows(self):
        for admin in (False, True):
            with patch.object(whatsapp, "_send", return_value=True) as send:
                whatsapp.send_main_menu_list("2771", admin=admin)
            sections = send.call_args.args[0]["interactive"]["action"]["sections"]
            self.assertLessEqual(sum(len(section["rows"]) for section in sections), 10)


if __name__ == "__main__":
    unittest.main()
