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
    def test_tonight_leaderboard_uses_submission_mode_not_current_member_preference(self):
        cursor = FakeCursor()

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            service.get_runner_leaderboard()

        self.assertIn("AND (s.mode = 'RUN' OR s.mode IS NULL)", cursor.query)
        self.assertNotIn("m.participation_type", cursor.query)
        self.assertIn("AND m.leaderboard_visibility_set = TRUE", cursor.query)
        self.assertIn("AND COALESCE(m.leaderboard_opt_out, FALSE) = FALSE", cursor.query)
        self.assertEqual(cursor.params, ())

    def test_walker_feed_uses_submission_mode_not_current_member_preference(self):
        cursor = FakeCursor()

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            service.get_walker_feed()

        self.assertIn("AND (s.mode = 'WORKOUT' OR s.mode IS NULL)", cursor.query)
        self.assertNotIn("m.participation_type", cursor.query)
        self.assertIn("AND m.leaderboard_visibility_set = TRUE", cursor.query)
        self.assertIn("AND COALESCE(m.leaderboard_opt_out, FALSE) = FALSE", cursor.query)
        self.assertEqual(cursor.params, ())

    def test_overall_leaderboard_uses_runner_submission_mode(self):
        cursor = FakeCursor()

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            service.get_overall_leaderboard(member_id=42)

        self.assertIn("AND (s.mode = 'RUN' OR s.mode IS NULL)", cursor.query)
        self.assertNotIn("m.participation_type", cursor.query)
        self.assertIn("AND m.leaderboard_visibility_set = TRUE", cursor.query)
        self.assertEqual(cursor.params, (10, 42))

    def test_member_rankings_uses_runner_submission_mode(self):
        cursor = FakeCursor()

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            service.get_member_rankings(42)

        self.assertIn("AND (s.mode = 'RUN' OR s.mode IS NULL)", cursor.query)
        self.assertNotIn("m.participation_type", cursor.query)
        self.assertIn("AND m.leaderboard_visibility_set = TRUE", cursor.query)
        self.assertEqual(cursor.params, (42,))

    def test_public_broadcast_recipients_require_completed_visibility_choice(self):
        cursor = FakeCursor()

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            service.get_checked_in_tt_member_phones("2026-09-08")

        self.assertIn("m.leaderboard_visibility_set = TRUE", cursor.query)
        self.assertIn("COALESCE(m.leaderboard_opt_out, FALSE) = FALSE", cursor.query)


if __name__ == "__main__":
    unittest.main()
