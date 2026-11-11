"""Real database coverage for monthly counts, privacy, scheduling and admin views."""

import os
import unittest
from datetime import date, datetime
from unittest.mock import patch

import postgres_integration as fixtures
from app.migrations import upgrade_database
from app.services import monthly_engagement_service as monthly
from app.services import engagement_service, privacy_service, tt_status_service


@unittest.skipUnless(fixtures._is_safe_integration_url(fixtures.INTEGRATION_DATABASE_URL),
                     "requires a disposable integration database")
class MonthlyEngagementIntegrationTests(unittest.TestCase):
    setUp = fixtures.PostgreSQLIntegrationTests.setUp
    _reset_public_schema = fixtures.PostgreSQLIntegrationTests._reset_public_schema
    _insert_member = fixtures.PostgreSQLIntegrationTests._insert_member
    _insert_submission = fixtures.PostgreSQLIntegrationTests._insert_submission

    def checkin(self, mid, day, event="TT"):
        with fixtures.cursor() as cur:
            cur.execute("INSERT INTO attendance (member_id, event, event_date) VALUES (%s, %s, %s)",
                        (mid, event, day))

    def test_monthly_goal_and_recap_count_attendance_separately_from_results(self):
        member = self._insert_member("27700000001", popia_acknowledged=True, leaderboard_opt_out=True)
        mid = member["id"]
        for day in (date(2026, 9, 29), date(2026, 10, 6), date(2026, 10, 20), date(2026, 10, 27), date(2026, 11, 3)):
            self.checkin(mid, day)
        self.checkin(mid, date(2026, 10, 7), "WEDLSD")
        self._insert_submission(mid, event_date=date(2026, 9, 29), seconds=1618)
        self._insert_submission(mid, event_date=date(2026, 10, 6), seconds=1600)
        self._insert_submission(mid, event_date=date(2026, 10, 20), mode="WORKOUT", distance_text=None, seconds=0,
                                time_text="45 minute walk")
        self._insert_submission(mid, event_date=date(2026, 10, 27), status="PENDING", confirmed=False, seconds=1000)
        self._insert_submission(mid, event_date=date(2026, 11, 3), seconds=1500)
        self._insert_submission(mid, event_date=date(2026, 10, 7), activity="WEDLSD", seconds=900)
        other = self._insert_member("27700000002")
        self.checkin(other["id"], date(2026, 10, 6))
        self._insert_submission(other["id"], event_date=date(2026, 10, 6), seconds=800)
        # Missing a week preserves the goal. Future check-ins don't count yet.
        self.assertEqual(monthly.get_monthly_goal(mid, date(2026, 10, 20))["attendance"], 2)
        self.assertEqual(monthly.get_monthly_goal(mid, date(2026, 10, 31))["attendance"], 3)
        self.assertEqual(monthly.get_monthly_goal(mid, date(2026, 11, 1))["attendance"], 0)
        recap = monthly.get_monthly_recap(mid, date(2026, 10, 1))
        self.assertEqual((recap["attendance"], recap["activities"], recap["distance_km"]), (3, 2, 4))
        self.assertEqual(recap["bests"][0]["previous_seconds"], 1618)
        self.assertIn("improved by 0:18", monthly.format_monthly_recap(recap))
        self.assertEqual(upgrade_database(), [])
        self.assertFalse(member["recaps_opt_in"])

    def test_queue_dedupes_and_opt_out_or_erasure_prevents_delivery(self):
        member = self._insert_member("27700000001", popia_acknowledged=True, recaps_opt_in=True,
                                     leaderboard_opt_out=True)
        mid = member["id"]
        self.checkin(mid, date(2026, 10, 6))
        for index, fields in enumerate(({"popia_acknowledged": True},
                                       {"popia_acknowledged": False, "recaps_opt_in": True}), 2):
            other = self._insert_member(f"2770000000{index}", **fields)
            self.checkin(other["id"], date(2026, 10, 6))
        self._insert_member("27700000004", popia_acknowledged=True, recaps_opt_in=True)  # inactive
        now = datetime(2026, 11, 1, 14)
        with patch.dict(os.environ, {"WHATSAPP_MONTHLY_RECAP_TEMPLATE_NAME": "monthly"}), patch(
            "app.whatsapp._send_direct", return_value=True
        ) as send:
            self.assertEqual(monthly.queue_monthly_recaps(now)["queued"], 1)
            self.assertEqual(monthly.queue_monthly_recaps(now)["queued"], 0)
            with fixtures.cursor() as cur:
                cur.execute("SELECT payload FROM job_queue WHERE job_type = 'monthly_recap'")
                jobs = cur.fetchall()
            self.assertEqual(len(jobs), 1)
            payload = jobs[0]["payload"]
            self.assertTrue(engagement_service.set_engagement_preference(mid, "recaps", False))
            self.assertFalse(monthly.send_monthly_recap(payload, now))
            send.assert_not_called()
            with fixtures.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS n FROM job_queue")
                self.assertEqual(cur.fetchone()["n"], 0)
            self.assertTrue(engagement_service.set_engagement_preference(mid, "recaps", True))
            self.assertEqual(monthly.queue_monthly_recaps(now)["queued"], 1)
            self.assertTrue(monthly.send_monthly_recap(payload, now))
            send.assert_called_once()
            self.assertTrue(privacy_service.withdraw_consent_and_request_erasure(member["phone"]))
            self.assertFalse(monthly.send_monthly_recap(payload, now))
            with fixtures.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS n FROM job_queue")
                self.assertEqual(cur.fetchone()["n"], 0)

    def test_admin_summary_includes_walks_missing_results_and_bounded_lists(self):
        day = date(2026, 11, 17)
        experienced = self._insert_member("27700000001", popia_acknowledged=True, participation_type="WALKER")
        mid = experienced["id"]
        for previous in (date(2026, 10, 20), date(2026, 10, 27), date(2026, 11, 3), date(2026, 11, 10), day):
            self.checkin(mid, previous)
        self._insert_submission(mid, event_date=day, mode="WORKOUT", distance_text=None, seconds=0, time_text="Walk")
        for index in range(2, 9):
            member = self._insert_member(f"2770000000{index}", popia_acknowledged=True, participation_type="RUNNER")
            self.checkin(member["id"], day)
            self._insert_submission(member["id"], event_date=day, status="PENDING", confirmed=False)
        # An unverified draft without attendance and a withdrawn member are excluded.
        draft = self._insert_member("27700000010", popia_acknowledged=True)
        self._insert_submission(draft["id"], event_date=day, status="PENDING", confirmed=False, tt_code_verified=False)
        withdrawn = self._insert_member("27700000011", popia_acknowledged=False)
        self.checkin(withdrawn["id"], day)
        result = tt_status_service.get_event_summary(day)
        summary = result["summary"]
        self.assertEqual((summary["checked_in"], summary["submitted"], summary["pending"]), (8, 1, 7))
        self.assertEqual(summary["walkers"], 1)
        self.assertEqual(summary["first_timers"], 7)
        self.assertEqual(summary["monthly_goals_reached"], 1)
        self.assertEqual(result["milestones"][0]["total"], 5)
        self.assertEqual(len(result["pending"]), 5)
        self.assertIn("(+2 more)", tt_status_service.format_event_summary(result))
        self.assertLess(len(tt_status_service.format_event_summary(result)), 2000)
