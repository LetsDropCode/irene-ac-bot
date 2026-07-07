import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from app.services import idempotency_service as service


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


class IdempotencyServiceTests(unittest.TestCase):
    def test_register_inbound_message_returns_true_for_new_message(self):
        cursor = FakeCursor(row={"message_id": "wamid.1"})

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            result = service.register_inbound_message("wamid.1", "27999999999")

        self.assertTrue(result)
        self.assertIn("ON CONFLICT (message_id) DO NOTHING", cursor.query)
        self.assertEqual(cursor.params, ("wamid.1", "27999999999"))

    def test_register_inbound_message_returns_false_for_duplicate(self):
        cursor = FakeCursor(row=None)

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            result = service.register_inbound_message("wamid.1", "27999999999")

        self.assertFalse(result)

    def test_missing_message_id_is_processable(self):
        self.assertTrue(service.register_inbound_message(None, "27999999999"))

    def test_mark_inbound_message_processed_updates_status(self):
        cursor = FakeCursor()

        with patch.object(service, "get_cursor", return_value=fake_cursor_context(cursor)):
            service.mark_inbound_message_processed("wamid.1", "FAILED", "boom")

        self.assertIn("UPDATE inbound_whatsapp_messages", cursor.query)
        self.assertEqual(cursor.params, ("FAILED", "boom", "wamid.1"))


if __name__ == "__main__":
    unittest.main()
