import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from app.services import event_code_service as service


class FakeCursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self.executed = []

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchone(self):
        if self.rows:
            return self.rows.pop(0)
        return None

    def close(self):
        pass


class FakeConnection:
    def __init__(self, cursor):
        self.cursor_obj = cursor
        self.committed = False
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


class EventCodeServiceTests(unittest.TestCase):
    def test_generate_tt_code_uses_upsert_for_new_daily_code(self):
        cursor = FakeCursor([None, {"code": "1234"}])
        conn = FakeConnection(cursor)

        with patch.object(service, "get_db", return_value=conn):
            with patch.object(service.random, "randint", return_value=1234):
                code = service.generate_tt_code("TT")

        self.assertEqual(code, "1234")
        self.assertTrue(conn.committed)
        insert_query, insert_params = cursor.executed[1]
        self.assertIn("ON CONFLICT (event, event_date)", insert_query)
        self.assertIn("RETURNING code", insert_query)
        self.assertEqual(insert_params[0], "TT")
        self.assertEqual(insert_params[1], "1234")

    def test_generate_tt_code_returns_existing_code_without_insert(self):
        cursor = FakeCursor([{"code": "5678"}])
        conn = FakeConnection(cursor)

        with patch.object(service, "get_db", return_value=conn):
            code = service.generate_tt_code("TT")

        self.assertEqual(code, "5678")
        self.assertEqual(len(cursor.executed), 1)
        self.assertFalse(conn.committed)
        self.assertTrue(conn.closed)


if __name__ == "__main__":
    unittest.main()
