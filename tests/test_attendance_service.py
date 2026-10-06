import os
import unittest
from contextlib import contextmanager
from datetime import date
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from app.services import attendance_service as service


class Cursor:
    def __init__(self, rows):
        self.rows = iter(rows)
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((query, params))

    def fetchone(self):
        return next(self.rows)


@contextmanager
def context(cursor, commit=True):
    yield cursor


class AttendanceServiceTests(unittest.TestCase):
    def test_opted_in_checkin_queues_one_durable_milestone_job_in_same_transaction(self):
        cursor = Cursor([
            {"member_id": 42, "event_date": date(2026, 10, 6)},
            {"popia_acknowledged": True, "milestones_opt_in": True},
        ])
        with patch.object(service, "get_cursor", return_value=context(cursor)), patch.object(
            service, "enqueue_job", return_value=11
        ) as enqueue:
            row = service.mark_attendance(42)

        self.assertEqual(row["member_id"], 42)
        self.assertEqual(enqueue.call_args.kwargs["dedupe_key"], "attendance-milestone:42:2026-10-06")
        self.assertIs(enqueue.call_args.kwargs["cursor"], cursor)

    def test_no_milestone_job_without_explicit_opt_in(self):
        cursor = Cursor([
            {"member_id": 42, "event_date": date(2026, 10, 6)},
            {"popia_acknowledged": True, "milestones_opt_in": False},
        ])
        with patch.object(service, "get_cursor", return_value=context(cursor)), patch.object(
            service, "enqueue_job"
        ) as enqueue:
            service.mark_attendance(42)
        enqueue.assert_not_called()


if __name__ == "__main__":
    unittest.main()
