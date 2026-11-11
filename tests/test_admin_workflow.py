import os
import unittest
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
from app.flows import admin_workflow_flow as flow, admin_dispatch
from app.services import admin_workflow_service as service
from app.services.tt_status_service import latest_tt_date
from app.services import monthly_email_schedule_service as email

ADMIN = "27700000001"


class AdminWorkflowTests(unittest.TestCase):
    def test_latest_tt_uses_sa_date_including_year_boundary(self):
        self.assertEqual(latest_tt_date(date(2026, 11, 11)), date(2026, 11, 10))
        self.assertEqual(latest_tt_date(date(2027, 1, 1)), date(2026, 12, 29))
        self.assertEqual(latest_tt_date(datetime(2026, 11, 9, 22, tzinfo=timezone.utc)), date(2026, 11, 10))

    def test_event_navigation_does_not_offer_future_tt(self):
        with patch.object(service, "require_admin"), patch.object(flow, "latest_tt_date", return_value=date(2026, 11, 10)), patch.object(
            flow, "get_event_summary", return_value={"event_date": date(2026, 11, 10), "summary": {}}
        ), patch.object(flow, "send_admin_workflow_buttons", return_value=True) as send:
            flow.show_event(ADMIN)
        buttons = send.call_args.args[2]
        self.assertEqual(buttons, [("adm_event:2026-11-03", "Previous TT"), ("adm_pending:2026-11-10:1", "Outstanding results")])

    def test_stable_member_ids_and_pagination_fit_whatsapp_list(self):
        rows = [{"id": mid, "first_name": "Member", "last_name": str(mid)} for mid in range(20, 27)]
        with patch.object(service, "pending_members", return_value=(rows, True)), patch.object(
            flow, "send_admin_workflow_list", return_value=True
        ) as send:
            flow.show_pending(ADMIN, date(2026, 11, 10), 2)
        options = send.call_args.args[2]
        self.assertEqual(len(options), 10)
        self.assertEqual(options[0][0], "adm_person:2026-11-10:20")
        self.assertTrue(all(len(title) <= 24 for _, title, _ in options))

    def test_pending_stages_include_runner_walker_and_missing_entry(self):
        self.assertEqual(service.pending_stage({}), "No result entry started")
        base = {"submission_id": 2, "tt_code_verified": True, "participation_type": "RUNNER"}
        self.assertEqual(service.pending_stage(base), "Distance not selected")
        self.assertEqual(service.pending_stage(dict(base, distance_text="4")), "Time not entered")
        self.assertEqual(service.pending_stage(dict(base, distance_text="4", time_text="20:00")), "Awaiting confirmation")
        self.assertEqual(service.pending_stage(dict(base, participation_type="WALKER")), "Workout note not entered")
        self.assertEqual(service.pending_stage(dict(base, mode="WORKOUT", time_text="Walk")), "Awaiting workout confirmation")

    def test_prompt_requires_live_member_window_and_open_event_and_no_reminder(self):
        now = datetime(2026, 11, 11, 12, tzinfo=service.SA_TZ)
        row = {"submission_id": 1, "tt_code_verified": True, "last_inbound_at": now - timedelta(hours=18)}
        with patch.object(service, "ensure_tt_open", return_value=(True, None)):
            self.assertTrue(service.prompt_eligibility(row, date(2026, 11, 10), now)[0])
            self.assertFalse(service.prompt_eligibility(dict(row, last_inbound_at=now-timedelta(hours=24)), date(2026, 11, 10), now)[0])
            self.assertFalse(service.prompt_eligibility(dict(row, reminder_status="DONE"), date(2026, 11, 10), now)[0])
            self.assertFalse(service.prompt_eligibility(row, date(2026, 11, 3), now)[0])
        with patch.object(service, "ensure_tt_open", return_value=(False, "closed")):
            self.assertFalse(service.prompt_eligibility(row, date(2026, 11, 10), now)[0])

    def test_stale_undo_button_never_mutates(self):
        with patch.object(service, "undo_correction") as undo, patch.object(flow, "send_text"):
            result = flow.handle_admin_workflow(SimpleNamespace(), ADMIN, None,
                {"id": "adm_undo_confirm:42"}, None, {"id": 1, "popia_acknowledged": True})
        self.assertEqual(result["status"], "admin_action_unavailable")
        undo.assert_not_called()

    def test_matching_undo_confirmation_calls_guarded_service_once(self):
        with patch.object(service, "undo_correction", return_value=(True, "restored")) as undo, patch.object(
            flow, "clear_profile_state"
        ) as clear, patch.object(flow, "send_text"):
            flow.handle_admin_workflow(SimpleNamespace(), ADMIN, None, {"id": "adm_undo_confirm:42"}, None,
                {"id": 1, "popia_acknowledged": True, "profile_state": "ADMIN_UNDO|42"})
        undo.assert_called_once_with(ADMIN, 42)
        clear.assert_called_once_with(1)

    def test_nonadmin_cannot_reach_new_flow(self):
        with patch.object(admin_dispatch, "handle_admin_workflow") as workflow, patch.object(
            admin_dispatch, "handle_admin_submission", return_value=None
        ):
            admin_dispatch.handle_admin_message(SimpleNamespace(), "outsider", None, None,
                {"id": "adm_undo_confirm:42"}, None, False)
        workflow.assert_not_called()
        with patch.object(service.config, "ADMIN_NUMBERS", frozenset({ADMIN})):
            for action in (lambda: service.pending_members("outsider", date(2026, 11, 10)),
                           lambda: service.undo_correction("outsider", 42),
                           lambda: service.queue_member_prompt("outsider", 1, date(2026, 11, 10))):
                with self.assertRaises(PermissionError):
                    action()

    def test_undo_requires_snapshot_and_current_revision(self):
        row = {"before_state": {}, "after_revision": 2, "revision": 2}
        self.assertTrue(service.can_undo(row))
        self.assertFalse(service.can_undo(dict(row, revision=3)))
        self.assertFalse(service.can_undo(dict(row, before_state=None)))
        self.assertFalse(service.can_undo(dict(row, reason="undo:1")))


