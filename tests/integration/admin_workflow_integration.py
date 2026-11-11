"""Exercise result-version guards and admin follow-up against PostgreSQL."""

import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from unittest.mock import patch

import postgres_integration as fixtures
from app.services import admin_workflow_service as service, admin_service
from app.services import monthly_email_schedule_service as email
from app.migrations import upgrade_database

ADMIN = "27700000001"


@unittest.skipUnless(fixtures._is_safe_integration_url(fixtures.INTEGRATION_DATABASE_URL),
                     "requires a disposable integration database")
class AdminWorkflowIntegrationTests(unittest.TestCase):
    setUp = fixtures.PostgreSQLIntegrationTests.setUp
    _reset_public_schema = fixtures.PostgreSQLIntegrationTests._reset_public_schema
    _insert_member = fixtures.PostgreSQLIntegrationTests._insert_member
    _insert_submission = fixtures.PostgreSQLIntegrationTests._insert_submission

    def users(self):
        return (self._insert_member(ADMIN, popia_acknowledged=True),
                self._insert_member("27700000002", popia_acknowledged=True, participation_type="WALKER"))

    def checkin(self, mid, day):
        with fixtures.cursor() as cur:
            cur.execute("INSERT INTO attendance (member_id, event, event_date) VALUES (%s, 'TT', %s)", (mid, day))

    def latest_change(self, sid):
        with fixtures.cursor() as cur:
            cur.execute("SELECT * FROM admin_corrections WHERE submission_id = %s ORDER BY id DESC LIMIT 1", (sid,))
            return cur.fetchone()

    def result(self, sid):
        with fixtures.cursor() as cur:
            cur.execute("SELECT * FROM submissions WHERE id = %s", (sid,))
            return cur.fetchone()

    def test_undo_restores_full_walker_state_and_is_one_time(self):
        admin, member = self.users()
        original = self._insert_submission(member["id"], event_date=date(2026, 11, 10), mode="WORKOUT",
                                           distance_text=None, time_text="Easy walk", seconds=0, confirmed=False)
        admin_service.correct_submission_by_id(original["id"], "4", "24:00", 1440, admin["id"])
        change = self.latest_change(original["id"])
        self.assertEqual(change["before_state"]["mode"], "WORKOUT")
        self.assertEqual(change["after_revision"], 1)
        with patch.object(service.config, "ADMIN_NUMBERS", frozenset({ADMIN})):
            self.assertTrue(service.undo_correction(ADMIN, change["id"])[0])
            self.assertFalse(service.undo_correction(ADMIN, change["id"])[0])
        restored = self.result(original["id"])
        for key in ("distance_text", "time_text", "seconds", "mode", "status", "confirmed"):
            self.assertEqual(restored[key], original[key], key)
        self.assertEqual(restored["revision"], 2)
        self.assertEqual(self.latest_change(original["id"])["reason"], f"undo:{change['id']}")
        self.assertEqual(upgrade_database(), [])

    def test_later_change_even_back_to_same_values_prevents_undo(self):
        admin, member = self.users()
        original = self._insert_submission(member["id"])
        admin_service.correct_submission_time_by_id(original["id"], "24:00", 1440, admin["id"])
        change = self.latest_change(original["id"])
        with fixtures.cursor() as cur:
            cur.execute("UPDATE submissions SET seconds = 1400 WHERE id = %s", (original["id"],))
            cur.execute("UPDATE submissions SET seconds = 1440 WHERE id = %s", (original["id"],))
        with patch.object(service.config, "ADMIN_NUMBERS", frozenset({ADMIN})):
            self.assertFalse(service.undo_correction(ADMIN, change["id"])[0])
        self.assertEqual(self.result(original["id"])["seconds"], 1440)

    def test_two_concurrent_undo_confirmations_only_restore_once(self):
        admin, member = self.users()
        original = self._insert_submission(member["id"])
        admin_service.correct_submission_by_id(original["id"], "4", "24:00", 1440, admin["id"])
        change = self.latest_change(original["id"])
        with patch.object(service.config, "ADMIN_NUMBERS", frozenset({ADMIN})), ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: service.undo_correction(ADMIN, change["id"])[0], range(2)))
        self.assertEqual(sorted(outcomes), [False, True])
        self.assertEqual(self.result(original["id"])["revision"], 2)

    def test_all_correction_paths_record_snapshots_and_legacy_audit_is_read_only(self):
        admin, member = self.users()
        with fixtures.cursor() as cur:
            cur.execute("SELECT (CURRENT_TIMESTAMP AT TIME ZONE 'Africa/Johannesburg')::date AS day")
            day = cur.fetchone()["day"]
        original = self._insert_submission(member["id"], event_date=day)
        for update in (
            lambda: admin_service.correct_runner_time(str(member["id"]), "4", "25:00", 1500, admin["id"]),
            lambda: admin_service.correct_runner_time_on_date(str(member["id"]), day.isoformat(), "4", "26:00", 1560, admin["id"]),
            lambda: admin_service.correct_runner_pb(str(member["id"]), "4", "27:00", 1620, admin["id"]),
        ):
            before = self.result(original["id"])
            self.assertIsNotNone(update())
            audit = self.latest_change(original["id"])
            self.assertEqual(audit["before_state"]["seconds"], before["seconds"])
            self.assertEqual(audit["after_revision"], before["revision"] + 1)
        with fixtures.cursor() as cur:
            cur.execute("UPDATE admin_corrections SET before_state = NULL WHERE id = %s", (audit["id"],))
        with patch.object(service.config, "ADMIN_NUMBERS", frozenset({ADMIN})):
            self.assertFalse(service.undo_correction(ADMIN, audit["id"])[0])

    def test_undo_does_not_overwrite_new_pending_or_withdrawn_member(self):
        admin, member = self.users()
        original = self._insert_submission(member["id"], status="PENDING", confirmed=False)
        admin_service.correct_submission_by_id(original["id"], "4", "24:00", 1440, admin["id"])
        change = self.latest_change(original["id"])
        newer = self._insert_submission(member["id"], status="PENDING", confirmed=False)
        with patch.object(service.config, "ADMIN_NUMBERS", frozenset({ADMIN})):
            self.assertFalse(service.undo_correction(ADMIN, change["id"])[0])
            with fixtures.cursor() as cur:
                cur.execute("UPDATE submissions SET status = 'CANCELLED' WHERE id = %s", (newer["id"],))
                cur.execute("UPDATE members SET popia_acknowledged = FALSE WHERE id = %s", (member["id"],))
            self.assertFalse(service.undo_correction(ADMIN, change["id"])[0])

    def test_pending_page_includes_missing_entries_and_excludes_completed_or_private_consent(self):
        admin, member = self.users()
        day = date(2026, 11, 10)
        self.checkin(member["id"], day)
        self._insert_submission(member["id"], event_date=day, mode="WORKOUT", distance_text=None,
                                time_text="Walk", seconds=0, status="PENDING", confirmed=False)
        missing = self._insert_member("27700000003", popia_acknowledged=True, leaderboard_opt_out=True)
        self.checkin(missing["id"], day)
        finished = self._insert_member("27700000004", popia_acknowledged=True)
        self.checkin(finished["id"], day)
        self._insert_submission(finished["id"], event_date=day)
        withdrawn = self._insert_member("27700000005", popia_acknowledged=False)
        self.checkin(withdrawn["id"], day)
        with patch.object(service.config, "ADMIN_NUMBERS", frozenset({ADMIN})):
            rows, more = service.pending_members(ADMIN, day)
            self.assertFalse(more)
            self.assertEqual({r["id"] for r in rows}, {member["id"], missing["id"]})
            self.assertEqual(service.pending_stage(rows[0]), "Awaiting workout confirmation")
            single, _ = service.pending_members(ADMIN, day, member_id=missing["id"])
            self.assertEqual(service.pending_stage(single[0]), "No result entry started")

    def test_prompt_dedupes_and_rechecks_completed_result_at_delivery(self):
        admin, member = self.users()
        day = date(2026, 11, 10)
        now = datetime(2026, 11, 10, 18, tzinfo=service.SA_TZ)
        self.checkin(member["id"], day)
        result = self._insert_submission(member["id"], event_date=day, status="PENDING", confirmed=False)
        with fixtures.cursor() as cur:
            cur.execute("INSERT INTO inbound_whatsapp_messages (message_id, sender, status, received_at) VALUES ('prompt-test', %s, 'PROCESSED', %s)",
                        (member["phone"], datetime(2026, 11, 10, 15, 55)))
        with patch.object(service.config, "ADMIN_NUMBERS", frozenset({ADMIN})), patch.object(service, "datetime") as clock, patch(
            "app.whatsapp._send_direct", return_value=True
        ) as send:
            clock.now.return_value = now
            self.assertTrue(service.queue_member_prompt(ADMIN, member["id"], day)[0])
            self.assertFalse(service.queue_member_prompt(ADMIN, member["id"], day)[0])
            payload = {"member_id": member["id"], "event_date": day.isoformat()}
            self.assertTrue(service.deliver_member_prompt(payload))
            self.assertIn("Reply RESUME", send.call_args.args[0]["text"]["body"])
            with fixtures.cursor() as cur:
                cur.execute("UPDATE submissions SET status = 'COMPLETE' WHERE id = %s", (result["id"],))
            self.assertFalse(service.deliver_member_prompt(payload))
            send.assert_called_once()

    def test_monthly_email_is_deduped_and_uses_previous_calendar_month(self):
        with patch.object(email, "email_schedule_ready", return_value=True):
            self.assertEqual(email.queue_monthly_attendance_email(datetime(2027, 1, 1, 14)), {"queued": 1})
            self.assertEqual(email.queue_monthly_attendance_email(datetime(2027, 1, 2, 14)), {"queued": 0})
        with fixtures.cursor() as cur:
            cur.execute("SELECT payload, dedupe_key FROM job_queue WHERE job_type = 'monthly_attendance_email'")
            jobs = cur.fetchall()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["payload"]["report_date"], "2026-12-31")
        self.assertEqual(jobs[0]["dedupe_key"], "monthly-attendance-email:2026-12-31")
