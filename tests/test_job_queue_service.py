import os
import unittest
from contextlib import contextmanager
from datetime import date
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from app.services import job_queue_service as service


class FakeCursor:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows
        self.query = None
        self.params = None

    def execute(self, query, params=None):
        self.query = query
        self.params = params

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows or []


class InMemoryJobCursor:
    """Small stateful queue double for exercising real service transitions."""

    def __init__(self, jobs):
        self.jobs = jobs
        self.row = None
        self.rows = []
        self.query = None
        self.params = None

    def execute(self, query, params=None):
        self.query = query
        self.params = params
        self.row = None
        self.rows = []

        if "WITH jobs_to_retry" in query:
            limit = params[0]
            failed = sorted(
                (job for job in self.jobs if job["status"] == "FAILED"),
                key=lambda job: job["id"],
            )[:limit]
            for job in failed:
                job.update(
                    status="PENDING",
                    attempts=0,
                    run_after="now",
                    locked_at=None,
                    last_error=None,
                )
            self.rows = [{"id": job["id"]} for job in failed]
            return

        if "WITH next_job" in query:
            claimable = next(
                (
                    job
                    for job in self.jobs
                    if job["status"] == "PENDING"
                    and job["attempts"] < job["max_attempts"]
                ),
                None,
            )
            if claimable:
                claimable.update(status="RUNNING", locked_at="now")
                claimable["attempts"] += 1
                self.row = dict(claimable)
            return

        if "SET status = 'DONE'" in query:
            job = next(job for job in self.jobs if job["id"] == params[0])
            job.update(status="DONE", last_error=None)
            return

        if "SET status = %s" in query:
            status, run_after, error, job_id = params
            job = next(job for job in self.jobs if job["id"] == job_id)
            job.update(status=status, run_after=run_after, last_error=error)

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


@contextmanager
def fake_cursor_context(cursor, commit=True):
    yield cursor


def in_memory_cursor_context(jobs):
    return fake_cursor_context(InMemoryJobCursor(jobs))


