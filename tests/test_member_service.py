import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from app.services import member_service as service


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


class MemberServiceTests(unittest.TestCase):
    def test_create_acknowledged_member_is_idempotent(self):
        cursor = FakeCursor(row={"id": 42, "popia_acknowledged": True})

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            row = service.create_member("27999999999", popia_acknowledged=True)

        self.assertEqual(row["id"], 42)
        self.assertIn("popia_acknowledged", cursor.query)
        self.assertIn("ON CONFLICT (phone)", cursor.query)
        self.assertEqual(cursor.params, ("27999999999", "Unknown", "Member", True))

    def test_leaderboard_opt_out_does_not_delete_member_or_results(self):
        cursor = FakeCursor()

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            service.opt_out_leaderboard("27999999999")

        self.assertIn("UPDATE members", cursor.query)
        self.assertIn("leaderboard_opt_out = TRUE", cursor.query)
        self.assertNotIn("DELETE", cursor.query.upper())
        self.assertNotIn("submissions", cursor.query.lower())

    def test_leaderboard_opt_in_restores_sharing_without_changing_results(self):
        cursor = FakeCursor()

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            service.opt_in_leaderboard("27999999999")

        self.assertIn("UPDATE members", cursor.query)
        self.assertIn("leaderboard_opt_out = FALSE", cursor.query)
        self.assertNotIn("DELETE", cursor.query.upper())
        self.assertNotIn("submissions", cursor.query.lower())


if __name__ == "__main__":
    unittest.main()
