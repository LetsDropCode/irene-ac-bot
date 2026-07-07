import os
import unittest
from contextlib import contextmanager
from datetime import date
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from app.services import job_queue_service as service


class FakeCursor:
    def __init__(self, row=None):
        self.row = row
        self.query = None
        self.params = None

    def execute(self, query, params=None):
        self.query = query
        self.params = params

    def fetchone(self):
        return self.row


@contextmanager
def fake_cursor_context(cursor, commit=True):
    yield cursor


class JobQueueServiceTests(unittest.TestCase):
    def test_enqueue_post_confirm_messages_stores_durable_job(self):
        cursor = FakeCursor(row={"id": 11})

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            job_id = service.enqueue_post_confirm_messages(
                "27999999999",
                {"id": 42},
                {"id": 101, "event_date": date(2026, 7, 7)},
                1800,
            )

        self.assertEqual(job_id, 11)
        self.assertIn("INSERT INTO job_queue", cursor.query)
        self.assertEqual(cursor.params[0], service.JOB_POST_CONFIRM_MESSAGES)

    def test_enqueue_whatsapp_text_stores_text_payload(self):
        cursor = FakeCursor(row={"id": 12})

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            job_id = service.enqueue_whatsapp_text("2771", "Hello")

        self.assertEqual(job_id, 12)
        self.assertEqual(cursor.params[0], service.JOB_WHATSAPP_SEND)

    def test_run_due_jobs_processes_until_queue_empty(self):
        jobs = [{"id": 1, "job_type": "anything", "payload": {}, "attempts": 1, "max_attempts": 3}]

        def claim():
            return jobs.pop(0) if jobs else None

        with patch.object(service, "_claim_next_job", side_effect=claim), patch.object(service, "_run_job") as run_job:
            processed = service.run_due_jobs(limit=5)

        self.assertEqual(processed, 1)
        run_job.assert_called_once()

    def test_get_queue_health_returns_queue_counts(self):
        cursor = FakeCursor(row={
            "pending_jobs": 2,
            "running_jobs": 1,
            "failed_jobs": 3,
            "done_jobs": 5,
            "oldest_pending_seconds": 90,
        })

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            result = service.get_queue_health()

        self.assertEqual(result["pending_jobs"], 2)
        self.assertEqual(result["failed_jobs"], 3)
        self.assertEqual(result["oldest_pending_seconds"], 90)
        self.assertIn("FROM job_queue", cursor.query)

    def test_unknown_job_type_fails_loudly(self):
        with self.assertRaises(ValueError):
            service._dispatch_job("missing", {})


if __name__ == "__main__":
    unittest.main()
