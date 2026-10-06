import unittest
from datetime import date

from app.services.leaderboard_formatter import format_date_range_leaderboards


class DateRangeLeaderboardFormatterTests(unittest.TestCase):
    def test_each_tt_date_is_returned_as_its_own_leaderboard(self):
        runners = [
            {
                "event_date": date(2026, 9, 15),
                "distance_text": "8",
                "position": 1,
                "first_name": "Newer",
                "last_name": "Runner",
                "time_text": "40:00",
            },
            {
                "event_date": date(2026, 9, 8),
                "distance_text": "8",
                "position": 1,
                "first_name": "Earlier",
                "last_name": "Runner",
                "time_text": "41:00",
            },
        ]

        messages = format_date_range_leaderboards(runners, [])

        self.assertEqual(len(messages), 2)
        self.assertIn("Tue, 15 Sep 2026", messages[0])
        self.assertIn("Newer Runner", messages[0])
        self.assertNotIn("Earlier Runner", messages[0])
        self.assertIn("Tue, 08 Sep 2026", messages[1])
        self.assertIn("Earlier Runner", messages[1])

    def test_empty_range_has_clear_message(self):
        self.assertEqual(
            format_date_range_leaderboards([], []),
            ["🏁 No TT results found in that date range."],
        )


if __name__ == "__main__":
    unittest.main()
