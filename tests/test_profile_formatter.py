import unittest

from app.services.profile_formatter import format_profile


class ProfileFormatterTests(unittest.TestCase):
    def test_profile_shows_opted_in_sharing_action(self):
        text = format_profile(
            {"first_name": "Lindsay", "last_name": "Bull", "participation_type": "RUNNER", "leaderboard_opt_out": False},
            {"total_runs": 0, "pbs": [], "recent": []},
        )

        self.assertIn("Leaderboard sharing: On", text)
        self.assertIn("STOP LEADERBOARD", text)
        self.assertIn("Last 5 Runs", text)

    def test_profile_shows_opted_out_sharing_action(self):
        text = format_profile(
            {"first_name": "Lindsay", "last_name": "Bull", "participation_type": "RUNNER", "leaderboard_opt_out": True},
            {"total_runs": 0, "pbs": [], "recent": []},
        )

        self.assertIn("Leaderboard sharing: Off", text)
        self.assertIn("START SHARING", text)


if __name__ == "__main__":
    unittest.main()
