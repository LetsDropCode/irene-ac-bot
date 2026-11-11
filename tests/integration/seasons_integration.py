"""Real PostgreSQL regression coverage for calendar-year views and history."""

import unittest
from datetime import date, datetime
from unittest.mock import patch

import postgres_integration as fixtures
from app import webhook
from app.services import season_service as seasons
from app.services import leaderboard_service, profile_service, pb_service, engagement_service
from app.migrations import upgrade_database
from app.migrations.versions import v20261111_season_welcome


@unittest.skipUnless(fixtures._is_safe_integration_url(fixtures.INTEGRATION_DATABASE_URL),
                     "requires a disposable integration database")
class SeasonIntegrationTests(unittest.TestCase):
    setUp = fixtures.PostgreSQLIntegrationTests.setUp
    _reset_public_schema = fixtures.PostgreSQLIntegrationTests._reset_public_schema
    _insert_member = fixtures.PostgreSQLIntegrationTests._insert_member
    _insert_submission = fixtures.PostgreSQLIntegrationTests._insert_submission

    def checkin(self, member_id, day):
        with fixtures.cursor() as cur:
            cur.execute("INSERT INTO attendance (member_id, event, event_date) VALUES (%s, 'TT', %s)",
                        (member_id, day))

    def test_rollover_and_backdated_results_preserve_history_and_all_time_pbs(self):
        member = self._insert_member("27700000001", participation_type="RUNNER",
                                     popia_acknowledged=True, leaderboard_visibility_set=True)
        mid = member["id"]
        old = self._insert_submission(mid, event_date=date(2026, 12, 29), seconds=1200, time_text="20:00")
        self.checkin(mid, date(2026, 12, 29))
        with patch.object(seasons, "current_season", return_value=2026):
            self.assertEqual(seasons.get_season_summary(mid)["total"], 1)
        with patch.object(seasons, "current_season", return_value=2027):
            fresh = seasons.get_season_summary(mid)
            self.assertEqual((fresh["total"], fresh["attendance"], fresh["pbs"]), (0, 0, []))
            self.assertEqual(leaderboard_service.get_overall_leaderboard(mid, year=2027), [])
            self.assertEqual(profile_service.get_user_profile(mid)["pbs"][0]["best_seconds"], 1200)

        self._insert_submission(mid, event_date=date(2027, 1, 5), seconds=1300, time_text="21:40")
        self.checkin(mid, date(2027, 1, 5))
        # A result inserted during a later year belongs to its event's year.
        backdated = self._insert_submission(mid, event_date=date(2026, 12, 22),
                                           created_at=datetime(2027, 1, 7), seconds=1100, time_text="18:20")
        self.assertEqual(seasons.get_season_summary(mid, 2026)["pbs"][0]["best_seconds"], 1100)
        self.assertEqual(seasons.get_season_summary(mid, 2027)["pbs"][0]["best_seconds"], 1300)
        self.assertEqual(pb_service.get_previous_best(mid, "4"), 1100)
        self.assertEqual(leaderboard_service.get_overall_leaderboard(mid)[0]["best_seconds"], 1100)
        self.assertEqual(leaderboard_service.get_overall_leaderboard(mid, year=2027)[0]["best_seconds"], 1300)
        rows, more = seasons.get_member_history(mid, 2026)
        self.assertFalse(more)
        self.assertEqual([row["id"] for row in rows], [old["id"], backdated["id"]])
        self.assertEqual(seasons.get_member_seasons(mid), [2027, 2026])
        self.assertEqual(engagement_service.get_attendance_stats(mid, today=date(2027, 1, 5))["current_streak"], 2)
        with fixtures.cursor() as cur:
            cur.execute("SELECT * FROM submissions ORDER BY id")
            before = cur.fetchall()
        self.assertEqual(upgrade_database(), [])
        with fixtures.cursor() as cur:
            cur.execute("SELECT * FROM submissions ORDER BY id")
            self.assertEqual(cur.fetchall(), before)

    def test_private_history_does_not_leak_other_members_and_pages_all_activity_types(self):
        private = self._insert_member("27700000002", popia_acknowledged=True,
                                      leaderboard_visibility_set=True, leaderboard_opt_out=True)
        other = self._insert_member("27700000003", leaderboard_visibility_set=True)
        mid = private["id"]
        own_ids = []
        for day in range(1, 10):
            own_ids.append(self._insert_submission(mid, event_date=date(2026, 9, day))["id"])
        workout = self._insert_submission(mid, event_date=date(2026, 10, 6), mode=None,
                                          distance_text=None, seconds=0, time_text="45 minute walk")
        own_ids.append(workout["id"])
        self.checkin(mid, date(2026, 10, 6))  # Does not duplicate the workout.
        self.checkin(mid, date(2025, 12, 30))  # Attendance-only historical season.
        self.checkin(mid, date(2026, 10, 13))
        self._insert_submission(mid, event_date=date(2026, 10, 13), status="PENDING", confirmed=False)
        self._insert_submission(mid, event_date=date(2026, 10, 20), activity="SUNSOCIAL")
        foreign = self._insert_submission(other["id"], event_date=date(2026, 11, 3), seconds=900)
        first, more = seasons.get_member_history(mid, 2026)
        self.assertTrue(more)
        second, more = seasons.get_member_history(mid, 2026, 2)
        self.assertFalse(more)
        self.assertEqual(len(first + second), 11)
        self.assertEqual({r["id"] for r in first + second if r["id"]}, set(own_ids))
        self.assertNotIn(foreign["id"], [r["id"] for r in first + second])
        self.assertIsNone(first[0]["id"])
        self.assertEqual(seasons.get_member_seasons(mid), [2026, 2025])
        summary = seasons.get_season_summary(mid, 2026)
        self.assertEqual((summary["total"], summary["walks"], summary["attendance"]), (10, 1, 2))
        self.assertNotIn(mid, [r["member_id"] for r in leaderboard_service.get_overall_leaderboard(mid, year=2026)])
        self.assertTrue(profile_service.get_user_profile(mid)["pbs"])

    def test_new_migration_is_additive_and_season_welcome_is_persistent(self):
        member = self._insert_member("27700000004", participation_type="RUNNER", popia_acknowledged=True,
                                    leaderboard_visibility_set=True)
        self._insert_submission(member["id"], event_date=date(2026, 12, 29))
        with fixtures.cursor() as cur:
            cur.execute("ALTER TABLE members DROP COLUMN last_seen_season")
            cur.execute("DELETE FROM schema_migrations WHERE name = %s", (v20261111_season_welcome.VERSION,))
        self.assertEqual(upgrade_database(), [v20261111_season_welcome.VERSION])
        with patch.object(webhook, "current_season", return_value=2027), patch.object(webhook, "send_text", return_value=True) as send:
            self.assertTrue(webhook.send_season_welcome_once(member["phone"], member))
            reloaded = webhook.get_member(member["phone"])
            self.assertFalse(webhook.send_season_welcome_once(member["phone"], reloaded))
            send.assert_called_once()
        self.assertEqual(profile_service.get_user_profile(member["id"])["total_runs"], 1)
        self.assertEqual(seasons.get_season_summary(member["id"], 2027)["total"], 0)
