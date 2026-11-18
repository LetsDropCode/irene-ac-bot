"""Real PostgreSQL transactions, with synthetic members and no Meta traffic."""

import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import postgres_integration as base
from app import config, whatsapp
from app.services import flow_session_service as flows, delivery_status_service as delivery
from app.services import job_queue_service as jobs, privacy_service
from app.meta_api import MetaSendError


@unittest.skipUnless(base._is_safe_integration_url(base.INTEGRATION_DATABASE_URL), "requires disposable PostgreSQL")
class NativeWhatsAppIntegrationTests(unittest.TestCase):
    setUp = base.PostgreSQLIntegrationTests.setUp
    _reset_public_schema = base.PostgreSQLIntegrationTests._reset_public_schema
    _insert_member = base.PostgreSQLIntegrationTests._insert_member
    _insert_submission = base.PostgreSQLIntegrationTests._insert_submission

    def calendar(self):
        draft = {"step": "date", "token": "draft-test-token", "member_id": 42, "name": "Test Member"}
        member = self._insert_member("test-admin", popia_acknowledged=True,
                                     profile_state="ADMIN_ADD_TT|" + json.dumps(draft))
        with patch.object(config, "ADMIN_NUMBERS", {"test-admin"}), whatsapp.queue_inbound_replies("test-inbound") as ids:
            self.assertTrue(flows.launch_admin_calendar("test-admin", "Test Member", draft["token"], "test-flow-id"))
        self.assertEqual(len(ids), 1)
        with base.cursor() as cur:
            cur.execute("SELECT payload FROM job_queue WHERE id = %s", (ids[0],))
            payload = cur.fetchone()["payload"]["payload"]
        params = payload["interactive"]["action"]["parameters"]
        self.assertEqual(params["flow_action_payload"]["screen"], "TT_DATE")
        self.assertNotIn("test-admin", params["flow_token"])
        return member, {"flow_token": params["flow_token"], "event_date": "2026-10-06"}

    def complete(self, data, sender="test-admin"):
        with patch.object(config, "WHATSAPP_FLOWS_ENABLED", True), patch.object(config, "ADMIN_NUMBERS", {"test-admin"}):
            return flows.complete_flow(sender, data)

    def test_retried_launch_reuses_durable_message_and_token(self):
        member, data = self.calendar()
        with patch.object(config, "ADMIN_NUMBERS", {"test-admin"}), whatsapp.queue_inbound_replies("test-inbound"):
            self.assertTrue(flows.launch_admin_calendar("test-admin", "Test Member", "draft-test-token", "test-flow-id"))
        with base.cursor() as cur:
            cur.execute("SELECT count(*) AS n FROM whatsapp_flow_sessions")
            self.assertEqual(cur.fetchone()["n"], 1)
            cur.execute("SELECT count(*) AS n FROM job_queue")
            self.assertEqual(cur.fetchone()["n"], 1)
        self.assertEqual(self.complete(data)[0], "completed")

    def test_undeliverable_calendar_queues_one_manual_fallback(self):
        _, data = self.calendar()
        with base.cursor() as cur:
            cur.execute("SELECT id FROM job_queue LIMIT 1")
            job_id = cur.fetchone()["id"]
        with patch.object(config, "ADMIN_NUMBERS", {"test-admin"}):
            for _ in range(2):
                self.assertTrue(delivery.record_status(self.event(job_id, "failed")))
        with base.cursor() as cur:
            cur.execute("SELECT payload FROM job_queue WHERE dedupe_key = %s", (f"flow-fallback:{job_id}",))
            rows = cur.fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["payload"]["payload"]["type"], "text")
            self.assertIn("YYYY-MM-DD", rows[0]["payload"]["payload"]["text"]["body"])
        self.assertEqual(self.complete(data)[0], "completed")

    def test_expired_calendar_failure_never_sends_a_free_form_followup(self):
        self.calendar()
        with base.cursor() as cur:
            cur.execute("SELECT id FROM job_queue LIMIT 1")
            job_id = cur.fetchone()["id"]
            cur.execute("UPDATE whatsapp_flow_sessions SET expires_at = CURRENT_TIMESTAMP - INTERVAL '1 minute'")
        with patch.object(config, "ADMIN_NUMBERS", {"test-admin"}):
            delivery.record_status(self.event(job_id, "failed"))
        with base.cursor() as cur:
            cur.execute("SELECT count(*) AS n FROM job_queue")
            self.assertEqual(cur.fetchone()["n"], 1)

    def test_delayed_launch_and_fallback_are_not_sent_after_session_expiry(self):
        self.calendar()
        with base.cursor() as cur:
            cur.execute("SELECT id FROM job_queue LIMIT 1")
            job_id = cur.fetchone()["id"]
        with patch.object(config, "ADMIN_NUMBERS", {"test-admin"}):
            delivery.record_status(self.event(job_id, "failed"))
        with base.cursor() as cur:
            cur.execute("UPDATE whatsapp_flow_sessions SET expires_at = CURRENT_TIMESTAMP - INTERVAL '1 minute'")
        with patch.object(config, "WHATSAPP_FLOWS_ENABLED", True), patch.object(config, "ADMIN_NUMBERS", {"test-admin"}), patch.object(
            whatsapp, "_send_direct"
        ) as direct:
            jobs.run_due_jobs(10)
            direct.assert_not_called()
        with base.cursor() as cur:
            cur.execute("SELECT count(*) AS n FROM job_queue WHERE status = 'DONE'")
            self.assertEqual(cur.fetchone()["n"], 2)

    def test_terminal_launch_rejection_queues_manual_recovery(self):
        self.calendar()
        with patch.object(config, "WHATSAPP_FLOWS_ENABLED", True), patch.object(config, "ADMIN_NUMBERS", {"test-admin"}), patch.object(
            whatsapp, "_send_direct", side_effect=MetaSendError("rejected", permanent=True)
        ):
            jobs._run_job(jobs._claim_next_job())
        with base.cursor() as cur:
            cur.execute("SELECT count(*) AS n FROM job_queue WHERE dedupe_key LIKE 'flow-fallback:%%'")
            self.assertEqual(cur.fetchone()["n"], 1)

    def test_valid_calendar_completion_advances_state_and_queues_once(self):
        member, data = self.calendar()
        status, job_id = self.complete(data)
        self.assertEqual(status, "completed")
        self.assertIsNotNone(job_id)
        self.assertEqual(self.complete(data), ("duplicate", None))
        with base.cursor() as cur:
            cur.execute("SELECT profile_state FROM members WHERE id = %s", (member["id"],))
            draft = json.loads(cur.fetchone()["profile_state"].split("|", 1)[1])
            self.assertEqual((draft["step"], draft["date"]), ("mode", "2026-10-06"))
            cur.execute("SELECT count(*) AS n FROM job_queue")
            self.assertEqual(cur.fetchone()["n"], 2)
            cur.execute("SELECT count(*) AS n FROM submissions")
            self.assertEqual(cur.fetchone()["n"], 0)

    def test_concurrent_completions_are_serialized(self):
        _, data = self.calendar()
        with patch.object(config, "WHATSAPP_FLOWS_ENABLED", True), patch.object(config, "ADMIN_NUMBERS", {"test-admin"}):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: flows.complete_flow("test-admin", data)[0], range(2)))
        self.assertCountEqual(results, ["completed", "duplicate"])

    def test_invalid_date_does_not_consume_session(self):
        _, data = self.calendar()
        for value in (None, {}, "2999-01-01", "2026-02-30", "CANCEL"):
            self.assertEqual(self.complete({**data, "event_date": value}), ("invalid", None))
        self.assertEqual(self.complete(data)[0], "completed")

    def test_cross_member_unknown_token_and_revoked_admin_are_rejected(self):
        _, data = self.calendar()
        self._insert_member("test-other", popia_acknowledged=True)
        self.assertEqual(self.complete(data, "test-other"), ("stale", None))
        self.assertEqual(self.complete({**data, "flow_token": "z" * 32}), ("stale", None))
        with patch.object(config, "WHATSAPP_FLOWS_ENABLED", True), patch.object(config, "ADMIN_NUMBERS", set()):
            self.assertEqual(flows.complete_flow("test-admin", data), ("unauthorized", None))
        self.assertEqual(self.complete(data)[0], "completed")

    def test_expired_and_cancelled_sessions_cannot_change_state(self):
        member, data = self.calendar()
        with base.cursor() as cur:
            cur.execute("UPDATE whatsapp_flow_sessions SET expires_at = CURRENT_TIMESTAMP - INTERVAL '1 minute'")
        self.assertEqual(self.complete(data), ("expired", None))
        with base.cursor() as cur:
            cur.execute("UPDATE whatsapp_flow_sessions SET expires_at = CURRENT_TIMESTAMP + INTERVAL '1 minute'")
            cur.execute("UPDATE members SET profile_state = NULL WHERE id = %s", (member["id"],))
        self.assertEqual(self.complete(data), ("stale", None))

    def test_callback_failure_rolls_back_state_token_and_outbound_write(self):
        member, data = self.calendar()
        with patch.object(flows, "enqueue_job", side_effect=RuntimeError("queue unavailable")):
            with self.assertRaises(RuntimeError):
                self.complete(data)
        with base.cursor() as cur:
            cur.execute("SELECT profile_state FROM members WHERE id = %s", (member["id"],))
            self.assertIn('"step": "date"', cur.fetchone()["profile_state"])
            cur.execute("SELECT consumed_at FROM whatsapp_flow_sessions")
            self.assertIsNone(cur.fetchone()["consumed_at"])
        self.assertEqual(self.complete(data)[0], "completed")

    def test_manual_entry_invalidates_old_form(self):
        member, data = self.calendar()
        with base.cursor() as cur:
            cur.execute("UPDATE members SET profile_state = %s WHERE id = %s",
                        ('ADMIN_ADD_TT|{"step":"mode","date":"2026-10-13"}', member["id"]))
        self.assertEqual(self.complete(data), ("stale", None))

    def queued_message(self):
        return jobs.enqueue_whatsapp_text("test-admin", "Synthetic test message")

    def event(self, job_id, status, message_id="wamid.synthetic"):
        return {"id": message_id, "status": status, "timestamp": "1794950000",
                "recipient_id": "test-admin", "biz_opaque_callback_data": f"job:{job_id}",
                "errors": [{"code": 131026, "message": "MUST NOT BE STORED"}] if status == "failed" else []}

    def test_status_before_acceptance_and_out_of_order_events_keep_strongest_evidence(self):
        job_id = self.queued_message()
        for status in ("read", "sent", "failed", "delivered", "read"):
            self.assertTrue(delivery.record_status(self.event(job_id, status)))
        delivery.record_acceptance(job_id, "wamid.synthetic")
        with base.cursor() as cur:
            cur.execute("SELECT * FROM whatsapp_delivery_status")
            rows = cur.fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "read")
            self.assertIsNone(rows[0]["error_code"])
            self.assertNotIn("MUST NOT BE STORED", str(rows))

    def test_failed_status_does_not_change_queue_or_saved_tt_result(self):
        member = self._insert_member("test-admin", popia_acknowledged=True)
        submission = self._insert_submission(member["id"])
        job_id = self.queued_message()
        with base.cursor() as cur:
            cur.execute("UPDATE job_queue SET status = 'DONE' WHERE id = %s", (job_id,))
        delivery.record_acceptance(job_id, "wamid.synthetic")
        self.assertTrue(delivery.record_status(self.event(job_id, "failed")))
        with base.cursor() as cur:
            cur.execute("SELECT status FROM submissions WHERE id = %s", (submission["id"],))
            self.assertEqual(cur.fetchone()["status"], "COMPLETE")
            cur.execute("SELECT status FROM job_queue WHERE id = %s", (job_id,))
            self.assertEqual(cur.fetchone()["status"], "DONE")

    def test_unknown_unsupported_and_malformed_statuses_do_not_create_records(self):
        job_id = self.queued_message()
        for event in (None, {}, {"status": []}, self.event(job_id, "deleted"),
                      {**self.event(job_id, "sent"), "timestamp": "bad"},
                      {**self.event(job_id, "sent"), "recipient_id": "other"},
                      self.event(9999, "sent")):
            self.assertFalse(delivery.record_status(event))
        with base.cursor() as cur:
            cur.execute("SELECT count(*) AS n FROM whatsapp_delivery_status")
            self.assertEqual(cur.fetchone()["n"], 0)

    def test_withdrawal_erases_sessions_statuses_and_late_callbacks_do_not_recreate_them(self):
        _, data = self.calendar()
        job_id = self.queued_message()
        delivery.record_acceptance(job_id, "wamid.synthetic")
        self.assertTrue(privacy_service.withdraw_consent_and_request_erasure("test-admin"))
        self.assertEqual(self.complete(data), ("unauthorized", None))
        self.assertFalse(delivery.record_status(self.event(job_id, "sent")))
        self.assertTrue(privacy_service.erase_member_after_confirmation("test-admin"))
        with base.cursor() as cur:
            for table in ("whatsapp_flow_sessions", "whatsapp_delivery_status", "job_queue"):
                cur.execute(f"SELECT count(*) AS n FROM {table}")
                self.assertEqual(cur.fetchone()["n"], 0)

    def test_diagnostic_retention_removes_old_rows_without_touching_tt(self):
        member, _ = self.calendar()
        self._insert_submission(member["id"])
        job_id = self.queued_message()
        delivery.record_acceptance(job_id, "wamid.synthetic")
        with base.cursor() as cur:
            cur.execute("UPDATE whatsapp_delivery_status SET created_at = CURRENT_TIMESTAMP - INTERVAL '31 days'")
            cur.execute("UPDATE whatsapp_flow_sessions SET expires_at = CURRENT_TIMESTAMP - INTERVAL '2 days'")
        delivery.prune_native_diagnostics()
        with base.cursor() as cur:
            for table in ("whatsapp_flow_sessions", "whatsapp_delivery_status"):
                cur.execute(f"SELECT count(*) AS n FROM {table}")
                self.assertEqual(cur.fetchone()["n"], 0)
            cur.execute("SELECT count(*) AS n FROM submissions")
            self.assertEqual(cur.fetchone()["n"], 1)

    def test_permanent_send_failure_exhausts_no_extra_attempts(self):
        job_id = self.queued_message()
        job = jobs._claim_next_job()
        with patch.object(whatsapp, "_send_direct", side_effect=MetaSendError("credentials", permanent=True)):
            jobs._run_job(job)
        with base.cursor() as cur:
            cur.execute("SELECT status, attempts FROM job_queue WHERE id = %s", (job_id,))
            self.assertEqual(dict(cur.fetchone()), {"status": "FAILED", "attempts": 1})
        self.assertIsNone(jobs._claim_next_job())
