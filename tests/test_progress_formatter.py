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
                    {"distance_text": "4", "seconds": 1600},
                    {"distance_text": "4", "seconds": 1660},
                    {"distance_text": "4", "seconds": 1720},
                ],
                "pace_comparison": [
                    "Compared with your last 4 km TT: 0:40 faster.",
                    "Rolling 3-TT pace: 5:10/km (improving by 0:10/km vs prior 3-TT window).",
                ],
            },
        )

        self.assertIn("Lindsay, your progress", message)
        self.assertIn("TT activities: 6", message)
        self.assertIn("Latest: 4km — 27:41 (6:55/km)", message)
        self.assertIn("Next milestone: 10 activities (4 to go)", message)
        self.assertIn("4km — 27:41", message)
        self.assertNotIn("Trend: 🔥 Improving", message)
        self.assertIn("Compared with your last 4 km TT: 0:40 faster.", message)
        self.assertIn("Rolling 3-TT pace: 5:10/km", message)

    def test_mixed_distances_do_not_show_false_improvement(self):
        message = format_progress(
            {"first_name": "Runner"},
            {"recent": [
                {"distance_text": "6", "seconds": 2200},
                {"distance_text": "8", "seconds": 2500},
                {"distance_text": "8", "seconds": 2600},
            ]},
        )
        self.assertIn("Trend: Not enough comparable runs yet.", message)
        self.assertNotIn("Improving", message)

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

    def test_formats_walker_specific_progress(self):
        message = format_progress(
            {"first_name": "Lindsay", "participation_type": "WALKER"},
            {
                "total_runs": 6,
                "latest": {
                    "distance_text": None,
                    "time_text": "Easy social walk",
                    "seconds": 0,
                },
                "pbs": [],
                "recent": [],
            },
        )

        self.assertIn("Lindsay, your walking progress", message)
        self.assertIn("Activities logged: 6", message)
        self.assertIn("Latest: Easy social walk", message)
        self.assertIn("Next milestone: 10 walks (4 to go)", message)
        self.assertIn("Great consistency", message)
        self.assertNotIn("PBs", message)


if __name__ == "__main__":
    unittest.main()
