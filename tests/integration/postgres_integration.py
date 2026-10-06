"""Focused PostgreSQL integration coverage; run only against a disposable DB."""

import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date
from unittest.mock import patch
from urllib.parse import urlparse

INTEGRATION_DATABASE_URL = os.getenv("INTEGRATION_DATABASE_URL")
# The integration suite always routes app.db to the explicitly supplied
# disposable database, even if the caller happens to have another DATABASE_URL.
if INTEGRATION_DATABASE_URL:
    os.environ["DATABASE_URL"] = INTEGRATION_DATABASE_URL
else:
    os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from app import db
from app.migrations import require_current_schema, upgrade_database
from app.services import (
    engagement_service,
    incomplete_reminder_service,
    job_queue_service,
    leaderboard_service,
    privacy_service,
    submission_service,
)


def _is_safe_integration_url(url: str | None) -> bool:
    if not url:
        return False
    database_name = urlparse(url).path.rsplit("/", 1)[-1].lower()
    return "test" in database_name or "integration" in database_name


@contextmanager
def cursor():
    with db.get_cursor() as cur:
        yield cur


@unittest.skipUnless(
    _is_safe_integration_url(INTEGRATION_DATABASE_URL),
    "requires an INTEGRATION_DATABASE_URL with a test/integration database name",
)
class PostgreSQLIntegrationTests(unittest.TestCase):
    """Runs against PostgreSQL, never mocks database access."""

    def setUp(self):
        self._reset_public_schema()
        upgrade_database()

    def _reset_public_schema(self):
        conn = db.get_db()
        try:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("DROP SCHEMA public CASCADE")
                cur.execute("CREATE SCHEMA public")
                cur.execute("GRANT ALL ON SCHEMA public TO CURRENT_USER")
        finally:
            conn.close()

    def _insert_member(self, phone: str, first_name="Integration", last_name="Member", **fields):
        columns = ["phone", "first_name", "last_name"] + list(fields)
        values = [phone, first_name, last_name] + list(fields.values())
        placeholders = ", ".join(["%s"] * len(columns))
        with cursor() as cur:
            cur.execute(
                f"INSERT INTO members ({', '.join(columns)}) VALUES ({placeholders}) RETURNING *",
                tuple(values),
            )
            return cur.fetchone()

    def _insert_submission(self, member_id: int, **overrides):
        row = {
            "activity": "TT",
            "distance_text": "4",
            "time_text": "27:41",
            "seconds": 1661,
            "event_date": date.today(),
            "status": "COMPLETE",
            "tt_code_verified": True,
            "confirmed": True,
            "mode": "RUN",
        }
        row.update(overrides)
        columns = ["member_id"] + list(row)
        values = [member_id] + list(row.values())
        with cursor() as cur:
            cur.execute(
                f"INSERT INTO submissions ({', '.join(columns)}) "
                f"VALUES ({', '.join(['%s'] * len(columns))}) RETURNING *",
                tuple(values),
            )
            return cur.fetchone()

    def test_clean_database_migration_creates_schema_constraints_indexes_and_events(self):
        with cursor() as cur:
            cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            tables = {row["tablename"] for row in cur.fetchall()}
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'members'
            """)
            member_columns = {row["column_name"] for row in cur.fetchall()}
            cur.execute("SELECT indexdef FROM pg_indexes WHERE tablename = 'submissions'")
            indexes = "\n".join(row["indexdef"] for row in cur.fetchall())
            cur.execute("SELECT indexdef FROM pg_indexes WHERE tablename = 'job_queue'")
            job_indexes = "\n".join(row["indexdef"] for row in cur.fetchall())
            cur.execute("SELECT event FROM event_config ORDER BY event")
            events = [row["event"] for row in cur.fetchall()]

        self.assertTrue({"members", "submissions", "job_queue", "schema_migrations"} <= tables)
        self.assertTrue({
            "profile_state", "leaderboard_visibility_set", "leaderboard_opt_out",
            "reminders_opt_in", "milestones_opt_in",
        } <= member_columns)
        self.assertIn("idx_submissions_one_pending_per_member_event_date", indexes)
        self.assertIn("idx_job_queue_dedupe_key", job_indexes)
        self.assertIn("WHERE (status = 'PENDING'::text)", indexes)
        self.assertEqual(events, ["SUNSOCIAL", "TT", "WEDLSD"])

    def test_opted_in_reminder_targets_only_unfinished_verified_result(self):
        member = self._insert_member(
            "27999999999", popia_acknowledged=True, reminders_opt_in=True,
        )
        pending = self._insert_submission(
            member["id"], event_date=date(2026, 10, 6), status="PENDING",
            confirmed=False,
        )
        rows = incomplete_reminder_service.get_incomplete_submissions(date(2026, 10, 6))
        self.assertEqual([row["submission_id"] for row in rows], [pending["id"]])
        with cursor() as cur:
            cur.execute("UPDATE submissions SET status = 'COMPLETE' WHERE id = %s", (pending["id"],))
        self.assertEqual(incomplete_reminder_service.get_incomplete_submissions(date(2026, 10, 6)), [])

    def test_attendance_streak_reads_weekly_tt_dates(self):
        member = self._insert_member("27999999999", popia_acknowledged=True)
        with cursor() as cur:
            for event_date in (date(2026, 9, 22), date(2026, 9, 29), date(2026, 10, 6)):
                cur.execute(
                    "INSERT INTO attendance (member_id, event, event_date) VALUES (%s, 'TT', %s)",
                    (member["id"], event_date),
                )
        stats = engagement_service.get_attendance_stats(member["id"], today=date(2026, 10, 6))
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["current_streak"], 3)

    def test_confirmed_erasure_removes_member_and_related_active_data(self):
        target = self._insert_member("27999999999", popia_acknowledged=True)
        other = self._insert_member("27888888888", popia_acknowledged=True)
        own_result = self._insert_submission(target["id"])
        other_result = self._insert_submission(other["id"])
        with cursor() as cur:
            cur.execute(
                "INSERT INTO attendance (member_id, event, event_date) VALUES (%s, 'TT', %s)",
                (target["id"], date.today()),
            )
            cur.execute(
                "INSERT INTO member_self_corrections (member_id, submission_id, mode) VALUES (%s, %s, 'RUN')",
                (target["id"], own_result["id"]),
            )
            cur.execute(
                "INSERT INTO admin_corrections (member_id, submission_id, admin_member_id) VALUES (%s, %s, %s)",
                (target["id"], own_result["id"], target["id"]),
            )
            cur.execute(
                "INSERT INTO admin_corrections (member_id, submission_id, admin_member_id) VALUES (%s, %s, %s)",
                (other["id"], other_result["id"], target["id"]),
            )
            cur.execute(
                "INSERT INTO inbound_whatsapp_messages (message_id, sender) VALUES ('erase-test', %s)",
                (target["phone"],),
            )
            cur.execute(
                "INSERT INTO job_queue (job_type, payload) VALUES ('whatsapp_send', %s::jsonb)",
                ('{"payload": {"to": "27999999999", "type": "text"}}',),
            )

        self.assertTrue(privacy_service.withdraw_consent_and_request_erasure(target["phone"]))
        self.assertTrue(privacy_service.erase_member_after_confirmation(target["phone"]))
        with cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM members WHERE id = %s", (target["id"],))
            self.assertEqual(cur.fetchone()["n"], 0)
            cur.execute("SELECT COUNT(*) AS n FROM submissions WHERE member_id = %s", (target["id"],))
            self.assertEqual(cur.fetchone()["n"], 0)
            cur.execute("SELECT COUNT(*) AS n FROM job_queue")
            self.assertEqual(cur.fetchone()["n"], 0)
            cur.execute("SELECT COUNT(*) AS n FROM inbound_whatsapp_messages WHERE sender = %s", (target["phone"],))
            self.assertEqual(cur.fetchone()["n"], 0)
            cur.execute("SELECT sender FROM inbound_whatsapp_messages WHERE message_id = 'erase-test'")
            self.assertIsNone(cur.fetchone()["sender"])
            cur.execute("SELECT admin_member_id FROM admin_corrections WHERE member_id = %s", (other["id"],))
            self.assertIsNone(cur.fetchone()["admin_member_id"])
            cur.execute("SELECT COUNT(*) AS n FROM members WHERE id = %s", (other["id"],))
            self.assertEqual(cur.fetchone()["n"], 1)

    def test_populated_legacy_migration_preserves_data_and_does_not_reclassify_onboarding(self):
        self._reset_public_schema()
        conn = db.get_db()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE members (
                        id SERIAL PRIMARY KEY, phone TEXT UNIQUE NOT NULL,
                        first_name TEXT NOT NULL, last_name TEXT NOT NULL,
                        profile_state TEXT, leaderboard_opt_out BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cur.execute("""
                    CREATE TABLE submissions (
                        id SERIAL PRIMARY KEY, member_id INTEGER NOT NULL REFERENCES members(id),
                        activity TEXT NOT NULL, distance_text TEXT, time_text TEXT NOT NULL,
                        seconds INTEGER NOT NULL, status TEXT DEFAULT 'PENDING',
                        tt_code_verified BOOLEAN DEFAULT FALSE, confirmed BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cur.execute("INSERT INTO members (phone, first_name, last_name) VALUES ('27001', 'Legacy', 'Public')")
                cur.execute("INSERT INTO members (phone, first_name, last_name, leaderboard_opt_out) VALUES ('27002', 'Legacy', 'Private', TRUE)")
                cur.execute("""
                    INSERT INTO members (phone, first_name, last_name, profile_state)
                    VALUES ('27003', 'New', 'Interrupted', 'ONBOARDING_LEADERBOARD')
                """)
                cur.execute("INSERT INTO submissions (member_id, activity, distance_text, time_text, seconds, status, tt_code_verified, confirmed) VALUES (1, 'TT', '8', '43:21', 2601, 'COMPLETE', TRUE, TRUE)")
                cur.execute("INSERT INTO submissions (member_id, activity, distance_text, time_text, seconds, status, tt_code_verified, confirmed) VALUES (2, 'TT', NULL, '45 min walk', 0, 'COMPLETE', TRUE, TRUE)")
                cur.execute("INSERT INTO submissions (member_id, activity, distance_text, time_text, seconds) VALUES (1, 'TT', NULL, '', 0)")
                cur.execute("INSERT INTO submissions (member_id, activity, distance_text, time_text, seconds) VALUES (1, 'TT', '4', '28:00', 1680)")
            conn.commit()
        finally:
            conn.close()

        upgrade_database()

        with cursor() as cur:
            cur.execute("SELECT phone, participation_type, leaderboard_opt_out, leaderboard_visibility_set FROM members ORDER BY phone")
            members = {row["phone"]: row for row in cur.fetchall()}
            cur.execute("SELECT distance_text, time_text, mode, event_date, status FROM submissions ORDER BY id")
            submissions = cur.fetchall()

        self.assertTrue(members["27001"]["leaderboard_visibility_set"])
        self.assertFalse(members["27001"]["leaderboard_opt_out"])
        self.assertTrue(members["27002"]["leaderboard_visibility_set"])
        self.assertTrue(members["27002"]["leaderboard_opt_out"])
        self.assertFalse(members["27003"]["leaderboard_visibility_set"])
        self.assertIsNone(members["27003"]["participation_type"])
        self.assertEqual(submissions[0]["mode"], "RUN")
        self.assertEqual(submissions[1]["mode"], "WORKOUT")
        self.assertTrue(all(row["event_date"] for row in submissions))
        self.assertEqual(sum(row["status"] == "PENDING" for row in submissions), 1)

    def test_pending_submission_uniqueness_holds_under_concurrent_creation(self):
        member = self._insert_member("27101")
        with ThreadPoolExecutor(max_workers=2) as pool:
            rows = list(pool.map(lambda _unused: submission_service.get_or_create_submission(member["id"]), range(2)))

        self.assertEqual({row["id"] for row in rows}, {rows[0]["id"]})
        with cursor() as cur:
            cur.execute("SELECT COUNT(*) AS count FROM submissions WHERE member_id = %s AND status = 'PENDING'", (member["id"],))
            self.assertEqual(cur.fetchone()["count"], 1)

    def test_queue_claim_uses_postgresql_skip_locked_across_two_workers(self):
        job_id = job_queue_service.enqueue_job("integration", {"kind": "claim"})
        claimed_by_a = job_queue_service._claim_next_job()
        claimed_by_b = job_queue_service._claim_next_job()

        self.assertEqual(claimed_by_a["id"], job_id)
        self.assertIsNone(claimed_by_b)

    def test_manual_retry_reenters_claim_and_done_lifecycle(self):
        job_id = job_queue_service.enqueue_job("integration", {"kind": "retry"}, max_attempts=3)
        with cursor() as cur:
            cur.execute("""
                UPDATE job_queue SET status = 'FAILED', attempts = max_attempts,
                    last_error = 'test failure' WHERE id = %s
            """, (job_id,))

        self.assertEqual(job_queue_service.retry_failed_jobs(), 1)
        claimed = job_queue_service._claim_next_job()
        self.assertEqual(claimed["id"], job_id)
        self.assertEqual(claimed["attempts"], 1)
        with patch.object(job_queue_service, "_dispatch_job"):
            job_queue_service._run_job(claimed)
        with cursor() as cur:
            cur.execute("SELECT status FROM job_queue WHERE id = %s", (job_id,))
            self.assertEqual(cur.fetchone()["status"], "DONE")

    def test_outbound_dedupe_key_returns_one_job_on_repeated_enqueue(self):
        payload = {"messaging_product": "whatsapp", "to": "2771", "type": "text", "text": {"body": "Hi"}}
        first = job_queue_service.enqueue_whatsapp_send(payload, dedupe_key="outbound:wamid.1:0")
        second = job_queue_service.enqueue_whatsapp_send(payload, dedupe_key="outbound:wamid.1:0")
        self.assertEqual(first, second)
        with cursor() as cur:
            cur.execute("SELECT COUNT(*) AS count FROM job_queue WHERE dedupe_key = %s", ("outbound:wamid.1:0",))
            self.assertEqual(cur.fetchone()["count"], 1)

    def test_confirmation_rolls_back_if_followup_cannot_be_queued(self):
        member = self._insert_member("27106")
        submission = self._insert_submission(member["id"], status="PENDING", confirmed=False)
        followup = {"sender": member["phone"], "member": member, "previous_best": None}

        with patch.object(submission_service, "enqueue_post_confirm_messages", side_effect=RuntimeError("queue unavailable")):
            with self.assertRaisesRegex(RuntimeError, "queue unavailable"):
                submission_service.confirm_submission(submission["id"], followup=followup)

        with cursor() as cur:
            cur.execute("SELECT status, confirmed FROM submissions WHERE id = %s", (submission["id"],))
            saved = cur.fetchone()
        self.assertEqual(saved["status"], "PENDING")
        self.assertFalse(saved["confirmed"])

    def test_concurrent_confirmation_is_idempotent(self):
        member = self._insert_member("27102")
        submission = self._insert_submission(member["id"], status="PENDING", confirmed=False)
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _unused: submission_service.confirm_submission(submission["id"]), range(2)))

        self.assertEqual(sum(row is not None for row in outcomes), 1)
        with cursor() as cur:
            cur.execute("SELECT status, confirmed, distance_text, time_text, seconds FROM submissions WHERE id = %s", (submission["id"],))
            saved = cur.fetchone()
        self.assertEqual(saved["status"], "COMPLETE")
        self.assertTrue(saved["confirmed"])
        self.assertEqual((saved["distance_text"], saved["time_text"], saved["seconds"]), ("4", "27:41", 1661))

    def test_incomplete_onboarding_is_non_public_after_repeated_startup(self):
        public_member = self._insert_member("27103", leaderboard_visibility_set=True, leaderboard_opt_out=False)
        incomplete_member = self._insert_member(
            "27104", first_name="New", last_name="Interrupted",
            profile_state="ONBOARDING_LEADERBOARD", leaderboard_visibility_set=False,
        )
        private_member = self._insert_member("27105", leaderboard_visibility_set=True, leaderboard_opt_out=True)
        for member in (public_member, incomplete_member, private_member):
            self._insert_submission(member["id"])

        self.assertEqual(upgrade_database(), [])
        require_current_schema()
        rows = leaderboard_service.get_runner_leaderboard(date.today())
        self.assertEqual([row["member_id"] for row in rows], [public_member["id"]])
        with cursor() as cur:
            cur.execute("SELECT leaderboard_visibility_set FROM members WHERE id = %s", (incomplete_member["id"],))
            self.assertFalse(cur.fetchone()["leaderboard_visibility_set"])


if __name__ == "__main__":
    unittest.main()