class JobQueueServiceTests(unittest.TestCase):
    def test_enqueue_post_confirm_messages_stores_durable_job(self):
        with patch.object(service, "enqueue_job", return_value=11) as enqueue_job:
            job_id = service.enqueue_post_confirm_messages(
                "27999999999",
                {"id": 42, "first_name": "Lindsay", "phone": "27999999999", "admin": True},
                {
                    "id": 101,
                    "event_date": date(2026, 7, 7),
                    "member_id": 42,
                    "distance_text": "8",
                    "time_text": "43:21",
                    "seconds": 2601,
                },
                1800,
            )

        self.assertEqual(job_id, 11)
        job_type, payload = enqueue_job.call_args.args
        self.assertEqual(job_type, service.JOB_POST_CONFIRM_MESSAGES)
        self.assertEqual(
            payload,
            {
                "sender": "27999999999",
                "member_id": 42,
                "first_name": "Lindsay",
                "submission": {"distance_text": "8", "time_text": "43:21", "seconds": 2601},
                "previous_best": 1800,
            },
        )
        self.assertNotIn("member", payload)
        self.assertNotIn("phone", payload)
        self.assertNotIn("admin", payload)

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

        with patch.object(service, "recover_stale_running_jobs", return_value=0), patch.object(
            service, "_claim_next_job", side_effect=claim
        ), patch.object(service, "_run_job") as run_job:
            processed = service.run_due_jobs(limit=5)

        self.assertEqual(processed, 1)
        run_job.assert_called_once()

    def test_recover_stale_running_jobs_requeues_or_fails_expired_leases(self):
        cursor = FakeCursor(rows=[{"id": 7}, {"id": 8}])

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            recovered = service.recover_stale_running_jobs(
                stale_after_seconds=300,
                limit=20,
            )

        self.assertEqual(recovered, 2)
        self.assertIn("status = 'RUNNING'", cursor.query)
        self.assertIn("FOR UPDATE SKIP LOCKED", cursor.query)
        self.assertIn("WHEN q.attempts >= q.max_attempts THEN 'FAILED'", cursor.query)
        self.assertIn("ELSE 'PENDING'", cursor.query)
        self.assertEqual(cursor.params, (300, 20))

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

    def test_get_failed_jobs_returns_recent_failures(self):
        cursor = FakeCursor(rows=[{"id": 7, "job_type": "whatsapp_send"}])

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            rows = service.get_failed_jobs(limit=3)

        self.assertEqual(rows, [{"id": 7, "job_type": "whatsapp_send"}])
        self.assertIn("WHERE status = 'FAILED'", cursor.query)
        self.assertEqual(cursor.params, (3,))

    def test_retry_failed_jobs_resets_attempts_and_uses_locked_selection(self):
        cursor = FakeCursor(rows=[{"id": 7}, {"id": 8}])

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            retried = service.retry_failed_jobs(limit=2)

        self.assertEqual(retried, 2)
        self.assertIn("SET status = 'PENDING'", cursor.query)
        self.assertIn("attempts = 0", cursor.query)
        self.assertIn("run_after = CURRENT_TIMESTAMP", cursor.query)
        self.assertIn("locked_at = NULL", cursor.query)
        self.assertIn("last_error = NULL", cursor.query)
        self.assertIn("FOR UPDATE SKIP LOCKED", cursor.query)
        self.assertEqual(cursor.params, (2,))

    def test_explicit_retry_returns_exhausted_job_to_full_claim_and_done_lifecycle(self):
        jobs = [{
            "id": 7,
            "job_type": "anything",
            "payload": {},
            "status": "FAILED",
            "attempts": 3,
            "max_attempts": 3,
            "run_after": "later",
            "locked_at": "old lease",
            "last_error": "network timeout",
        }]

        with patch.object(service, "get_cursor", side_effect=lambda: in_memory_cursor_context(jobs)):
            self.assertEqual(service.retry_failed_jobs(), 1)
            self.assertEqual(jobs[0]["status"], "PENDING")
            self.assertEqual(jobs[0]["attempts"], 0)
            self.assertIsNone(jobs[0]["locked_at"])
            self.assertIsNone(jobs[0]["last_error"])

            claimed = service._claim_next_job()
            self.assertEqual(claimed["id"], 7)
            self.assertEqual(claimed["attempts"], 1)
            self.assertEqual(jobs[0]["status"], "RUNNING")

            with patch.object(service, "_dispatch_job"):
                service._run_job(claimed)

        self.assertEqual(jobs[0]["status"], "DONE")

    def test_explicit_retry_respects_limit_and_does_not_duplicate_jobs(self):
        jobs = [
            {"id": 1, "status": "FAILED", "attempts": 3, "max_attempts": 3},
            {"id": 2, "status": "FAILED", "attempts": 3, "max_attempts": 3},
            {"id": 3, "status": "FAILED", "attempts": 3, "max_attempts": 3},
        ]

        with patch.object(service, "get_cursor", side_effect=lambda: in_memory_cursor_context(jobs)):
            self.assertEqual(service.retry_failed_jobs(limit=2), 2)

        self.assertEqual([job["id"] for job in jobs], [1, 2, 3])
        self.assertEqual([job["status"] for job in jobs], ["PENDING", "PENDING", "FAILED"])
        self.assertEqual([job["attempts"] for job in jobs], [0, 0, 3])

    def test_explicit_retry_returns_zero_when_no_jobs_are_failed(self):
        jobs = [{"id": 1, "status": "DONE", "attempts": 1, "max_attempts": 3}]

        with patch.object(service, "get_cursor", side_effect=lambda: in_memory_cursor_context(jobs)):
            self.assertEqual(service.retry_failed_jobs(), 0)

        self.assertEqual(jobs[0]["status"], "DONE")

    def test_manually_retried_job_returns_to_normal_failure_lifecycle(self):
        jobs = [{
            "id": 7,
            "job_type": "anything",
            "payload": {},
            "status": "FAILED",
            "attempts": 3,
            "max_attempts": 3,
        }]

        with patch.object(service, "get_cursor", side_effect=lambda: in_memory_cursor_context(jobs)):
            service.retry_failed_jobs()
            for attempt in range(1, 4):
                claimed = service._claim_next_job()
                self.assertEqual(claimed["attempts"], attempt)
                service._mark_job_failed(claimed, RuntimeError("retry failed"))

        self.assertEqual(jobs[0]["attempts"], 3)
        self.assertEqual(jobs[0]["status"], "FAILED")

    def test_unknown_job_type_fails_loudly(self):
        with self.assertRaises(ValueError):
            service._dispatch_job("missing", {})


if __name__ == "__main__":
    unittest.main()
