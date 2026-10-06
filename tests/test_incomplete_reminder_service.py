import os
import unittest
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from app.services import incomplete_reminder_service as service


class Cursor:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows or []
        self.query = None
        self.params = None

    def execute(self, query, params=None):
        self.query = query
        self.params = params

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


@contextmanager
def context(cursor, commit=True):
    yield cursor


class IncompleteReminderTests(unittest.TestCase):
    def test_only_verified_opted_in_pending_submissions_are_selected(self):
        cursor = Cursor(rows=[{"submission_id": 101, "member_id": 42}])
        with patch.object(service, "get_cursor", return_value=context(cursor)):
            rows = service.get_incomplete_submissions(datetime(2026, 10, 6).date())
        self.assertEqual(rows[0]["submission_id"], 101)
        for condition in (
            "s.status = 'PENDING'", "s.tt_code_verified = TRUE",
            "m.popia_acknowledged = TRUE", "m.reminders_opt_in = TRUE",
        ):
            self.assertIn(condition, cursor.query)

    def test_wednesday_run_queues_stable_jobs(self):
        now = datetime(2026, 10, 7, 11, 0, tzinfo=service.SA_TZ)
        rows = [{"submission_id": 101, "member_id": 42}]
        with patch.object(service, "get_incomplete_submissions", return_value=rows), patch.object(
            service, "enqueue_job", return_value=9
        ) as enqueue:
            first = service.queue_incomplete_submission_reminders(now)
            second = service.queue_incomplete_submission_reminders(now)
        self.assertEqual(first, second)
        self.assertEqual(first["queued"], 1)
        self.assertEqual(enqueue.call_args_list[0].kwargs["dedupe_key"], "incomplete-reminder:101")
        self.assertEqual(enqueue.call_args_list[1].kwargs["dedupe_key"], "incomplete-reminder:101")

    def test_scheduler_does_nothing_after_deadline(self):
        now = datetime(2026, 10, 7, 13, 1, tzinfo=service.SA_TZ)
        with patch.object(service, "get_incomplete_submissions") as query:
            result = service.queue_incomplete_submission_reminders(now)
        self.assertTrue(result["outside_window"])
        query.assert_not_called()

    def test_scheduler_waits_until_eleven_for_useful_lead_time(self):
        now = datetime(2026, 10, 7, 10, 59, tzinfo=service.SA_TZ)
        with patch.object(service, "get_incomplete_submissions") as query:
            result = service.queue_incomplete_submission_reminders(now)
        self.assertTrue(result["outside_window"])
        query.assert_not_called()

    def test_delivery_skips_completed_result_after_queuing(self):
        cursor = Cursor(row=None)
        payload = {"submission_id": 101, "member_id": 42, "event_date": "2026-10-06"}
        now = datetime(2026, 10, 7, 11, 5, tzinfo=service.SA_TZ)
        with patch.object(service, "datetime") as mocked_datetime, patch.object(
            service, "get_cursor", return_value=context(cursor)
        ), patch("app.whatsapp._send_direct") as direct:
            mocked_datetime.now.return_value = now
            self.assertFalse(service.send_incomplete_submission_reminder(payload))
        self.assertIn("s.status = 'PENDING'", cursor.query)
        self.assertIn("FOR SHARE", cursor.query)
        direct.assert_not_called()

    def test_delivery_sends_only_while_member_is_still_eligible(self):
        cursor = Cursor(row={"phone": "27999999999", "first_name": "Lindsay"})
        payload = {"submission_id": 101, "member_id": 42, "event_date": "2026-10-06"}
        now = datetime(2026, 10, 7, 11, 5, tzinfo=service.SA_TZ)
        with patch.object(service, "datetime") as mocked_datetime, patch.object(
            service, "get_cursor", return_value=context(cursor)
        ), patch.dict(os.environ, {"WHATSAPP_REMINDER_TEMPLATE_NAME": "tt_result_reminder"}), patch(
            "app.whatsapp._send_direct", return_value=True
        ) as direct:
            mocked_datetime.now.return_value = now
            self.assertTrue(service.send_incomplete_submission_reminder(payload))
        sent = direct.call_args.args[0]
        self.assertEqual(sent["type"], "template")
        self.assertEqual(sent["template"]["name"], "tt_result_reminder")
        self.assertEqual(sent["template"]["components"][0]["parameters"][0]["text"], "Lindsay")

    def test_delivery_skips_job_after_deadline_without_database_read(self):
        payload = {"submission_id": 101, "member_id": 42, "event_date": "2026-10-06"}
        now = datetime(2026, 10, 7, 13, 1, tzinfo=service.SA_TZ)
        with patch.object(service, "datetime") as mocked_datetime, patch.object(
            service, "get_cursor"
        ) as db:
            mocked_datetime.now.return_value = now
            self.assertFalse(service.send_incomplete_submission_reminder(payload))
        db.assert_not_called()

    def test_delivery_does_not_send_if_deadline_passes_during_eligibility_check(self):
        cursor = Cursor(row={"phone": "27999999999", "first_name": "Lindsay"})
        payload = {"submission_id": 101, "member_id": 42, "event_date": "2026-10-06"}
        before = datetime(2026, 10, 7, 12, 59, tzinfo=service.SA_TZ)
        after = datetime(2026, 10, 7, 13, 0, tzinfo=service.SA_TZ)
        with patch.object(service, "datetime") as mocked_datetime, patch.object(
            service, "get_cursor", return_value=context(cursor)
        ), patch("app.whatsapp._send_direct") as direct:
            mocked_datetime.now.side_effect = [before, after]
            self.assertFalse(service.send_incomplete_submission_reminder(payload))
        direct.assert_not_called()


if __name__ == "__main__":
    unittest.main()
