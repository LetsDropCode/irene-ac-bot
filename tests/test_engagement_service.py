import os
import unittest
from contextlib import contextmanager
from datetime import date
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from app.services import engagement_service as service


class Cursor:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows or []
        self.statements = []

    def execute(self, query, params=None):
        self.statements.append((" ".join(query.split()), params))

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


@contextmanager
def context(cursor, commit=True):
    yield cursor


class EngagementServiceTests(unittest.TestCase):
    def test_weekly_streak_and_next_attendance_milestone(self):
        stats = service.calculate_attendance_stats(
            [date(2026, 9, 1), date(2026, 9, 8), date(2026, 9, 22),
             date(2026, 9, 29), date(2026, 10, 6)],
            today=date(2026, 10, 6),
        )
        self.assertEqual(stats["total"], 5)
        self.assertEqual(stats["current_streak"], 3)
        self.assertEqual(stats["longest_streak"], 3)
        self.assertEqual(stats["next_milestone"], 10)
        self.assertIn("5 TT check-ins", service.milestone_message(stats))

    def test_streak_resets_when_latest_tuesday_was_missed(self):
        stats = service.calculate_attendance_stats(
            [date(2026, 9, 22), date(2026, 9, 29)],
            today=date(2026, 10, 7),
        )
        self.assertEqual(stats["current_streak"], 0)
        self.assertEqual(stats["longest_streak"], 2)

    def test_last_weeks_streak_is_current_until_tuesday_check_in(self):
        stats = service.calculate_attendance_stats(
            [date(2026, 9, 22), date(2026, 9, 29)],
            today=date(2026, 10, 6),
        )
        self.assertEqual(stats["current_streak"], 2)

    def test_non_tuesday_rows_do_not_count_as_tt_streak(self):
        stats = service.calculate_attendance_stats(
            [date(2026, 10, 6), date(2026, 10, 7)],
            today=date(2026, 10, 6),
        )
        self.assertEqual(stats["total"], 1)

    def test_no_proactive_message_without_milestone_or_streak(self):
        self.assertIsNone(service.milestone_message({"total": 3, "current_streak": 1}))

    def test_preference_is_allowlisted_and_opt_out_purges_queued_jobs(self):
        cursor = Cursor(row={"id": 42})
        with patch.object(service, "get_cursor", return_value=context(cursor)):
            self.assertTrue(service.set_engagement_preference(42, "reminders", False))
        self.assertIn("reminders_opt_in = %s", cursor.statements[0][0])
        self.assertIn("DELETE FROM job_queue", cursor.statements[1][0])
        self.assertEqual(cursor.statements[1][1], (service.JOB_INCOMPLETE_REMINDER, "42"))
        with self.assertRaises(ValueError):
            service.set_engagement_preference(42, "members; DROP TABLE members", True)

    def test_opt_in_does_not_purge_jobs(self):
        cursor = Cursor(row={"id": 42})
        with patch.object(service, "get_cursor", return_value=context(cursor)):
            self.assertTrue(service.set_engagement_preference(42, "milestones", True))
        self.assertEqual(len(cursor.statements), 1)

    def test_milestone_delivery_rechecks_consent_under_lock(self):
        cursor = Cursor(row=None)
        with patch.object(service, "get_cursor", return_value=context(cursor)), patch(
            "app.whatsapp._send_direct"
        ) as direct:
            self.assertFalse(service.send_attendance_milestone(
                {"member_id": 42, "event_date": "2026-10-06"}
            ))
        self.assertIn("milestones_opt_in = TRUE", cursor.statements[0][0])
        self.assertIn("FOR SHARE", cursor.statements[0][0])
        direct.assert_not_called()

    def test_milestone_delivery_formats_current_streak(self):
        cursor = Cursor(row={"phone": "27999999999"})
        stats = {"total": 5, "current_streak": 3}
        with patch.object(service, "get_cursor", return_value=context(cursor)), patch.object(
            service, "get_attendance_stats", return_value=stats
        ), patch.dict(os.environ, {"WHATSAPP_MILESTONE_TEMPLATE_NAME": "tt_milestone"}), patch(
            "app.whatsapp._send_direct", return_value=True
        ) as direct:
            self.assertTrue(service.send_attendance_milestone(
                {"member_id": 42, "event_date": "2026-10-06"}
            ))
        sent = direct.call_args.args[0]
        self.assertEqual(sent["type"], "template")
        self.assertEqual(sent["template"]["name"], "tt_milestone")
        self.assertEqual(
            [item["text"] for item in sent["template"]["components"][0]["parameters"]],
            ["5", "3"],
        )


if __name__ == "__main__":
    unittest.main()
