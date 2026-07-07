import os
import unittest
from contextlib import contextmanager
from datetime import date
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from app.services import health_service as service


class FakeCursor:
    def __init__(self, row=None, error=None):
        self.row = row
        self.error = error
        self.query = None

    def execute(self, query, params=None):
        if self.error:
            raise self.error
        self.query = query

    def fetchone(self):
        return self.row


@contextmanager
def fake_cursor_context(cursor, commit=False):
    yield cursor


class HealthServiceTests(unittest.TestCase):
    def test_health_is_ok_when_database_and_event_dates_are_ready(self):
        cursor = FakeCursor({
            "sa_date": date(2026, 7, 7),
            "submissions_missing_event_date": 0,
        })

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            result = service.get_system_health()

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["checks"]["database"]["status"], "ok")
        self.assertEqual(result["checks"]["submissions_event_date"]["missing_rows"], 0)
        self.assertIn("WHERE event_date IS NULL", cursor.query)

    def test_health_is_degraded_when_event_date_backfill_is_incomplete(self):
        cursor = FakeCursor({
            "sa_date": date(2026, 7, 7),
            "submissions_missing_event_date": 2,
        })

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            result = service.get_system_health()

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["checks"]["submissions_event_date"]["status"], "degraded")

    def test_health_reports_database_errors(self):
        cursor = FakeCursor(error=RuntimeError("db unavailable"))

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            result = service.get_system_health()

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["checks"]["database"]["status"], "error")
        self.assertIn("db unavailable", result["checks"]["database"]["detail"])


if __name__ == "__main__":
    unittest.main()
