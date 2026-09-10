import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from app import db


class FakeCursor:
    def __init__(self):
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((query, params))


class DatabaseMigrationTests(unittest.TestCase):
    def test_visibility_legacy_backfill_is_versioned_and_excludes_live_onboarding(self):
        cursor = FakeCursor()

        db.apply_legacy_visibility_onboarding_migration(cursor)

        query = cursor.queries[0][0]
        self.assertIn("INSERT INTO schema_migrations", query)
        self.assertIn("2026-09-visibility-onboarding-v1", query)
        self.assertIn("ON CONFLICT (name) DO NOTHING", query)
        self.assertIn("leaderboard_visibility_set = TRUE", query)
        self.assertIn("NOT LIKE 'ONBOARDING_%'", query)

    def test_visibility_legacy_backfill_is_safe_to_run_repeatedly(self):
        cursor = FakeCursor()

        db.apply_legacy_visibility_onboarding_migration(cursor)
        db.apply_legacy_visibility_onboarding_migration(cursor)

        self.assertEqual(len(cursor.queries), 2)
        for query, _params in cursor.queries:
            self.assertIn("ON CONFLICT (name) DO NOTHING", query)
            self.assertIn("WHERE EXISTS (SELECT 1 FROM applied)", query)


if __name__ == "__main__":
    unittest.main()
