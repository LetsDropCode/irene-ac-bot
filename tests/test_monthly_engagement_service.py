import os
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from app.services import monthly_engagement_service as service
from app.services import engagement_service
from test_engagement_service import Cursor, context


class MonthlyEngagementTests(unittest.TestCase):
    def test_calendar_boundaries_include_leap_february_and_year_rollover(self):
        self.assertEqual(service.month_bounds(date(2028, 2, 29)), (date(2028, 2, 1), date(2028, 3, 1)))
        self.assertEqual(service.previous_month(date(2027, 1, 1)), date(2026, 12, 1))
        self.assertEqual(service.month_bounds(date(2026, 12, 31)), (date(2026, 12, 1), date(2027, 1, 1)))

    def test_goal_keeps_extra_attendance_without_resetting_or_penalties(self):
        data = {"month": date(2026, 11, 1), "attendance": 4}
        self.assertIn("4 of 3", service.format_goal_line(data))
        self.assertIn("goal reached", service.format_goal_line(data))
        data["attendance"] = 0
        self.assertNotIn("goal reached", service.format_goal_line(data))

    def test_recap_compares_same_distance_and_does_not_call_first_time_an_improvement(self):
        data = {"month": date(2026, 10, 1), "attendance": 3, "activities": 2,
                "distance_km": 10, "bests": [
                    {"distance_text": "4", "best_seconds": 1600, "previous_seconds": 1618},
                    {"distance_text": "6", "best_seconds": 2300, "previous_seconds": None},
                    {"distance_text": "8", "best_seconds": 3300, "previous_seconds": 3200},
                ]}
        text = service.format_monthly_recap(data)
        self.assertIn("October 2026", text)
        self.assertIn("improved by 0:18", text)
        self.assertIn("First 6 km best", text)
        self.assertNotIn("8 km PB", text)
        self.assertIn("free-text walks aren't estimated", text)
        self.assertIn("RECAPS ON/OFF", text)

    def test_no_activity_has_neutral_recap(self):
        text = service.format_monthly_recap({"month": date(2026, 10, 1), "attendance": 0,
                                           "activities": 0, "distance_km": 0, "bests": []})
        self.assertIn("Join in whenever you're ready", text)
        self.assertNotIn("PB", text)

    def test_scheduler_waits_for_result_deadline_and_uses_south_africa_time(self):
        cursor = Cursor(rows=[{"id": 42}])
        with patch.object(service, "get_cursor", return_value=context(cursor)) as db, patch.object(
            service, "enqueue_job"
        ) as enqueue, patch.object(service, "recap_messages_available", return_value=True):
            # 11:59 UTC is 13:59 SAST, before the recap window.
            result = service.queue_monthly_recaps(datetime(2026, 11, 1, 11, 59, tzinfo=timezone.utc))
            self.assertEqual(result["queued"], 0)
            db.assert_not_called()
            result = service.queue_monthly_recaps(datetime(2026, 11, 1, 12, tzinfo=timezone.utc))
        self.assertEqual(result, {"month": "2026-10-01", "queued": 1})
        self.assertEqual(enqueue.call_args.kwargs["dedupe_key"], "monthly-recap:42:2026-10-01")

    def test_no_template_or_outside_window_never_queries_members(self):
        with patch.object(service, "get_cursor") as db, patch.object(
            service, "recap_messages_available", return_value=False
        ):
            self.assertEqual(service.queue_monthly_recaps(datetime(2026, 11, 1, 14))["queued"], 0)
        with patch.object(service, "get_cursor") as db, patch.object(
            service, "recap_messages_available", return_value=True
        ):
            for now in (datetime(2026, 11, 4, 14), datetime(2026, 11, 1, 20)):
                self.assertEqual(service.queue_monthly_recaps(now)["queued"], 0)
            db.assert_not_called()

    def test_delivery_skips_stale_month_or_withdrawn_consent(self):
        payload = {"member_id": 42, "month": "2026-10-01"}
        cursor = Cursor(row=None)
        with patch.object(service, "get_cursor", return_value=context(cursor)) as db, patch(
            "app.whatsapp._send_direct"
        ) as send:
            self.assertFalse(service.send_monthly_recap(payload, datetime(2026, 12, 1, 14)))
            db.assert_not_called()
            self.assertFalse(service.send_monthly_recap(payload, datetime(2026, 11, 4, 14)))
            db.assert_not_called()
            self.assertFalse(service.send_monthly_recap(payload, datetime(2026, 11, 1, 14)))
            send.assert_not_called()
        self.assertIn("recaps_opt_in = TRUE", cursor.statements[0][0])
        self.assertIn("popia_acknowledged = TRUE", cursor.statements[0][0])
        self.assertIn("FOR SHARE", cursor.statements[0][0])

    def test_delivery_uses_approved_template_and_retries_failed_send(self):
        data = {"month": date(2026, 10, 1), "attendance": 3, "activities": 2,
                "distance_km": 8, "bests": []}
        with patch.object(service, "get_cursor", side_effect=lambda **kw: context(Cursor(row={"phone": "27700000000"}))), patch.object(
            service, "get_monthly_recap", return_value=data
        ), patch.dict(os.environ, {"WHATSAPP_MONTHLY_RECAP_TEMPLATE_NAME": "monthly"}), patch(
            "app.whatsapp._send_direct", return_value=True
        ) as send:
            payload = {"member_id": 42, "month": "2026-10-01"}
            self.assertTrue(service.send_monthly_recap(payload, datetime(2026, 11, 1, 14)))
            message = send.call_args.args[0]
            self.assertEqual(message["type"], "template")
            params = message["template"]["components"][0]["parameters"]
            self.assertEqual([p["text"] for p in params[:5]], ["October 2026", "3", "2", "8", "Reached"])
            send.return_value = False
            with self.assertRaisesRegex(RuntimeError, "send returned false"):
                service.send_monthly_recap(payload, datetime(2026, 11, 1, 14))

    def test_recap_opt_out_only_cancels_recap_jobs(self):
        cursor = Cursor(row={"id": 42})
        with patch.object(engagement_service, "get_cursor", return_value=context(cursor)):
            self.assertTrue(engagement_service.set_engagement_preference(42, "recaps", False))
        self.assertIn("recaps_opt_in", cursor.statements[0][0])
        self.assertEqual(cursor.statements[1][1], (service.JOB_MONTHLY_RECAP, "42"))


if __name__ == "__main__":
    unittest.main()
