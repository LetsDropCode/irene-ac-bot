import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from app.services import admin_service as service


class FakeCursor:
    def __init__(self, row=None):
        self.query = None
        self.params = None
        self.row = row
        self.executed = []

    def execute(self, query, params=None):
        self.query = query
        self.params = params
        self.executed.append((query, params))

    def fetchone(self):
        return self.row


@contextmanager
def fake_cursor_context(cursor):
    yield cursor


class AdminServiceTests(unittest.TestCase):
    def test_get_member_submission_history_looks_up_by_member_id(self):
        cursor = FakeCursor(row=None)
        cursor.fetchall = lambda: [{"submission_id": 101}]

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            rows = service.get_member_submission_history("42")

        self.assertEqual(rows, [{"submission_id": 101}])
        self.assertIn("ORDER BY s.created_at DESC", cursor.query)
        self.assertEqual(cursor.params, (42, 42, "42", "42", 20))

    def test_get_submission_for_admin_loads_submission_by_id(self):
        cursor = FakeCursor(row={"submission_id": 101})

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            row = service.get_submission_for_admin(101)

        self.assertEqual(row, {"submission_id": 101})
        self.assertIn("WHERE s.id = %s", cursor.query)
        self.assertEqual(cursor.params, (101,))

    def test_correct_submission_by_id_updates_exact_submission(self):
        cursor = FakeCursor(row={"id": 101})

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            row = service.correct_submission_by_id(101, "6", "42:00", 2520)

        self.assertEqual(row, {"id": 101})
        self.assertIn("WHERE s.id = %s", cursor.query)
        self.assertEqual(cursor.params, (101, "6", "42:00", 2520))

    def test_correct_submission_by_id_records_admin_audit(self):
        cursor = FakeCursor(row={
            "id": 101,
            "member_id": 42,
            "old_distance_text": "4",
            "old_time_text": "27:41",
            "old_seconds": 1661,
            "distance_text": "6",
            "time_text": "42:00",
            "seconds": 2520,
        })

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            row = service.correct_submission_by_id(101, "6", "42:00", 2520, admin_member_id=7)

        self.assertEqual(row["id"], 101)
        audit_query, audit_params = cursor.executed[-1]
        self.assertIn("INSERT INTO admin_corrections", audit_query)
        self.assertEqual(
            audit_params,
            (7, 101, 42, "4", "27:41", 1661, "6", "42:00", 2520, "selected_submission"),
        )

    def test_correct_runner_pb_targets_best_runner_or_both_submission(self):
        cursor = FakeCursor(row={"id": 101})

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            row = service.correct_runner_pb("42", "4", "26:59", 1619)

        self.assertEqual(row, {"id": 101})
        self.assertIn("AND m.participation_type IN ('RUNNER', 'BOTH')", cursor.query)
        self.assertIn("ORDER BY s.seconds ASC, s.created_at ASC", cursor.query)
        self.assertEqual(cursor.params, ("4", 42, 42, "42", "42", "4", "26:59", 1619))

    def test_correct_runner_time_on_date_targets_submitted_date(self):
        cursor = FakeCursor(row={"id": 101})

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            row = service.correct_runner_time_on_date("42", "2026-06-09", "6", "42:00", 2520)

        self.assertEqual(row, {"id": 101})
        self.assertIn("= %s", cursor.query)
        self.assertIn("ORDER BY s.created_at DESC", cursor.query)
        self.assertEqual(cursor.params, ("2026-06-09", 42, 42, "42", "42", "6", "42:00", 2520))


if __name__ == "__main__":
    unittest.main()
