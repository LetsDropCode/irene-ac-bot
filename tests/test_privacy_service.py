import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from app.services import privacy_service


class RecordingCursor:
    def __init__(self, rows):
        self.rows = iter(rows)
        self.statements = []

    def execute(self, query, params=None):
        self.statements.append((" ".join(query.split()), params))

    def fetchone(self):
        return next(self.rows)


@contextmanager
def cursor_context(cursor, commit=True):
    yield cursor


class PrivacyServiceTests(unittest.TestCase):
    def test_withdrawal_hides_results_and_purges_outbound_payloads(self):
        cursor = RecordingCursor([{"id": 42}])
        with patch.object(privacy_service, "get_cursor", return_value=cursor_context(cursor)):
            self.assertTrue(privacy_service.withdraw_consent_and_request_erasure("27999999999"))

        self.assertIn("popia_acknowledged = FALSE", cursor.statements[0][0])
        self.assertIn("leaderboard_opt_out = TRUE", cursor.statements[0][0])
        self.assertIn("profile_state = %s", cursor.statements[0][0])
        self.assertEqual(cursor.statements[1][1], ("42", "27999999999", "27999999999"))
        self.assertIn("DELETE FROM job_queue", cursor.statements[1][0])
        self.assertIn("q.dedupe_key LIKE", cursor.statements[2][0])

    def test_erasure_requires_pending_confirmation(self):
        cursor = RecordingCursor([None])
        with patch.object(privacy_service, "get_cursor", return_value=cursor_context(cursor)):
            self.assertFalse(privacy_service.erase_member_after_confirmation("27999999999"))

        self.assertEqual(len(cursor.statements), 1)
        self.assertIn("profile_state = %s", cursor.statements[0][0])

    def test_confirmed_erasure_removes_dependent_records_before_member(self):
        cursor = RecordingCursor([{"id": 42}])
        with patch.object(privacy_service, "get_cursor", return_value=cursor_context(cursor)):
            self.assertTrue(privacy_service.erase_member_after_confirmation("27999999999"))

        sql = [statement for statement, _ in cursor.statements]
        self.assertIn("FOR UPDATE", sql[0])
        self.assertIn("DELETE FROM job_queue", sql[1])
        self.assertIn("q.dedupe_key LIKE", sql[2])
        self.assertIn("UPDATE inbound_whatsapp_messages SET sender = NULL", sql[3])
        self.assertIn("status = 'PROCESSED'", sql[3])
        self.assertIn("DELETE FROM member_self_corrections", sql[4])
        self.assertIn("DELETE FROM admin_corrections", sql[5])
        self.assertIn("UPDATE admin_corrections SET admin_member_id = NULL", sql[6])
        self.assertIn("DELETE FROM attendance", sql[7])
        self.assertIn("DELETE FROM submissions", sql[8])
        self.assertIn("DELETE FROM members", sql[9])

    def test_cancel_does_not_restore_consent(self):
        cursor = RecordingCursor([{"id": 42}])
        with patch.object(privacy_service, "get_cursor", return_value=cursor_context(cursor)):
            self.assertTrue(privacy_service.cancel_erasure_request("27999999999"))

        self.assertNotIn("popia_acknowledged = TRUE", cursor.statements[0][0])
        self.assertIn("profile_state = NULL", cursor.statements[0][0])


if __name__ == "__main__":
    unittest.main()
