import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from app.services import pb_service as service


class FakeCursor:
    def __init__(self):
        self.query = None
        self.params = None

    def execute(self, query, params=None):
        self.query = query
        self.params = params

    def fetchone(self):
        return {"best_time": 1661}


@contextmanager
def fake_cursor_context(cursor, commit=False):
    yield cursor


class PbServiceTests(unittest.TestCase):
    def test_pb_calculation_includes_runner_submissions_independent_of_member_preference(self):
        cursor = FakeCursor()

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            best = service.get_previous_best(42, "4")

        self.assertEqual(best, 1661)
        self.assertIn("(mode = 'RUN' OR mode IS NULL)", cursor.query)
        self.assertNotIn("participation_type", cursor.query)
        self.assertEqual(cursor.params, (42, "4"))
