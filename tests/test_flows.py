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
        self.assertEqual(resolve_menu_action("CODE"), "SUBMIT")
        self.assertEqual(resolve_menu_action("TIME"), "RESUME")
        self.assertEqual(resolve_menu_action("CHANGE"), "FIX_RESULT")
        self.assertEqual(resolve_menu_action("MY PROFILE"), "PROFILE")
        self.assertEqual(resolve_menu_action("3"), "PROGRESS")
        self.assertEqual(resolve_menu_action("4"), "LEADERBOARDS")
        self.assertEqual(resolve_menu_action("TONIGHT"), "TONIGHT_LEADERBOARD")
        self.assertEqual(resolve_menu_action("5"), "OVERALL_LEADERBOARD")
        self.assertEqual(resolve_menu_action("MY RANKING"), "MY_RANKING")
        self.assertEqual(resolve_menu_action("SHOP"), "SHOP")
        self.assertEqual(resolve_menu_action("6"), "SHOP")
        self.assertEqual(resolve_menu_action("7"), "EDIT_PROFILE")
        self.assertEqual(resolve_menu_action("8"), "OPT_OUT")
        self.assertEqual(resolve_menu_action("PROGRESS"), "PROGRESS")
        self.assertEqual(resolve_interactive_action("menu_progress"), "PROGRESS")
        self.assertEqual(resolve_interactive_action("menu_leaderboard"), "LEADERBOARDS")
        self.assertEqual(resolve_interactive_action("menu_shop"), "SHOP")
        self.assertEqual(resolve_interactive_action("leaderboard_tonight"), "TONIGHT_LEADERBOARD")
        self.assertEqual(resolve_interactive_action("leaderboard_overall"), "OVERALL_LEADERBOARD")
        self.assertEqual(resolve_interactive_action("leaderboard_my_ranking"), "MY_RANKING")
        self.assertEqual(resolve_menu_action("ADMIN"), "ADMIN_MENU")
        self.assertEqual(resolve_menu_action("STATUS"), "ADMIN_TT_STATUS")
        self.assertEqual(resolve_menu_action("RECOVER TONIGHT"), "ADMIN_RECOVER_TONIGHT")
        self.assertEqual(resolve_interactive_action("admin_menu"), "ADMIN_MENU")
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