class MonthlyEmailScheduleTests(unittest.TestCase):
    def test_schedule_is_off_without_explicit_enable_and_complete_config(self):
        with patch.object(email.config, "ATTENDANCE_REPORT_ENABLED", False), patch.object(email, "enqueue_job") as enqueue:
            self.assertEqual(email.queue_monthly_attendance_email(datetime(2026, 12, 1, 14)), {"queued": 0})
            enqueue.assert_not_called()
        with patch.object(email.config, "ATTENDANCE_REPORT_ENABLED", True), patch.object(email.config, "SMTP_HOST", None):
            self.assertFalse(email.email_schedule_ready())

    def test_schedule_skips_outside_window_and_delivery_rechecks_enablement(self):
        with patch.object(email, "email_schedule_ready", return_value=True), patch.object(email, "get_cursor") as db:
            for when in (datetime(2026, 12, 1, 13), datetime(2026, 12, 4, 14), datetime(2026, 12, 1, 20)):
                self.assertEqual(email.queue_monthly_attendance_email(when), {"queued": 0})
            db.assert_not_called()
        with patch.object(email, "email_schedule_ready", return_value=False), patch.object(email, "send_monthly_attendance_report") as send:
            self.assertFalse(email.deliver_monthly_attendance_email({"report_date": "2026-11-30"}, datetime(2026, 12, 1, 14)))
            send.assert_not_called()

    def test_delivery_uses_last_month_end_and_cannot_send_old_report(self):
        with patch.object(email, "email_schedule_ready", return_value=True), patch.object(email, "send_monthly_attendance_report") as send:
            self.assertTrue(email.deliver_monthly_attendance_email({"report_date": "2026-12-31"}, datetime(2027, 1, 1, 14)))
            send.assert_called_once_with(date(2026, 12, 31))
            self.assertFalse(email.deliver_monthly_attendance_email({"report_date": "2026-11-30"}, datetime(2027, 1, 1, 14)))
            self.assertFalse(email.deliver_monthly_attendance_email({"report_date": "2026-12-31"}, datetime(2027, 1, 4, 14)))
