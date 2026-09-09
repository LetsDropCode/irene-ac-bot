import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from app.services import submission_service as service


class FakeCursor:
    def __init__(self, rows=None, rowcount=0):
        self.rows = rows or []
        self.rowcount = rowcount
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
    def test_get_active_submission_only_reads_existing_pending_rows(self):
        cursor = FakeCursor(rows=[{"id": 101, "tt_code_verified": False}])

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor, commit=False)):
            row = service.get_active_submission(42)

        self.assertEqual(row, {"id": 101, "tt_code_verified": False})
        self.assertIn("SELECT *", cursor.queries[0])
        self.assertIn("status = 'PENDING'", cursor.queries[0])
        self.assertNotIn("INSERT", cursor.queries[0])

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

    def test_editing_distance_clears_old_time_and_sets_run_mode(self):
        cursor = FakeCursor(rows=[{"id": 101}])

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            service.save_distance(101, "6")

        self.assertIn("time_text = ''", cursor.queries[0])
        self.assertIn("seconds = 0", cursor.queries[0])
        self.assertIn("mode = 'RUN'", cursor.queries[0])

    def test_save_workout_and_confirm_is_one_atomic_update(self):
        cursor = FakeCursor(rows=[{"id": 101, "status": "COMPLETE"}])

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            row = service.save_workout_and_confirm(101, "45 min walk")

        self.assertEqual(row["status"], "COMPLETE")
        self.assertIn("status = 'COMPLETE'", cursor.queries[0])
        self.assertIn("confirmed = TRUE", cursor.queries[0])
        self.assertIn("mode = 'WORKOUT'", cursor.queries[0])

    def test_release_pending_submissions_returns_update_count_without_fetching(self):
        cursor = FakeCursor(rowcount=3)

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            released = service.release_pending_submissions(42)

        self.assertEqual(released, 3)
        self.assertIn("UPDATE submissions", cursor.queries[0])
        self.assertIn("tt_code_verified = FALSE", cursor.queries[0])


if __name__ == "__main__":
    unittest.main()
