import unittest

from app.services.progress_formatter import format_progress


class ProgressFormatterTests(unittest.TestCase):
    def test_formats_progress_with_latest_pbs_trend_and_next_milestone(self):
        message = format_progress(
            {"first_name": "Lindsay"},
            {
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
                "recent": [
                    {"seconds": 1600},
                    {"seconds": 1660},
                    {"seconds": 1720},
                ],
            },
        )

        self.assertIn("Lindsay, your progress", message)
        self.assertIn("TT activities: 6", message)
        self.assertIn("Latest: 4km — 27:41 (6:55/km)", message)
        self.assertIn("Next milestone: 10 activities (4 to go)", message)
        self.assertIn("4km — 27:41", message)
        self.assertIn("Trend: 🔥 Improving", message)

    def test_formats_progress_before_first_activity(self):
        message = format_progress(
            {"first_name": "Lindsay"},
            {
                "total_runs": 0,
                "latest": None,
                "pbs": [],
                "recent": [],
            },
        )

        self.assertIn("No TT activities logged yet.", message)
        self.assertIn("Next milestone: 1 activities (1 to go)", message)


if __name__ == "__main__":
    unittest.main()
