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

    def test_reopening_runner_result_for_edit_resets_the_same_submission(self):
        cursor = FakeCursor(rows=[{"id": 101, "status": "PENDING"}])

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            row = service.reopen_submission_for_edit(101)

        self.assertEqual(row, {"id": 101, "status": "PENDING"})
        query = cursor.queries[0]
        self.assertIn("UPDATE submissions", query)
        self.assertNotIn("INSERT", query)
        self.assertIn("status = 'PENDING'", query)
        self.assertIn("confirmed = FALSE", query)
        self.assertIn("distance_text = NULL", query)
        self.assertIn("time_text = ''", query)
        self.assertIn("seconds = 0", query)
        self.assertIn("mode = 'RUN'", query)
        self.assertEqual(cursor.params[0], (101,))

    def test_member_self_correction_stores_proposal_without_updating_submission(self):
        cursor = FakeCursor(rows=[{"id": 501, "submission_id": 101}])

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            row = service.start_member_self_correction(42, 101, "RUN")

        self.assertEqual(row["id"], 501)
        query = cursor.queries[0]
        self.assertIn("INSERT INTO member_self_corrections", query)
        self.assertNotIn("UPDATE submissions", query)
        self.assertIn("s.status = 'COMPLETE'", query)
        self.assertEqual(cursor.params[0], (42, "RUN", 101, 42))

    def test_apply_member_self_correction_updates_existing_complete_row_once(self):
        cursor = FakeCursor(rows=[{"id": 101, "status": "COMPLETE"}])

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            row = service.apply_member_self_correction(501, 42)

        self.assertEqual(row, {"id": 101, "status": "COMPLETE"})
        query = cursor.queries[0]
        self.assertIn("DELETE FROM member_self_corrections", query)
        self.assertIn("UPDATE submissions", query)
        self.assertNotIn("INSERT INTO submissions", query)
        self.assertIn("s.status = 'COMPLETE'", query)
        self.assertIn("s.tt_code_verified = TRUE", query)
        self.assertIn("distance_text IN ('4', '6', '8')", query)
        self.assertEqual(cursor.params[0], (501, 42))

    def test_save_workout_for_confirmation_keeps_submission_pending(self):
        cursor = FakeCursor(rows=[{"id": 101, "status": "PENDING"}])

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            row = service.save_workout_for_confirmation(101, "45 min walk")

        self.assertEqual(row["status"], "PENDING")
        self.assertIn("status = 'PENDING'", cursor.queries[0])
        self.assertIn("confirmed = FALSE", cursor.queries[0])
        self.assertIn("mode = 'WORKOUT'", cursor.queries[0])

    def test_confirm_workout_submission_completes_only_a_saved_workout(self):
        cursor = FakeCursor(rows=[{"id": 101, "status": "COMPLETE"}])

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            row = service.confirm_workout_submission(101)

        self.assertEqual(row["status"], "COMPLETE")
        self.assertIn("status = 'COMPLETE'", cursor.queries[0])
        self.assertIn("tt_code_verified = TRUE", cursor.queries[0])
        self.assertIn("mode = 'WORKOUT'", cursor.queries[0])

    def test_confirm_runner_submission_requires_a_complete_verified_result(self):
        cursor = FakeCursor(rows=[{"id": 101, "status": "COMPLETE"}])

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            row = service.confirm_submission(101)

        self.assertEqual(row["status"], "COMPLETE")
        query = cursor.queries[0]
        self.assertIn("status = 'PENDING'", query)
        self.assertIn("tt_code_verified = TRUE", query)
        self.assertIn("distance_text IN ('4', '6', '8')", query)
        self.assertIn("COALESCE(time_text, '') <> ''", query)
        self.assertIn("COALESCE(seconds, 0) > 0", query)

    def test_self_correctable_submission_uses_the_single_current_tt_event_date(self):
        cursor = FakeCursor(rows=[{"id": 101, "event_date": "2026-09-08"}])

        with patch.object(service, "self_correctable_event_date", return_value="2026-09-08"), patch.object(
            service, "get_cursor", return_value=fake_cursor_context(cursor, commit=False)
        ):
            row = service.get_self_correctable_tt_submission(42)

        self.assertEqual(row["id"], 101)
        self.assertIn("tt_code_verified = TRUE", cursor.queries[0])
        self.assertIn("event_date = %s", cursor.queries[0])
        self.assertEqual(cursor.params[0], (42, "2026-09-08"))

    def test_self_correctable_submission_does_not_query_without_an_eligible_event_date(self):
        with patch.object(service, "self_correctable_event_date", return_value=None), patch.object(
            service, "get_cursor"
        ) as get_cursor:
            row = service.get_self_correctable_tt_submission(42)

        self.assertIsNone(row)
        get_cursor.assert_not_called()

    def test_release_pending_submissions_returns_update_count_without_fetching(self):
        cursor = FakeCursor(rowcount=3)

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            released = service.release_pending_submissions(42)

        self.assertEqual(released, 3)
        self.assertIn("UPDATE submissions", cursor.queries[0])
        self.assertIn("tt_code_verified = FALSE", cursor.queries[0])


if __name__ == "__main__":
    unittest.main()
