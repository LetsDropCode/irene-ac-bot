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
    AWAITING_WORKOUT_CONFIRM,
    resolve_pending_submission_state,
)


class HelpFlowTests(unittest.TestCase):
    def test_help_aliases_and_menu_actions(self):
        self.assertTrue(is_help_command("\\HELP"))
        self.assertTrue(is_help_command("MENU"))
        self.assertEqual(resolve_menu_action("1"), "SUBMIT")
        self.assertEqual(resolve_menu_action("CODE"), "SUBMIT")
        self.assertEqual(resolve_menu_action("TT CODE"), "SUBMIT")
        self.assertEqual(resolve_menu_action("TT CODE", admin=True), "ADMIN_TT_CODE")
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
        self.assertEqual(resolve_menu_action("LEAGUE"), "LEAGUE_STANDINGS")
        self.assertEqual(resolve_menu_action("STANDINGS"), "LEAGUE_STANDINGS")
        self.assertEqual(resolve_menu_action("7"), "LEAGUE_STANDINGS")
        self.assertEqual(resolve_menu_action("8"), "OPT_OUT")
        self.assertEqual(resolve_menu_action("9"), "OPT_IN")
        self.assertEqual(resolve_menu_action("EDIT PROFILE"), "EDIT_PROFILE")
        self.assertEqual(resolve_menu_action("EDIT DETAILS"), "EDIT_PROFILE")
        self.assertEqual(resolve_interactive_action("menu_edit_profile"), "EDIT_PROFILE")
        self.assertEqual(resolve_menu_action("START SHARING"), "OPT_IN")
        self.assertEqual(resolve_interactive_action("menu_opt_in"), "OPT_IN")
        self.assertEqual(resolve_menu_action("PROGRESS"), "PROGRESS")
        self.assertEqual(resolve_interactive_action("menu_progress"), "PROGRESS")
        self.assertEqual(resolve_interactive_action("menu_leaderboard"), "LEADERBOARDS")
        self.assertEqual(resolve_interactive_action("menu_shop"), "SHOP")
        self.assertEqual(resolve_interactive_action("menu_league_standings"), "LEAGUE_STANDINGS")
        self.assertEqual(resolve_interactive_action("leaderboard_tonight"), "TONIGHT_LEADERBOARD")
        self.assertEqual(resolve_interactive_action("leaderboard_overall"), "OVERALL_LEADERBOARD")
        self.assertEqual(resolve_interactive_action("leaderboard_my_ranking"), "MY_RANKING")
        self.assertEqual(resolve_menu_action("ADMIN"), "ADMIN_MENU")
        self.assertEqual(resolve_menu_action("STATUS"), "ADMIN_TT_STATUS")
        self.assertEqual(resolve_menu_action("HISTORY"), "ADMIN_HISTORY")
        self.assertEqual(resolve_menu_action("TIMES"), "ADMIN_HISTORY")
        self.assertEqual(resolve_menu_action("CORRECT"), "ADMIN_CORRECT")
        self.assertEqual(resolve_menu_action("RECOVER TONIGHT"), "ADMIN_RECOVER_TONIGHT")
        self.assertEqual(resolve_menu_action("JOBS STATUS"), "ADMIN_JOBS_STATUS")
        self.assertEqual(resolve_menu_action("JOBS RUN"), "ADMIN_JOBS_RUN")
        self.assertEqual(resolve_menu_action("JOBS FAILED"), "ADMIN_JOBS_FAILED")
        self.assertEqual(resolve_menu_action("JOBS RETRY"), "ADMIN_JOBS_RETRY")
        self.assertEqual(resolve_interactive_action("admin_menu"), "ADMIN_MENU")
        self.assertEqual(resolve_interactive_action("admin_tt_code"), "ADMIN_TT_CODE")
        self.assertEqual(resolve_interactive_action("admin_correct"), "ADMIN_CORRECT")
        self.assertEqual(resolve_interactive_action("admin_find"), "ADMIN_FIND")
        self.assertEqual(resolve_interactive_action("admin_history"), "ADMIN_HISTORY")
        self.assertEqual(resolve_interactive_action("admin_jobs_status"), "ADMIN_JOBS_STATUS")
        self.assertEqual(resolve_interactive_action("admin_jobs_failed"), "ADMIN_JOBS_FAILED")
        self.assertEqual(resolve_interactive_action("admin_jobs_retry"), "ADMIN_JOBS_RETRY")
        self.assertEqual(resolve_interactive_action("admin_leaderboards"), "ADMIN_LEADERBOARDS")
        self.assertEqual(resolve_interactive_action("admin_member_history"), "ADMIN_MEMBER_HISTORY")
        self.assertEqual(resolve_interactive_action("admin_member_correct"), "ADMIN_MEMBER_CORRECT")

    def test_admin_context_only_overrides_the_real_tt_code_collision(self):
        # STATUS, HISTORY, PENDING, and CORRECT are already admin-only text
        # intents. The remaining audited member aliases have no conflicting
        # admin text command and deliberately retain their behavior.
        self.assertEqual(resolve_menu_action("STATUS", admin=True), "ADMIN_TT_STATUS")
        self.assertEqual(resolve_menu_action("HISTORY", admin=True), "ADMIN_HISTORY")
        self.assertEqual(resolve_menu_action("PENDING", admin=True), "ADMIN_PENDING")
        self.assertEqual(resolve_menu_action("CORRECT", admin=True), "ADMIN_CORRECT")
        self.assertEqual(resolve_menu_action("RESULTS", admin=True), "LEADERBOARDS")
        self.assertEqual(resolve_menu_action("TIME", admin=True), "RESUME")
        self.assertEqual(resolve_menu_action("CODE", admin=True), "SUBMIT")
        self.assertEqual(resolve_menu_action("TT", admin=True), "SUBMIT")
        self.assertIsNone(resolve_menu_action("START", admin=True))
        self.assertIsNone(resolve_menu_action("MENU", admin=True))

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

    def test_submission_mode_overrides_a_changed_member_preference(self):
        self.assertEqual(
            resolve_pending_submission_state(
                {"participation_type": "WALKER"},
                {"mode": "RUN", "distance_text": "8", "time_text": ""},
            ),
            AWAITING_TIME,
        )
        self.assertEqual(
            resolve_pending_submission_state(
                {"participation_type": "RUNNER"},
                {"mode": "WORKOUT", "distance_text": None, "time_text": ""},
            ),
            AWAITING_WORKOUT,
        )

    def test_both_member_submission_mode_selects_its_own_state_machine(self):
        self.assertEqual(
            resolve_pending_submission_state(
                {"participation_type": "BOTH"},
                {"mode": "RUN", "distance_text": None, "time_text": ""},
            ),
            AWAITING_DISTANCE,
        )
        self.assertEqual(
            resolve_pending_submission_state(
                {"participation_type": "BOTH"},
                {"mode": "WORKOUT", "distance_text": None, "time_text": ""},
            ),
            AWAITING_WORKOUT,
        )

    def test_legacy_mode_less_rows_remain_recoverable(self):
        self.assertEqual(
            resolve_pending_submission_state(
                {"participation_type": "RUNNER"},
                {"distance_text": "6", "time_text": ""},
            ),
            AWAITING_TIME,
        )
        self.assertEqual(
            resolve_pending_submission_state(
                {"participation_type": "RUNNER"},
                {"distance_text": None, "time_text": "Easy walk"},
            ),
            AWAITING_WORKOUT_CONFIRM,
        )


if __name__ == "__main__":
    unittest.main()
