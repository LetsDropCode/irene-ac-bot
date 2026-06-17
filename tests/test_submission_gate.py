import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.services import submission_gate

SA_TZ = ZoneInfo("Africa/Johannesburg")


class SubmissionGateTests(unittest.TestCase):
    def test_default_gate_blocks_before_open_time(self):
        with patch.object(submission_gate, "_get_event_config", return_value=None):
            allowed, reason = submission_gate.ensure_tt_open(
                now=datetime(2026, 6, 16, 16, 59, tzinfo=SA_TZ)
            )

        self.assertFalse(allowed)
        self.assertEqual(reason, "⏱ Submissions open at *17:00*.")

    def test_default_gate_allows_tuesday_during_window(self):
        with patch.object(submission_gate, "_get_event_config", return_value=None):
            allowed, reason = submission_gate.ensure_tt_open(
                now=datetime(2026, 6, 16, 18, 0, tzinfo=SA_TZ)
            )

        self.assertTrue(allowed)
        self.assertIsNone(reason)

    def test_default_gate_blocks_after_close_time(self):
        with patch.object(submission_gate, "_get_event_config", return_value=None):
            allowed, reason = submission_gate.ensure_tt_open(
                now=datetime(2026, 6, 16, 22, 31, tzinfo=SA_TZ)
            )

        self.assertFalse(allowed)
        self.assertEqual(reason, "⏱ Submissions close at *22:30*.")

    def test_default_gate_blocks_wrong_day(self):
        with patch.object(submission_gate, "_get_event_config", return_value=None):
            allowed, reason = submission_gate.ensure_tt_open(
                now=datetime(2026, 6, 17, 18, 0, tzinfo=SA_TZ)
            )

        self.assertFalse(allowed)
        self.assertEqual(reason, "⛔ Time Trials only happen on *Tuesdays*.")

    def test_gate_uses_database_event_config(self):
        config = {
            "day_of_week": 2,
            "open_time": "18:30",
            "close_time": "20:00",
        }

        with patch.object(submission_gate, "_get_event_config", return_value=config):
            allowed, reason = submission_gate.ensure_tt_open(
                now=datetime(2026, 6, 17, 18, 29, tzinfo=SA_TZ)
            )
            self.assertFalse(allowed)
            self.assertEqual(reason, "⏱ Submissions open at *18:30*.")

            allowed, reason = submission_gate.ensure_tt_open(
                now=datetime(2026, 6, 17, 18, 30, tzinfo=SA_TZ)
            )
            self.assertTrue(allowed)
            self.assertIsNone(reason)


if __name__ == "__main__":
    unittest.main()
