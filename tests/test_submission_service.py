import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from app.services import submission_service as service


class FakeCursor:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.queries = []
        self.params = []

    def execute(self, query, params=None):
        self.queries.append(query)
        self.params.append(params)

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None


@contextmanager
def fake_cursor_context(cursor, commit=True):
    yield cursor


class SubmissionServiceTests(unittest.TestCase):
    def test_get_or_create_submission_uses_event_date_and_pending_conflict_guard(self):
        select_cursor = FakeCursor(rows=[None])
        insert_cursor = FakeCursor(rows=[{"id": 101, "member_id": 42}])

        with patch.object(
            service,
            "get_cursor",
            side_effect=[
                fake_cursor_context(select_cursor, commit=False),
                fake_cursor_context(insert_cursor),
            ],
        ):
            row = service.get_or_create_submission(42)

        self.assertEqual(row, {"id": 101, "member_id": 42})
        self.assertIn("event_date =", select_cursor.queries[0])
        self.assertIn("ON CONFLICT (member_id, event_date)", insert_cursor.queries[0])
        self.assertIn("WHERE status = 'PENDING'", insert_cursor.queries[0])


if __name__ == "__main__":
    unittest.main()
