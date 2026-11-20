"""Real isolated PostgreSQL: revisions, concurrent ticks, admin UX and sends."""

import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import festive_runs_integration as base

from app.flows import festive_weekly_flow as ui
from app.migrations import upgrade_database
from app.services import festive_weekly_notifications as n
from app.services import festive_weekly_service as w
from app.services.job_queue_service import _dispatch_job


@unittest.skipUnless(base.SAFE, "requires disposable local integration database")
class WeeklyIntegrationTests(unittest.TestCase):
    call = base.FestiveIntegrationTests.call
    sql = base.FestiveIntegrationTests.sql
    published = base.FestiveIntegrationTests.published

    def setUp(self):
        base.FestiveIntegrationTests.setUp(self)
        p = patch.dict(
            os.environ,
            {
                "FESTIVE_WEEKLY_DIGEST_ENABLED": "true",
                "FESTIVE_WEEKLY_BOT_LINK": "https://wa.me/27999990000?text=RUNS",
                "FESTIVE_WEEKLY_DIGEST_TIME": "06:00",
                "FESTIVE_WEEKLY_DIGEST_TIMEZONE": "Africa/Johannesburg",
                "FESTIVE_WEEKLY_AUTO_GROUP_POST": "false",
                "FESTIVE_WEEKLY_ADMIN_NOTIFICATION_ENABLED": "false",
                "FESTIVE_WEEKLY_TEMPLATE_APPROVED": "false",
                "FESTIVE_WEEKLY_NOTIFICATION_TEMPLATE": "",
            },
        )
        p.start()
        self.addCleanup(p.stop)
        self.at = datetime(2026, 12, 7, 6, tzinfo=w.domain.TZ)

    def generate(self):
        return w.generate(w.WEEKS[0], self.admin)

    def notice(self):
        n.subscribe(self.admin, True)
        with patch.dict(
            os.environ,
            {
                "FESTIVE_WEEKLY_ADMIN_NOTIFICATION_ENABLED": "true",
                "FESTIVE_WEEKLY_NOTIFICATION_TEMPLATE": "weekly_test",
                "FESTIVE_WEEKLY_TEMPLATE_APPROVED": "true",
            },
        ):
            w.schedule(self.at)
        return self.sql("SELECT * FROM festive_weekly_notices")[0]

    def deliver(self, notice, response=None, error=None):
        with (
            patch.dict(
                os.environ,
                {
                    "FESTIVE_UAT_MODE": "false",
                    "FESTIVE_WEEKLY_ADMIN_NOTIFICATION_ENABLED": "true",
                    "FESTIVE_WEEKLY_NOTIFICATION_TEMPLATE": "weekly_test",
                    "FESTIVE_WEEKLY_TEMPLATE_APPROVED": "true",
                },
            ),
            patch.object(w.domain, "now", return_value=self.at),
            patch.object(
                n.requests, "post", return_value=response, side_effect=error
            ) as post,
        ):
            _dispatch_job("festive_weekly_notice", {"notice_id": notice["id"]})
            return post

    def test_T13_T14_concurrent_and_restart_idempotency(self):
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(lambda _: w.schedule(self.at), range(3)))
        w.schedule(self.at + timedelta(hours=2))
        self.assertEqual(len(self.sql("SELECT * FROM festive_weekly_editions")), 1)
        self.assertEqual(self.sql("SELECT * FROM job_queue"), [])
        self.assertEqual(upgrade_database(), [])

    def test_T15_manual_regeneration_safe(self):
        first = self.generate()
        again = self.generate()
        self.assertEqual(first["id"], again["id"])
        self.assertEqual(first["generated_at"], again["generated_at"])

    def test_T16_posted_revision_preserved_and_draft_hidden(self):
        self.published()
        first = self.generate()
        w.mark_posted(self.admin, first["id"], self.at)
        self.call(
            base.s.save_details,
            self.lead,
            base.DAY,
            {**base.DETAILS, "meeting_point": "Private new park"},
            True,
        )
        self.assertEqual(self.generate()["id"], first["id"])
        self.call(base.s.admin_action, self.admin, base.DAY, "APPROVE")
        latest = self.generate()
        old = self.sql(
            "SELECT * FROM festive_weekly_editions WHERE id=%s", (first["id"],)
        )[0]
        self.assertEqual(old["status"], "OUTDATED")
        self.assertIsNotNone(old["posted_at"])
        self.assertEqual(old["messages"], first["messages"])
        self.assertEqual(latest["revision"], 2)
        self.assertIn("Private new park", " ".join(latest["correction_messages"]))

    def test_T17_cancellation_update(self):
        self.published()
        self.generate()
        self.call(base.s.admin_action, self.admin, base.DAY, "CANCEL")
        edition = self.generate()
        self.assertIn("cancelled", " ".join(edition["correction_messages"]))
        self.assertNotIn("📅", " ".join(edition["messages"]))

    def test_T18_host_reassignment_update(self):
        self.call(base.s.book, self.lead, base.DAY, "LEAD")
        self.generate()
        self.call(
            base.s.admin_action,
            self.admin,
            base.DAY,
            "REASSIGN",
            replacement=self.cohost,
        )
        edition = self.generate()
        self.assertEqual(edition["revision"], 2)
        self.assertIn("Cohost Test", " ".join(edition["messages"]))
        self.assertIn("Host / co-host", edition["changes"][0]["fields"])

    def test_T19_unauthorized_admin_commands_and_mutations(self):
        actions = SimpleNamespace(get_member=lambda _: self.members[0])
        with patch.object(base.t, "send") as send:
            base.chat.handle(actions, self.members[0]["phone"], "WEEKLY", None)
            self.assertIn("administrator", send.call_args.args[0]["text"]["body"])
        for fn, args in (
            (w.generate, (w.WEEKS[0], self.runner)),
            (w.mark_posted, (self.runner, 1)),
            (w.history, (self.runner,)),
            (n.subscribe, (self.runner, True)),
        ):
            with self.assertRaises(base.s.FestiveError):
                fn(*args)
        self.assertEqual(self.sql("SELECT * FROM festive_weekly_editions"), [])

    def test_T20_T21_existing_commands_and_tt_unchanged(self):
        self.generate()
        actions = SimpleNamespace(get_member=lambda _: self.members[0])
        with patch.object(base.t, "send"):
            for command in ("RUNS", "HOST", "JOIN"):
                result = base.chat.handle(
                    actions, self.members[0]["phone"], command, None
                )
                self.assertEqual(result["status"], "festive")
        self.assertEqual(self.sql("SELECT * FROM submissions"), [])
        self.assertEqual(self.sql("SELECT * FROM attendance"), [])

    def test_T23_T27_provider_accepted_not_group_posted(self):
        notice = self.notice()
        response = SimpleNamespace(
            ok=True, json=lambda: {"messages": [{"id": "wamid.weekly-test"}]}
        )
        post = self.deliver(notice, response)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.kwargs["json"]["type"], "template")
        self.assertEqual(self.deliver(notice, response).call_count, 0)
        saved = self.sql("SELECT * FROM festive_weekly_notices")[0]
        self.assertEqual(saved["status"], "ACCEPTED")
        self.assertEqual(saved["provider_message_id"], "wamid.weekly-test")
        self.assertEqual(
            self.sql("SELECT status FROM festive_weekly_editions")[0]["status"],
            "READY_FOR_REVIEW",
        )

    def test_T23_timeout_uncertain_never_auto_retried(self):
        notice = self.notice()
        self.deliver(notice, error=n.requests.Timeout())
        self.assertEqual(
            self.sql("SELECT status FROM festive_weekly_notices")[0]["status"],
            "UNCERTAIN",
        )
        self.assertEqual(self.deliver(notice).call_count, 0)

    def test_T23_rejected_provider_failure_recorded(self):
        notice = self.notice()
        self.deliver(notice, SimpleNamespace(ok=False, status_code=400))
        self.assertEqual(
            self.sql("SELECT status FROM festive_weekly_notices")[0]["status"], "FAILED"
        )

    def test_T28_template_missing_and_separate_opt_in(self):
        with patch.dict(
            os.environ, {"FESTIVE_WEEKLY_ADMIN_NOTIFICATION_ENABLED": "true"}
        ):
            w.schedule(self.at)
            self.assertEqual(self.sql("SELECT * FROM festive_weekly_notices"), [])
            n.subscribe(self.admin, True)
            w.schedule(self.at)
        self.assertEqual(
            self.sql("SELECT status FROM festive_weekly_notices")[0]["status"],
            "BLOCKED_TEMPLATE",
        )
        self.assertEqual(self.sql("SELECT * FROM job_queue"), [])

    def test_T28_optout_before_delivery(self):
        notice = self.notice()
        n.subscribe(self.admin, False)
        self.assertEqual(self.deliver(notice).call_count, 0)
        self.assertEqual(
            self.sql("SELECT status FROM festive_weekly_notices")[0]["status"],
            "SUPPRESSED",
        )

    def test_T27_manual_posted_confirmation_is_idempotent(self):
        edition = self.generate()
        a = w.mark_posted(self.admin, edition["id"], self.at)
        b = w.mark_posted(self.admin, edition["id"], self.at)
        self.assertEqual(a["posted_at"], b["posted_at"])
        self.assertEqual(a["delivery_status"], "ADMIN_CONFIRMED")
        self.assertIsNone(a["provider_message_id"])

    def test_stale_post_confirmation_refreshes_and_refuses(self):
        edition = self.generate()
        self.call(base.s.book, self.lead, base.DAY, "LEAD")
        with self.assertRaisesRegex(base.s.FestiveError, "outdated"):
            w.mark_posted(self.admin, edition["id"], self.at)
        rows = self.sql("SELECT * FROM festive_weekly_editions ORDER BY revision")
        self.assertEqual([r["status"] for r in rows], ["OUTDATED", "READY_FOR_REVIEW"])
        self.assertTrue(all(r["posted_at"] is None for r in rows))

    def test_cumulative_correction_against_last_posted(self):
        self.published()
        first = self.generate()
        w.mark_posted(self.admin, first["id"], self.at)
        self.call(
            base.s.save_details,
            self.lead,
            base.DAY,
            {**base.DETAILS, "start_time": "07:00"},
            True,
        )
        self.call(base.s.admin_action, self.admin, base.DAY, "APPROVE")
        self.generate()
        self.call(
            base.s.save_details,
            self.lead,
            base.DAY,
            {**base.DETAILS, "start_time": "07:00", "meeting_point": "Second park"},
            True,
        )
        self.call(base.s.admin_action, self.admin, base.DAY, "APPROVE")
        latest = self.generate()
        self.assertIn("Start time", latest["changes"][0]["fields"])
        self.assertIn("Meeting point", latest["changes"][0]["fields"])

    def test_future_preview_not_posted_or_notified(self):
        edition = self.generate()
        with self.assertRaisesRegex(base.s.FestiveError, "future draft"):
            w.mark_posted(self.admin, edition["id"])
        self.assertEqual(self.sql("SELECT * FROM festive_weekly_notices"), [])

    def test_missed_weeks_catchup_and_stop(self):
        w.schedule(datetime(2026, 12, 29, 10, tzinfo=base.s.TZ))
        self.assertEqual(len(self.sql("SELECT * FROM festive_weekly_editions")), 4)
        w.schedule(datetime(2027, 1, 4, tzinfo=base.s.TZ))
        self.assertEqual(len(self.sql("SELECT * FROM festive_weekly_editions")), 4)

    def test_native_and_text_menu_preview_share_and_post(self):
        messages = []
        actions = SimpleNamespace(get_member=lambda _: self.members[3])
        phone = self.members[3]["phone"]
        with (
            patch.object(ui, "send", side_effect=messages.append),
            patch.object(base.s, "now", return_value=self.at),
        ):
            base.chat.handle(actions, phone, "WEEKLY", None)
            self.assertEqual(
                len(messages[-1]["interactive"]["action"]["sections"][0]["rows"]), 6
            )
            base.chat.handle(actions, phone, None, {"id": ui.PREFIX + "1"})
            self.assertTrue(
                any(
                    "YOUR FESTIVE RUNS" in m.get("text", {}).get("body", "")
                    for m in messages
                )
            )
            base.chat.handle(actions, phone, "WEEKLY TEXT", None)
            self.assertEqual(messages[-1]["type"], "text")
            base.chat.handle(actions, phone, "3", None)
            base.chat.handle(actions, phone, "6", None)
            base.chat.handle(actions, phone, "1", None)
        self.assertEqual(
            self.sql("SELECT status FROM festive_weekly_editions")[0]["status"],
            "POSTED",
        )

    def test_reply_queue_has_expiry_and_failed_provider_is_retryable(self):
        with patch.object(base.s, "now", return_value=self.at):
            ui.say(self.members[3]["phone"], "Weekly preview")
        job = self.sql("SELECT * FROM job_queue")[0]
        self.assertEqual(job["job_type"], "festive_weekly_reply")
        with (
            patch.dict(os.environ, {"FESTIVE_UAT_MODE": "false"}),
            patch.object(base.s, "now", return_value=self.at),
            patch("app.whatsapp._send_direct", return_value=False),
            self.assertRaises(RuntimeError),
        ):
            _dispatch_job(job["job_type"], job["payload"])

    def test_T30_disabled_queued_delivery_and_generation(self):
        notice = self.notice()
        with (
            patch.dict(os.environ, {"FESTIVE_WEEKLY_DIGEST_ENABLED": "false"}),
            patch.object(n.requests, "post") as post,
        ):
            self.assertEqual(w.schedule(self.at)["generated"], 0)
            n.deliver({"notice_id": notice["id"]})
            post.assert_not_called()
            actions = SimpleNamespace(get_member=lambda _: self.members[3])
            with patch.object(base.t, "send") as reply:
                base.chat.handle(actions, self.members[3]["phone"], "WEEKLY", None)
            self.assertIn("disabled", reply.call_args.args[0]["text"]["body"])

    def test_failed_first_generation_records_failure_and_recovers(self):
        with (
            patch.object(w, "render", side_effect=RuntimeError("private test error")),
            self.assertRaises(RuntimeError),
        ):
            w.schedule(self.at)
        failed = self.sql("SELECT * FROM festive_weekly_editions")[0]
        self.assertEqual(failed["status"], "FAILED")
        self.assertNotIn("private", failed["last_error"])
        w.schedule(self.at)
        editions = self.sql("SELECT * FROM festive_weekly_editions ORDER BY revision")
        self.assertEqual(editions[-1]["status"], "READY_FOR_REVIEW")
        self.assertIsNone(editions[-1]["last_error"])

    def test_failed_refresh_preserves_posted_content(self):
        first = self.generate()
        w.mark_posted(self.admin, first["id"], self.at)
        with (
            patch.object(w, "render", side_effect=RuntimeError("failure")),
            self.assertRaises(RuntimeError),
        ):
            w.schedule(self.at)
        old = self.sql("SELECT * FROM festive_weekly_editions")[0]
        self.assertEqual(old["messages"], first["messages"])
        self.assertEqual(old["status"], "POSTED")
        self.assertIsNotNone(old["last_error"])
        w.schedule(self.at)
        self.assertIsNone(
            self.sql("SELECT last_error FROM festive_weekly_editions")[0]["last_error"]
        )

    def test_restart_deduplicates_admin_notice_jobs(self):
        notice = self.notice()
        with (
            patch.dict(
                os.environ,
                {
                    "FESTIVE_WEEKLY_ADMIN_NOTIFICATION_ENABLED": "true",
                    "FESTIVE_WEEKLY_NOTIFICATION_TEMPLATE": "weekly_test",
                    "FESTIVE_WEEKLY_TEMPLATE_APPROVED": "true",
                },
            ),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            list(pool.map(lambda _: w.schedule(self.at), range(2)))
        self.assertEqual(len(self.sql("SELECT * FROM festive_weekly_notices")), 1)
        self.assertEqual(
            len(
                self.sql(
                    "SELECT * FROM job_queue WHERE job_type='festive_weekly_notice'"
                )
            ),
            1,
        )
        self.assertEqual(
            self.sql("SELECT id FROM festive_weekly_notices")[0]["id"], notice["id"]
        )

    def test_temporary_database_unavailability_retries_on_next_tick(self):
        with (
            patch.object(w, "get_cursor", side_effect=RuntimeError("database offline")),
            self.assertRaises(RuntimeError),
        ):
            w.schedule(self.at)
        w.schedule(self.at)
        self.assertEqual(len(self.sql("SELECT * FROM festive_weekly_editions")), 1)

    def test_outdated_notice_suppressed_without_send(self):
        notice = self.notice()
        self.call(base.s.book, self.lead, base.DAY, "LEAD")
        self.generate()
        self.assertEqual(self.deliver(notice).call_count, 0)
        self.assertEqual(
            self.sql("SELECT status FROM festive_weekly_notices")[0]["status"],
            "SUPPRESSED",
        )

    def test_empty_calendar_and_disabled_do_not_invent_runs(self):
        self.sql("DELETE FROM festive_run_slots")
        edition = self.generate()
        self.assertEqual(edition["source_snapshot"], [])
        self.assertIn("No upcoming", " ".join(edition["messages"]))

    def test_interactive_weekly_submenu_does_not_capture_run_selection(self):
        actions = SimpleNamespace(get_member=lambda _: self.members[3])
        phone = self.members[3]["phone"]
        with patch.object(ui, "send"), patch.object(base.t, "send"):
            base.chat.handle(actions, phone, "WEEKLY", None)
            result = base.chat.handle(
                actions, phone, None, {"id": "festive:run:" + base.DAY}
            )
        self.assertEqual(result["status"], "festive")
