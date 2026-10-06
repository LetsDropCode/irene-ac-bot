import os
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from app import migrations
from app.migrations.versions import v20261006_baseline as baseline


class FakeCursor:
    def __init__(self):
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((query, params))


class VersionCursor(FakeCursor):
    def __init__(self, applied):
        super().__init__()
        self.applied = applied
        self.selected = None
        self.events = []

    def execute(self, query, params=None):
        super().execute(query, params)
        if "SELECT 1 FROM schema_migrations" in query:
            self.selected = params[0]
        elif "INSERT INTO schema_migrations (name) VALUES" in query:
            self.applied.add(params[0])

    def fetchone(self):
        return {"exists": 1} if self.selected in self.applied else None

    def fetchall(self):
        return [{"name": name} for name in self.applied]

    def close(self):
        pass


class FakeConnection:
    def __init__(self, applied):
        self.cur = VersionCursor(applied)
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


@contextmanager
def cursor_context(cur, commit=False):
    yield cur


class DatabaseMigrationTests(unittest.TestCase):
    def test_runner_applies_each_version_once_and_checks_schema(self):
        applied = set()
        connections = []
        events = []
        versions = (
            SimpleNamespace(VERSION="v1", upgrade=lambda _cur: events.append("v1")),
            SimpleNamespace(VERSION="v2", upgrade=lambda _cur: events.append("v2")),
        )

        def connection():
            conn = FakeConnection(applied)
            connections.append(conn)
            return conn

        with patch.object(migrations, "MIGRATIONS", versions), patch.object(
            migrations, "get_db", side_effect=connection
        ), patch.object(migrations, "get_cursor", side_effect=lambda commit=False: cursor_context(VersionCursor(applied))):
            self.assertEqual(migrations.upgrade_database(), ["v1", "v2"])
            self.assertEqual(migrations.upgrade_database(), [])
            migrations.require_current_schema()

        self.assertEqual(events, ["v1", "v2"])
        self.assertEqual(applied, {"v1", "v2"})
        self.assertEqual([conn.commits for conn in connections], [1, 1])
        self.assertTrue(all("pg_advisory_xact_lock" in conn.cur.queries[0][0] for conn in connections))

    def test_pending_migration_prevents_startup(self):
        versions = (SimpleNamespace(VERSION="v1"),)
        with patch.object(migrations, "MIGRATIONS", versions), patch.object(
            migrations, "get_cursor", return_value=cursor_context(VersionCursor(set()))
        ):
            with self.assertRaisesRegex(RuntimeError, "migrations are pending"):
                migrations.require_current_schema()

    def test_failed_migration_rolls_back_without_marking_version(self):
        applied = set()
        conn = FakeConnection(applied)

        def fail(_cur):
            raise RuntimeError("migration failed")

        with patch.object(migrations, "MIGRATIONS", (SimpleNamespace(VERSION="v1", upgrade=fail),)), patch.object(
            migrations, "get_db", return_value=conn
        ):
            with self.assertRaisesRegex(RuntimeError, "migration failed"):
                migrations.upgrade_database()

        self.assertEqual(conn.rollbacks, 1)
        self.assertEqual(conn.commits, 0)
        self.assertEqual(applied, set())

    def test_visibility_legacy_backfill_is_versioned_and_excludes_live_onboarding(self):
        cursor = FakeCursor()

        baseline.apply_legacy_visibility_onboarding_migration(cursor)

        query = cursor.queries[0][0]
        self.assertIn("INSERT INTO schema_migrations", query)
        self.assertIn("2026-09-visibility-onboarding-v1", query)
        self.assertIn("ON CONFLICT (name) DO NOTHING", query)
        self.assertIn("leaderboard_visibility_set = TRUE", query)
        self.assertIn("NOT LIKE 'ONBOARDING_%'", query)

    def test_visibility_legacy_backfill_is_safe_to_run_repeatedly(self):
        cursor = FakeCursor()

        baseline.apply_legacy_visibility_onboarding_migration(cursor)
        baseline.apply_legacy_visibility_onboarding_migration(cursor)

        self.assertEqual(len(cursor.queries), 2)
        for query, _params in cursor.queries:
            self.assertIn("ON CONFLICT (name) DO NOTHING", query)
            self.assertIn("WHERE EXISTS (SELECT 1 FROM applied)", query)


if __name__ == "__main__":
    unittest.main()
