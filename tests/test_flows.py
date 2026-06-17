import unittest

from app.flows.help_flow import (
    format_help_menu,
    is_help_command,
    resolve_interactive_action,
    resolve_menu_action,
)
from app.flows.submission_state import (
    AWAITING_BOTH_CHOICE,
    AWAITING_CONFIRM,
    AWAITING_DISTANCE,
    AWAITING_TIME,
    AWAITING_WORKOUT,
    resolve_pending_submission_state,
)


class HelpFlowTests(unittest.TestCase):
    def test_help_aliases_and_menu_actions(self):
        self.assertTrue(is_help_command("\\HELP"))
        self.assertTrue(is_help_command("MENU"))
        self.assertEqual(resolve_menu_action("1"), "SUBMIT")
        self.assertEqual(resolve_menu_action("MY PROFILE"), "PROFILE")
        self.assertEqual(resolve_menu_action("3"), "PROGRESS")
        self.assertEqual(resolve_menu_action("SEASON PBS"), "SEASON_PB")
        self.assertEqual(resolve_menu_action("4"), "LEADERBOARD")
        self.assertEqual(resolve_menu_action("5"), "OVERALL_LEADERBOARD")
        self.assertEqual(resolve_menu_action("6"), "EDIT_PROFILE")
        self.assertEqual(resolve_menu_action("7"), "OPT_OUT")
        self.assertEqual(resolve_menu_action("PROGRESS"), "PROGRESS")
        self.assertEqual(resolve_interactive_action("menu_progress"), "PROGRESS")
        self.assertEqual(
            resolve_interactive_action("menu_overall_leaderboard"),
            "OVERALL_LEADERBOARD",
        )
        self.assertEqual(resolve_interactive_action("admin_tt_code"), "ADMIN_TT_CODE")

    def test_admin_menu_includes_admin_commands(self):
        self.assertIn("Admin commands", format_help_menu(admin=True))
        self.assertNotIn("Admin commands", format_help_menu(admin=False))


class SubmissionStateTests(unittest.TestCase):
    def test_resolves_pending_submission_states(self):
        self.assertEqual(
            resolve_pending_submission_state(
                {"participation_type": "WALKER"},
                {"time_text": ""},
            ),
            AWAITING_WORKOUT,
        )
        self.assertEqual(
            resolve_pending_submission_state(
                {"participation_type": "BOTH"},
                {"distance_text": None, "time_text": ""},
            ),
            AWAITING_BOTH_CHOICE,
        )
        self.assertEqual(
            resolve_pending_submission_state(
                {"participation_type": "RUNNER"},
                {"distance_text": None, "time_text": ""},
            ),
            AWAITING_DISTANCE,
        )
        self.assertEqual(
            resolve_pending_submission_state(
                {"participation_type": "RUNNER"},
                {"distance_text": "4", "time_text": ""},
            ),
            AWAITING_TIME,
        )
        self.assertEqual(
            resolve_pending_submission_state(
                {"participation_type": "RUNNER"},
                {"distance_text": "4", "time_text": "27:41"},
            ),
            AWAITING_CONFIRM,
        )


if __name__ == "__main__":
    unittest.main()
