import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from app.services import leaderboard_service as service


class FakeCursor:
    def __init__(self):
        self.query = None
        self.params = None

    def execute(self, query, params=None):
        self.query = query
        self.params = params

    def fetchall(self):
        return []


@contextmanager
def fake_cursor_context(cursor, commit=False):
    yield cursor


class LeaderboardServiceTests(unittest.TestCase):
    def test_overall_leaderboard_filters_to_runner_members(self):
        cursor = FakeCursor()

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            service.get_overall_leaderboard(member_id=42)

        self.assertIn("AND m.participation_type IN ('RUNNER', 'BOTH')", cursor.query)
        self.assertEqual(cursor.params, (10, 42))

    def test_member_rankings_filters_to_runner_members(self):
        cursor = FakeCursor()

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            service.get_member_rankings(42)

        self.assertIn("AND m.participation_type IN ('RUNNER', 'BOTH')", cursor.query)
        self.assertEqual(cursor.params, (42,))


if __name__ == "__main__":
    unittest.main()
