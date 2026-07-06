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

    def execute(self, query, params=None):
        self.query = query
        self.params = params

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

    def test_correct_runner_pb_targets_best_runner_or_both_submission(self):
        cursor = FakeCursor(row={"id": 101})

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            row = service.correct_runner_pb("42", "4", "26:59", 1619)

        self.assertEqual(row, {"id": 101})
        self.assertIn("AND m.participation_type IN ('RUNNER', 'BOTH')", cursor.query)
        self.assertIn("ORDER BY s.seconds ASC, s.created_at ASC", cursor.query)
        self.assertEqual(cursor.params, ("4", 42, 42, "42", "42", "4", "26:59", 1619))


if __name__ == "__main__":
    unittest.main()
