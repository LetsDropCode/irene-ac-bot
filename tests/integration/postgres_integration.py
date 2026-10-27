"""Focused PostgreSQL integration coverage; run only against a disposable DB."""

import json
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

from app import db, config
from app.migrations import require_current_schema, upgrade_database
from app.migrations.versions import v20261027_submission_mode_default
from app.flows.submission_dispatch import handle_submission_message
from app.flows.webhook_dispatch import route_message
from app.flows import admin_submission_flow
from app.flows.submission_state import resolve_pending_submission_state
from app import webhook
from app.services import (
    admin_submission_service,
    engagement_service,
    incomplete_reminder_service,
    job_queue_service,
    leaderboard_service,
    profile_service,
    monthly_attendance_report_service,
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

    def test_legacy_run_default_does_not_block_walker_or_both_free_text(self):
        with cursor() as cur:
            cur.execute("ALTER TABLE submissions ALTER COLUMN mode SET DEFAULT 'RUN'")

        for index, (participation, expected) in enumerate((
            ("WALKER", "awaiting_workout"),
            ("BOTH", "awaiting_both_choice"),
            ("RUNNER", "awaiting_distance"),
        )):
            with self.subTest(participation=participation):
                member = self._insert_member(f"27800{index}", participation_type=participation)
                row = submission_service.get_or_create_submission(member["id"])
                self.assertIsNone(row["mode"])
                self.assertEqual(resolve_pending_submission_state(member, row), expected)
                if participation == "RUNNER":
                    continue

                with cursor() as cur:
                    cur.execute("UPDATE submissions SET tt_code_verified = TRUE WHERE id = %s", (row["id"],))
                note = "Pyramid walk, 5.54km, 41:35"
                with patch.object(webhook, "ensure_tt_open", return_value=(True, None)), patch.object(
                    webhook, "send_workout_confirm_buttons"
                ) as review, patch.object(webhook, "send_text"), patch.object(
                    webhook, "send_distance_buttons"
                ) as distances:
                    if participation == "BOTH":
                        result = handle_submission_message(
                            webhook, member["phone"], None, None,
                            {"id": "submit_workout"}, None, member,
                        )
                        self.assertEqual(result, {"status": "both_workout"})
                    result = handle_submission_message(webhook, member["phone"], note.upper(), note, None, None, member)
                    prefix = "both" if participation == "BOTH" else "walker"
                    self.assertEqual(result, {"status": f"{prefix}_workout_confirm"})
                    review.assert_called_once_with(member["phone"], note.upper())
                    distances.assert_not_called()
                    result = handle_submission_message(webhook, member["phone"], None, None, {"id": "confirm"}, None, member)
                    self.assertEqual(result, {"status": "workout_confirmed"})
                saved = submission_service.get_completed_submission_for_current_event(member["id"])
                self.assertEqual(saved["time_text"], note.upper())
                self.assertEqual(saved["mode"], "WORKOUT")
                self.assertIsNone(saved["distance_text"])

    def test_mode_default_migration_preserves_existing_results_and_choices(self):
        member = self._insert_member("278010", participation_type="WALKER")
        existing = self._insert_submission(member["id"], status="PENDING", time_text="", seconds=0)
        with cursor() as cur:
            cur.execute("ALTER TABLE submissions ALTER COLUMN mode SET DEFAULT 'RUN'")
            cur.execute("DELETE FROM schema_migrations WHERE name = %s", (v20261027_submission_mode_default.VERSION,))
        self.assertEqual(upgrade_database(), [v20261027_submission_mode_default.VERSION])
        self.assertEqual(upgrade_database(), [])
        with cursor() as cur:
            cur.execute("SELECT column_default FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'submissions' AND column_name = 'mode'")
            self.assertIsNone(cur.fetchone()["column_default"])
            cur.execute("SELECT * FROM submissions WHERE id = %s", (existing["id"],))
            self.assertEqual(cur.fetchone(), existing)

    def test_mode_default_migration_recovers_only_empty_pending_walker_checkins(self):
        cases = (
            ("WALKER", "PENDING", None, "", 0, "WORKOUT"),
            ("WALKER", "PENDING", "", "", 0, "WORKOUT"),
            ("WALKER", "PENDING", "4", "", 0, "RUN"),
            ("WALKER", "PENDING", None, "Saved note", 0, "RUN"),
            ("WALKER", "COMPLETE", None, "", 0, "RUN"),
            ("WALKER", "PENDING", None, "", 1800, "RUN"),
            ("BOTH", "PENDING", None, "", 0, "RUN"),
            ("RUNNER", "PENDING", None, "", 0, "RUN"),
        )
        originals = []
        for index, (participation, status, distance, note, seconds, expected_mode) in enumerate(cases):
            member = self._insert_member(f"27802{index}", participation_type=participation)
            row = self._insert_submission(
                member["id"], status=status, distance_text=distance, time_text=note, seconds=seconds,
            )
            originals.append((row, expected_mode))
        with cursor() as cur:
            v20261027_submission_mode_default.upgrade(cur)
            for original, expected_mode in originals:
                cur.execute("SELECT * FROM submissions WHERE id = %s", (original["id"],))
                self.assertEqual(cur.fetchone(), {**original, "mode": expected_mode})

    def test_queue_claim_uses_postgresql_skip_locked_across_two_workers(self):
        job_id = job_queue_service.enqueue_job("integration", {"kind": "claim"})
        claimed_by_a = job_queue_service._claim_next_job()
        claimed_by_b = job_queue_service._claim_next_job()

        self.assertEqual(claimed_by_a["id"], job_id)
        self.assertIsNone(claimed_by_b)

    def test_immediate_replies_bypass_backlog_and_coaching_without_five_job_limit(self):
        backlog = [job_queue_service.enqueue_whatsapp_text("2770", "Broadcast") for _ in range(8)]
        coaching = job_queue_service.enqueue_job(job_queue_service.JOB_POST_CONFIRM_MESSAGES, {})
        replies = [job_queue_service.enqueue_whatsapp_text("2771", f"Reply {i}") for i in range(7)]
        with patch("app.whatsapp._send_direct", return_value=True) as send:
            self.assertEqual(job_queue_service.run_reply_jobs(replies), 7)
            self.assertEqual(job_queue_service.run_reply_jobs(replies), 0)

        self.assertEqual([call.args[0]["text"]["body"] for call in send.call_args_list],
                         [f"Reply {i}" for i in range(7)])
        with cursor() as cur:
            cur.execute("SELECT id, status FROM job_queue")
            statuses = {row["id"]: row["status"] for row in cur.fetchall()}
        self.assertTrue(all(statuses[job_id] == "PENDING" for job_id in backlog + [coaching]))
        self.assertTrue(all(statuses[job_id] == "DONE" for job_id in replies))

    def test_immediate_reply_claim_respects_locks_type_retry_time_and_attempts(self):
        running = job_queue_service.enqueue_whatsapp_text("2771", "Already claimed")
        self.assertEqual(job_queue_service._claim_next_job()["id"], running)
        delayed = job_queue_service.enqueue_whatsapp_text("2771", "Retry later")
        exhausted = job_queue_service.enqueue_whatsapp_text("2771", "Exhausted")
        coaching = job_queue_service.enqueue_job(job_queue_service.JOB_POST_CONFIRM_MESSAGES, {})
        locked = job_queue_service.enqueue_whatsapp_text("2771", "Locked")
        ready = job_queue_service.enqueue_whatsapp_text("2771", "Ready")
        with cursor() as cur:
            cur.execute("UPDATE job_queue SET run_after = CURRENT_TIMESTAMP + INTERVAL '1 hour' WHERE id = %s", (delayed,))
            cur.execute("UPDATE job_queue SET attempts = max_attempts WHERE id = %s", (exhausted,))
        with cursor() as cur:
            cur.execute("SELECT id FROM job_queue WHERE id = %s FOR UPDATE", (locked,))
            with patch("app.whatsapp._send_direct", return_value=True) as send:
                self.assertEqual(job_queue_service.run_reply_jobs([running, delayed, exhausted, coaching, locked, ready]), 1)
        self.assertEqual(send.call_args.args[0]["text"]["body"], "Ready")
        self.assertEqual(job_queue_service._claim_next_job(job_ids=[locked])["id"], locked)

    def test_immediate_reply_failure_keeps_durable_scheduled_retry(self):
        @contextmanager
        def sa_cursor(commit=True):
            with db.get_cursor(commit=commit) as cur:
                cur.execute("SET LOCAL TIME ZONE 'Africa/Johannesburg'")
                yield cur

        with patch.object(job_queue_service, "get_cursor", side_effect=sa_cursor):
            reply = job_queue_service.enqueue_whatsapp_text("2771", "Retry me")
            with patch("app.whatsapp._send_direct", return_value=False) as send:
                self.assertEqual(job_queue_service.run_reply_jobs([reply]), 1)
                self.assertEqual(job_queue_service.run_reply_jobs([reply]), 0)
            send.assert_called_once()
            with sa_cursor() as cur:
                cur.execute("SELECT status, attempts, run_after > CURRENT_TIMESTAMP AS delayed FROM job_queue WHERE id = %s", (reply,))
                row = cur.fetchone()
        self.assertEqual(row["status"], "PENDING")
        self.assertEqual(row["attempts"], 1)
        self.assertTrue(row["delayed"])

    def _admin_entry_members(self):
        admin = self._insert_member("270001", popia_acknowledged=True)
        member = self._insert_member("270002", popia_acknowledged=True)
        return admin, member

    def test_backdated_admin_tt_reaches_event_leaderboard_progress_and_attendance(self):
        admin, member = self._admin_entry_members()
        with cursor() as cur:
            cur.execute("UPDATE members SET leaderboard_visibility_set = TRUE, leaderboard_opt_out = FALSE WHERE id = %s", (member["id"],))
        recent_date = date(2026, 10, 20)
        recent = self._insert_submission(member["id"], event_date=recent_date, created_at="2026-10-20 19:00:00")
        with patch.object(config, "ADMIN_NUMBERS", frozenset({admin["phone"]})):
            run = admin_submission_service.save_admin_submission(admin["phone"], member["id"], "2026-10-06", "RUN", "26:00", "4")["submission"]
            walk = admin_submission_service.save_admin_submission(admin["phone"], member["id"], "2026-10-13", "WORKOUT", "Pyramid walk, 5.54km, 41:35")["submission"]
        run_date, walk_date = run["event_date"], walk["event_date"]
        board = leaderboard_service.get_runner_leaderboard(run_date)
        self.assertEqual([(r["member_id"], r["time_text"]) for r in board], [(member["id"], "26:00")])
        self.assertEqual(leaderboard_service.get_runner_leaderboard(walk_date), [])
        self.assertEqual([r["time_text"] for r in leaderboard_service.get_runner_leaderboard(recent_date)], [recent["time_text"]])
        self.assertEqual([r["time_text"] for r in leaderboard_service.get_walker_feed(walk_date)], [walk["time_text"]])
        self.assertEqual(leaderboard_service.get_walker_feed(run_date), [])
        ranged = leaderboard_service.get_runner_leaderboards_for_range(run_date, walk_date)
        self.assertEqual([r["event_date"] for r in ranged], [run_date])
        self.assertEqual([r["event_date"] for r in leaderboard_service.get_walker_feeds_for_range(run_date, walk_date)], [walk_date])
        profile = profile_service.get_user_profile(member["id"])
        self.assertEqual(profile["total_runs"], 3)
        self.assertEqual(profile["latest"]["id"], recent["id"])
        self.assertEqual([r["event_date"] for r in profile["recent"]], [recent_date, run_date])
        self.assertEqual(profile["pbs"], [{"distance_text": "4", "best_seconds": 1560}])
        attendance = monthly_attendance_report_service.fetch_attendance_rows(recent_date)
        self.assertEqual([r["event_date"] for r in attendance], [run_date, walk_date])
        self.assertTrue(all(r["submitted_result"] and not r["pending_result"] for r in attendance))
        stats = engagement_service.get_attendance_stats(member["id"], today=walk_date)
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["longest_streak"], 2)
        self.assertEqual(stats["latest_date"], walk_date)
        # Public sharing preferences still apply to admin-entered results.
        with cursor() as cur:
            cur.execute("UPDATE members SET leaderboard_opt_out = TRUE WHERE id = %s", (member["id"],))
        self.assertEqual(leaderboard_service.get_runner_leaderboard(run_date), [])
        self.assertEqual(leaderboard_service.get_walker_feed(walk_date), [])
        self.assertEqual(profile_service.get_user_profile(member["id"])["total_runs"], 3)

    def test_admin_missing_run_and_workout_save_selected_date_with_audit_and_attendance(self):
        admin, member = self._admin_entry_members()
        with patch.object(config, "ADMIN_NUMBERS", frozenset({admin["phone"]})):
            for event_date, mode, note, distance in (
                ("2026-10-06", "RUN", "27:41", "4"),
                ("2026-10-13", "WORKOUT", "Pyramid walk, 5.54km, 41:35", None),
            ):
                result = admin_submission_service.save_admin_submission(admin["phone"], member["id"], event_date, mode, note, distance)
                row = result["submission"]
                self.assertEqual(result["status"], "saved")
                self.assertEqual(row["event_date"], date.fromisoformat(event_date))
                self.assertEqual(row["mode"], mode)
                self.assertEqual(row["time_text"], note)
                self.assertEqual(row["status"], "COMPLETE")
                self.assertTrue(row["tt_code_verified"])
                self.assertTrue(row["confirmed"])
                with cursor() as cur:
                    cur.execute("SELECT * FROM attendance WHERE member_id = %s AND event_date = %s", (member["id"], event_date))
                    self.assertEqual(cur.fetchone()["source"], "whatsapp_admin")
                    cur.execute("SELECT * FROM admin_corrections WHERE submission_id = %s", (row["id"],))
                    audit = cur.fetchone()
                    self.assertEqual(audit["admin_member_id"], admin["id"])
                    self.assertEqual(audit["reason"], "admin_missing_tt_submission")
                    self.assertEqual(audit["new_time_text"], note)
                    self.assertIsNone(audit["old_time_text"])
            with cursor() as cur:
                cur.execute("SELECT COUNT(*) AS n FROM job_queue")
                self.assertEqual(cur.fetchone()["n"], 0)

    def test_admin_missing_tt_completes_pending_row_and_never_overwrites_complete(self):
        admin, member = self._admin_entry_members()
        pending = self._insert_submission(member["id"], event_date=date(2026, 10, 6), status="PENDING", confirmed=False, time_text="", seconds=0)
        with patch.object(config, "ADMIN_NUMBERS", frozenset({admin["phone"]})):
            saved = admin_submission_service.save_admin_submission(admin["phone"], member["id"], "2026-10-06", "RUN", "27:41", "6")
            self.assertEqual(saved["submission"]["id"], pending["id"])
            again = admin_submission_service.save_admin_submission(admin["phone"], member["id"], "2026-10-06", "WORKOUT", "Walk")
            self.assertEqual(again, {"status": "exists"})
        with cursor() as cur:
            cur.execute("SELECT * FROM submissions WHERE id = %s", (pending["id"],))
            self.assertEqual(cur.fetchone(), saved["submission"])
            cur.execute("SELECT * FROM admin_corrections WHERE submission_id = %s", (pending["id"],))
            audits = cur.fetchall()
            self.assertEqual(len(audits), 1)
            self.assertEqual(audits[0]["old_distance_text"], "4")

    def test_admin_missing_tt_rejects_non_admin_future_date_invalid_result_and_withdrawn_consent(self):
        admin, member = self._admin_entry_members()
        with patch.object(config, "ADMIN_NUMBERS", frozenset({admin["phone"]})):
            with self.assertRaises(PermissionError):
                admin_submission_service.save_admin_submission(member["phone"], member["id"], "2026-10-06", "RUN", "27:41", "4")
            for event_date, mode, note, distance in (
                ("2999-01-01", "RUN", "27:41", "4"),
                ("2026-10-06", "RUN", "00:00", "4"),
                ("2026-10-06", "RUN", "27:41", "5"),
                ("2026-10-06", "WORKOUT", "", None),
            ):
                with self.assertRaises(ValueError):
                    admin_submission_service.save_admin_submission(admin["phone"], member["id"], event_date, mode, note, distance)
            with cursor() as cur:
                cur.execute("UPDATE members SET popia_acknowledged = FALSE WHERE id = %s", (member["id"],))
            with self.assertRaises(ValueError):
                admin_submission_service.save_admin_submission(admin["phone"], member["id"], "2026-10-06", "RUN", "27:41", "4")
        with cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM submissions")
            self.assertEqual(cur.fetchone()["n"], 0)

    def test_concurrent_admin_submissions_save_only_one_result(self):
        admin, member = self._admin_entry_members()
        with patch.object(config, "ADMIN_NUMBERS", frozenset({admin["phone"]})), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: admin_submission_service.save_admin_submission(
                admin["phone"], member["id"], "2026-10-06", "RUN", "27:41", "4"), range(2)))
        self.assertEqual(sorted(result["status"] for result in results), ["exists", "saved"])
        with cursor() as cur:
            for table in ("submissions", "attendance", "admin_corrections"):
                cur.execute(f"SELECT COUNT(*) AS n FROM {table}")
                self.assertEqual(cur.fetchone()["n"], 1)

    def test_admin_save_and_member_checkin_cannot_create_duplicate_rows(self):
        admin, member = self._admin_entry_members()
        with cursor() as cur:
            cur.execute("SELECT (CURRENT_TIMESTAMP AT TIME ZONE 'Africa/Johannesburg')::date AS today")
            today = cur.fetchone()["today"].isoformat()
        with patch.object(config, "ADMIN_NUMBERS", frozenset({admin["phone"]})), ThreadPoolExecutor(max_workers=2) as pool:
            save = pool.submit(admin_submission_service.save_admin_submission, admin["phone"], member["id"], today, "RUN", "27:41", "4")
            checkin = pool.submit(submission_service.get_or_create_submission, member["id"])
            result = save.result()
            row = checkin.result()
            self.assertEqual(result["submission"]["id"], row["id"])
        with cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM submissions WHERE member_id = %s", (member["id"],))
            self.assertEqual(cur.fetchone()["n"], 1)

    def test_admin_save_rolls_back_result_if_audit_fails(self):
        admin, member = self._admin_entry_members()
        with patch.object(config, "ADMIN_NUMBERS", frozenset({admin["phone"]})), patch.object(
            admin_submission_service, "_record_admin_correction", side_effect=RuntimeError("audit unavailable")
        ):
            with self.assertRaises(RuntimeError):
                admin_submission_service.save_admin_submission(admin["phone"], member["id"], "2026-10-06", "RUN", "27:41", "4")
        with cursor() as cur:
            for table in ("submissions", "attendance", "admin_corrections"):
                cur.execute(f"SELECT COUNT(*) AS n FROM {table}")
                self.assertEqual(cur.fetchone()["n"], 0)

    def test_admin_whatsapp_journey_uses_persisted_draft_and_saves_only_on_confirm(self):
        admin, member = self._admin_entry_members()
        with patch.object(config, "ADMIN_NUMBERS", frozenset({admin["phone"]})), patch.object(
            webhook, "ADMIN_NUMBERS", frozenset({admin["phone"]})
        ), patch.object(admin_submission_flow, "send_text"), patch.object(
            admin_submission_flow, "send_admin_submission_buttons"
        ) as buttons, patch.object(admin_submission_flow, "send_admin_date_calendar", return_value=True) as calendar:
            for message, expected in (
                ("ADMIN SUBMIT", "admin_add_search"),
                (member["phone"], "admin_add_choose_member"),
                ("1", "admin_add_date"),
            ):
                result = route_message(webhook, admin["phone"], message, None)
                self.assertEqual(result["status"], expected)
            token = calendar.call_args.args[2]
            payload = {"entry": [{"changes": [{"value": {"messages": [{
                "id": "integration-calendar", "from": admin["phone"], "type": "interactive",
                "interactive": {"type": "nfm_reply", "nfm_reply": {"response_json": json.dumps({
                    "flow_token": token, "event_date": "2026-10-06",
                })}},
            }]}}]}]}
            _, sender, text, button = webhook.extract_whatsapp_message(payload)
            self.assertEqual(route_message(webhook, sender, text, button)["status"], "admin_add_mode")
            for message, expected in (
                ("WORKOUT", "admin_add_workout"),
                ("Pyramid walk, 5.54km, 41:35", "admin_add_review"),
            ):
                self.assertEqual(route_message(webhook, admin["phone"], message, None)["status"], expected)
            with cursor() as cur:
                cur.execute("SELECT COUNT(*) AS n FROM submissions")
                self.assertEqual(cur.fetchone()["n"], 0)
            confirm_id = buttons.call_args.args[2][0][0]
            result = route_message(webhook, admin["phone"], None, {"id": confirm_id})
            self.assertEqual(result["status"], "admin_add_saved")
            repeated = route_message(webhook, admin["phone"], None, {"id": confirm_id})
            self.assertEqual(repeated["status"], "admin_add_expired")
            with cursor() as cur:
                cur.execute("SELECT * FROM submissions WHERE id = %s", (result["submission_id"],))
                row = cur.fetchone()
                self.assertEqual(row["member_id"], member["id"])
                self.assertEqual(row["event_date"], date(2026, 10, 6))
                self.assertEqual(row["time_text"], "Pyramid walk, 5.54km, 41:35")

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
