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

    def test_explicit_visibility_choice_marks_onboarding_complete(self):
        cursor = FakeCursor()

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            service.set_leaderboard_visibility(42, True)

        self.assertIn("leaderboard_opt_out = %s", cursor.query)
        self.assertIn("leaderboard_visibility_set = TRUE", cursor.query)
        self.assertIn("profile_state = NULL", cursor.query)
        self.assertEqual(cursor.params, (True, 42))

    def test_onboarding_name_transition_is_atomic_and_keeps_visibility_private(self):
        cursor = FakeCursor(row={"id": 42})

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            service.save_onboarding_name_and_advance(42, "New", "Member")

        self.assertIn("profile_state = 'ONBOARDING_PARTICIPATION'", cursor.query)
        self.assertIn("leaderboard_visibility_set = FALSE", cursor.query)
        self.assertEqual(cursor.params, ("New", "Member", 42))

    def test_onboarding_participation_transition_is_atomic_and_keeps_visibility_private(self):
        cursor = FakeCursor(row={"id": 42})

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            service.save_onboarding_participation_and_advance(42, "RUNNER")

        self.assertIn("profile_state = 'ONBOARDING_LEADERBOARD'", cursor.query)
        self.assertIn("leaderboard_visibility_set = FALSE", cursor.query)
        self.assertEqual(cursor.params, ("RUNNER", 42))

    def test_onboarding_visibility_completion_is_atomic(self):
        cursor = FakeCursor(row={"id": 42})

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            service.complete_onboarding_visibility(42, False)

        self.assertIn("leaderboard_visibility_set = TRUE", cursor.query)
        self.assertIn("profile_state = NULL", cursor.query)
        self.assertIn("profile_state = 'ONBOARDING_LEADERBOARD'", cursor.query)
        self.assertEqual(cursor.params, (False, 42))


if __name__ == "__main__":
    unittest.main()
