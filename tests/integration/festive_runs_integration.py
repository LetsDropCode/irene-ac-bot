"""Real PostgreSQL UAT, atomicity and concurrency. All transports are mocked."""

import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlparse

URL = os.getenv("INTEGRATION_DATABASE_URL")
if URL:
    os.environ["DATABASE_URL"] = URL
else:
    os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
from app import db
from app.flows import festive_flow as chat
from app.migrations import upgrade_database
from app.migrations.versions import v20261118_festive_runs as migration
from app.services import festive_flow_service as f
from app.services import festive_notifications as n
from app.services import festive_service as s
from app.services import festive_transport as t
from app.services.job_queue_service import _dispatch_job

DAY = "2026-12-13"
DETAILS = {
    "meeting_point": "Test public park",
    "location_description": "Meet at the east gate",
    "start_time": "06:00",
    "distances": "5km, 10km",
    "route_description": "Two marked loops",
    "safety_notes": "Cross roads carefully; park in designated bays",
    "maps_url": "https://maps.google.com/?q=-25.9,28.2",
    "walkers_welcome": "yes",
    "coffee_arrangements": "TBC",
}
SAFE = (
    URL
    and urlparse(URL).hostname in {"127.0.0.1", "localhost"}
    and any(v in urlparse(URL).path.lower() for v in ("test", "integration"))
)


@unittest.skipUnless(
    SAFE, "requires an explicitly supplied disposable local integration database"
)
class FestiveIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.patchers = [
            patch.dict(
                os.environ,
                {
                    "FESTIVE_RUNS_ENABLED": "true",
                    "FESTIVE_UAT_MODE": "true",
                    "FESTIVE_UAT_ALLOWLIST": "27999990001,27999990002,27999990003,27999990004",
                    "FESTIVE_FLOWS_READY": "false",
                    "FESTIVE_NOTIFICATION_TEMPLATE": "festive_test",
                    "FESTIVE_INTERACTIVE_ENABLED": "true",
                },
            ),
            patch.object(s, "ADMIN_NUMBERS", frozenset({"27999990004"})),
            patch.object(n, "ADMIN_NUMBERS", frozenset({"27999990004"})),
            patch.object(
                s, "now", return_value=datetime(2026, 11, 18, 12, tzinfo=s.TZ)
            ),
            patch(
                "requests.sessions.Session.request",
                side_effect=AssertionError("Live network forbidden in festive tests"),
            ),
        ]
        for p in self.patchers:
            p.start()
            self.addCleanup(p.stop)
        with db.get_cursor() as cur:
            cur.execute("DROP SCHEMA public CASCADE")
            cur.execute("CREATE SCHEMA public")
        upgrade_database()
        self.members = []
        with db.get_cursor() as cur:
            for i, name in enumerate(("Runner", "Lead", "Cohost", "Captain"), 1):
                cur.execute(
                    "INSERT INTO members(phone,first_name,last_name,popia_acknowledged,reminders_opt_in) VALUES (%s,%s,'Test',TRUE,TRUE) RETURNING *",
                    (f"2799999000{i}", name),
                )
                self.members.append(cur.fetchone())
        self.runner, self.lead, self.cohost, self.admin = [
            m["id"] for m in self.members
        ]

    def call(self, fn, *args, **kwargs):
        with db.get_cursor() as cur:
            return fn(cur, *args, **kwargs)

    def sql(self, query, values=()):
        with db.get_cursor() as cur:
            cur.execute(query, values)
            return cur.fetchall() if cur.description else []

    def deliver_at(self, payload, at=None):
        with patch.object(
            s, "now", return_value=at or datetime(2026, 12, 12, 6, tzinfo=s.TZ)
        ):
            n.deliver(payload)

    def published(self):
        self.call(s.book, self.lead, DAY, "LEAD", True)
        self.call(s.save_details, self.lead, DAY, DETAILS, True)
        self.call(s.admin_action, self.admin, DAY, "APPROVE")

    def step(self, token, response, **data):
        return f.exchange(
            {
                "flow_token": token,
                "action": "data_exchange",
                "screen": response["screen"],
                "data": {"revision": response["data"]["revision"], **data},
            }
        )

    def test_T01_T02_seed_idempotent_and_additive(self):
        self.call(migration.upgrade)
        self.assertEqual(
            [
                str(r["run_date"])
                for r in self.sql(
                    "SELECT run_date FROM festive_run_slots ORDER BY run_date"
                )
            ],
            list(s.DATES),
        )
        self.assertEqual(upgrade_database(), [])
        self.assertEqual(len(self.sql("SELECT id FROM members")), 4)
        self.assertEqual(self.sql("SELECT * FROM submissions"), [])

    def test_T03_T05_T06_host_and_cohost_multiple_dates(self):
        self.call(s.book, self.lead, DAY, "LEAD")
        self.call(s.book, self.lead, DAY, "LEAD")
        self.call(s.book, self.cohost, DAY, "COHOST")
        self.call(s.book, self.lead, "2026-12-15", "LEAD")
        self.assertEqual(
            len(self.sql("SELECT * FROM festive_run_hosts WHERE status='ACTIVE'")), 3
        )
        with self.assertRaises(s.FestiveError):
            self.call(s.book, self.runner, DAY, "COHOST")

    def test_T04_concurrent_lead_host_single_winner(self):
        def request(actor):
            try:
                self.call(s.book, actor, DAY, "LEAD")
                return "saved"
            except s.FestiveError:
                return "unavailable"

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(request, (self.lead, self.cohost)))
        self.assertCountEqual(results, ["saved", "unavailable"])
        self.assertEqual(
            len(self.sql("SELECT * FROM festive_run_hosts WHERE status='ACTIVE'")), 1
        )

    def test_database_partial_unique_index_rejects_bypass(self):
        import psycopg2

        self.call(s.book, self.lead, DAY, "LEAD")
        with self.assertRaises(psycopg2.IntegrityError):
            self.sql(
                "INSERT INTO festive_run_hosts(run_slot_id,member_id,host_role) SELECT id,%s,'LEAD' FROM festive_run_slots WHERE run_date=%s",
                (self.cohost, DAY),
            )

    def test_T07_T08_T09_drafts_and_ownership(self):
        self.call(s.book, self.lead, DAY, "LEAD")
        self.call(s.save_details, self.lead, DAY, {"meeting_point": "Private draft"})
        self.call(s.save_details, self.lead, DAY, DETAILS)
        with self.assertRaises(s.FestiveError):
            self.call(s.save_details, self.runner, DAY, DETAILS)
        public = self.call(s.calendar, self.runner)[0]
        self.assertNotIn("draft", public)
        self.assertIsNone(public["published"])
        self.assertNotIn("Test public park", s.public_summary(public))
        self.assertIn("draft", self.call(s.calendar, self.lead)[0])

    def test_T10_T11_T13_T14_T15_T16_T17_rsvp_lifecycle(self):
        with self.assertRaises(s.FestiveError):
            self.call(s.rsvp, self.runner, DAY, "5km")
        self.published()
        for distance in ("5km", "5km", "10km"):
            self.call(s.rsvp, self.runner, DAY, distance, True)
        rows = self.sql("SELECT * FROM festive_run_rsvps")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["selected_distance"], "10km")
        mine = self.call(s.calendar, self.runner)[0]
        self.assertEqual(mine["mine"]["selected_distance"], "10km")
        self.assertEqual(mine["rsvp_count"], 1)
        self.call(s.withdraw_rsvp, self.runner, DAY)
        self.call(s.withdraw_rsvp, self.runner, DAY)
        self.assertEqual(
            self.sql("SELECT status FROM festive_run_rsvps")[0]["status"], "WITHDRAWN"
        )

    def test_T18_withdraw_unpublished_releases_slot(self):
        self.call(s.book, self.lead, DAY, "LEAD")
        self.call(s.book, self.cohost, DAY, "COHOST")
        self.call(s.withdraw_host, self.lead, DAY)
        self.call(s.book, self.runner, DAY, "LEAD")
        self.assertEqual(
            len(self.sql("SELECT * FROM festive_run_hosts WHERE status='ACTIVE'")), 1
        )

    def test_T18_T23_published_withdrawal_cancels_and_preserves_rsvp(self):
        self.published()
        self.call(s.rsvp, self.runner, DAY, "5km", True)
        self.call(s.withdraw_host, self.lead, DAY)
        self.assertEqual(self.call(s.calendar, self.runner)[0]["status"], "CANCELLED")
        self.assertEqual(
            self.sql("SELECT status FROM festive_run_rsvps")[0]["status"], "ACTIVE"
        )
        with self.assertRaises(s.FestiveError):
            self.call(s.rsvp, self.runner, DAY, "5km")
        self.assertEqual(
            self.sql("SELECT notification_type FROM festive_run_notifications")[0][
                "notification_type"
            ],
            "CANCELLED",
        )
        self.call(s.admin_action, self.admin, DAY, "REOPEN")
        self.call(s.admin_action, self.admin, DAY, "REASSIGN", replacement=self.cohost)
        self.assertIsNone(self.call(s.calendar, self.runner)[0]["published"])

    def test_T19_amendments_require_review_and_create_one_notice(self):
        self.published()
        self.call(s.rsvp, self.runner, DAY, "5km", True)
        self.call(
            s.save_details,
            self.lead,
            DAY,
            {**DETAILS, "meeting_point": "New test venue"},
            True,
        )
        self.assertEqual(
            self.call(s.calendar, self.runner)[0]["published"]["meeting_point"],
            DETAILS["meeting_point"],
        )
        self.call(s.admin_action, self.admin, DAY, "APPROVE")
        self.assertEqual(
            self.call(s.calendar, self.runner)[0]["published"]["meeting_point"],
            "New test venue",
        )
        self.assertEqual(len(self.sql("SELECT * FROM festive_run_notifications")), 1)
        with self.assertRaises(s.FestiveError):
            self.call(s.admin_action, self.admin, DAY, "APPROVE")

    def test_T20_host_72_admin_48_year_boundary(self):
        day = "2027-01-02"
        self.call(s.book, self.lead, day, "LEAD", True)
        self.call(s.save_details, self.lead, day, DETAILS)
        n.schedule(datetime(2026, 12, 30, 6, tzinfo=s.TZ))
        rows = self.sql(
            "SELECT notification_type,scheduled_for FROM festive_run_notifications ORDER BY notification_type"
        )
        times = {
            r["notification_type"]: r["scheduled_for"].astimezone(s.TZ) for r in rows
        }
        self.assertEqual(times["HOST_72"], datetime(2026, 12, 30, 6, tzinfo=s.TZ))
        self.assertEqual(times["ADMIN_48"], datetime(2026, 12, 31, 6, tzinfo=s.TZ))

    def test_T21_T22_24_hour_reminder_idempotent_simulation(self):
        self.published()
        self.call(s.rsvp, self.runner, DAY, "5km", True)
        when = datetime(2026, 12, 12, 6, tzinfo=s.TZ)
        n.schedule(when)
        n.schedule(when)
        rows = self.sql("SELECT * FROM festive_run_notifications")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["scheduled_for"].astimezone(s.TZ), when)
        jobs = self.sql("SELECT * FROM job_queue WHERE job_type='festive_notification'")
        self.assertEqual(len(jobs), 1)
        with patch.object(s, "now", return_value=when):
            _dispatch_job("festive_notification", jobs[0]["payload"])
            _dispatch_job("festive_notification", jobs[0]["payload"])
        self.assertEqual(
            self.sql("SELECT status FROM festive_run_notifications")[0]["status"],
            "SIMULATED",
        )

    def test_missing_templates_block_without_send(self):
        self.published()
        self.call(s.rsvp, self.runner, DAY, "5km", True)
        with patch.dict(os.environ, {"FESTIVE_NOTIFICATION_TEMPLATE": ""}):
            n.schedule(datetime(2026, 12, 12, 6, tzinfo=s.TZ))
        self.assertEqual(
            self.sql("SELECT status FROM festive_run_notifications")[0]["status"],
            "BLOCKED_TEMPLATE",
        )
        self.assertEqual(
            self.sql("SELECT * FROM job_queue WHERE job_type='festive_notification'"),
            [],
        )

    def test_notification_timeout_never_automatically_resends(self):
        import requests

        self.published()
        self.call(s.rsvp, self.runner, DAY, "5km", True)
        n.schedule(datetime(2026, 12, 12, 6, tzinfo=s.TZ))
        payload = self.sql(
            "SELECT payload FROM job_queue WHERE job_type='festive_notification'"
        )[0]["payload"]
        with (
            patch.dict(os.environ, {"FESTIVE_UAT_MODE": "false"}),
            patch.object(n.requests, "post", side_effect=requests.Timeout) as post,
        ):
            self.deliver_at(payload)
            self.deliver_at(payload)
            self.assertEqual(post.call_count, 1)
        self.assertEqual(
            self.sql("SELECT status FROM festive_run_notifications")[0]["status"],
            "UNCERTAIN",
        )

    def test_opt_out_rechecked_at_delivery(self):
        self.published()
        self.call(s.rsvp, self.runner, DAY, "5km", True)
        n.schedule(datetime(2026, 12, 12, 6, tzinfo=s.TZ))
        self.call(s.withdraw_rsvp, self.runner, DAY)
        self.deliver_at(
            self.sql(
                "SELECT payload FROM job_queue WHERE job_type='festive_notification'"
            )[0]["payload"]
        )
        self.assertEqual(
            self.sql("SELECT status FROM festive_run_notifications")[0]["status"],
            "SUPPRESSED",
        )

    def test_T24_unauthorized_admin_actions(self):
        self.call(s.book, self.lead, DAY, "LEAD")
        self.call(s.save_details, self.lead, DAY, DETAILS, True)
        with self.assertRaises(s.FestiveError):
            self.call(s.admin_action, self.runner, DAY, "APPROVE")
        with self.assertRaises(s.FestiveError):
            f.create_session(self.runner, "ADMIN")

    def test_invalid_past_dates_distance_and_rollback(self):
        for day in ("2026-12-14", "not-date", "2027-02-01"):
            with self.assertRaises(s.FestiveError):
                self.call(s.book, self.lead, day, "LEAD")
        with (
            patch.object(s, "now", return_value=datetime(2027, 1, 4, tzinfo=s.TZ)),
            self.assertRaises(s.FestiveError),
        ):
            self.call(s.book, self.lead, DAY, "LEAD")
        with self.assertRaises(RuntimeError), db.get_cursor() as cur:
            s.book(cur, self.lead, DAY, "LEAD")
            raise RuntimeError("simulate rollback")
        self.assertEqual(self.sql("SELECT * FROM festive_run_hosts"), [])
        self.published()
        with self.assertRaises(s.FestiveError):
            self.call(s.rsvp, self.runner, DAY, "42km")

    def test_inactive_member_and_erasure_release_host_safely(self):
        self.call(s.book, self.lead, DAY, "LEAD")
        self.sql(
            "UPDATE members SET popia_acknowledged=FALSE WHERE id=%s", (self.runner,)
        )
        with self.assertRaises(s.FestiveError):
            self.call(s.book, self.runner, "2026-12-15", "LEAD")
        self.sql("DELETE FROM members WHERE id=%s", (self.lead,))
        self.assertEqual(
            self.sql("SELECT status,member_id FROM festive_run_hosts")[0],
            {"status": "WITHDRAWN", "member_id": None},
        )
        self.assertEqual(self.call(s.calendar)[0]["status"], "CANCELLED")

    def test_flow_host_complete_journey_and_retry_receipt(self):
        token, response = f.create_session(self.lead, "HOST")
        self.assertEqual(len(response["data"]["options"]), 14)
        response = self.step(token, response, choice=DAY, role="LEAD", reminders=True)
        request = {
            "flow_token": token,
            "action": "data_exchange",
            "screen": "BOOK",
            "data": {"revision": response["data"]["revision"], "confirm": True},
        }
        response = f.exchange(request)
        self.assertEqual(response["screen"], "DETAILS")
        self.assertEqual(f.exchange(request), response)
        response = self.step(token, response, **DETAILS, save_mode="submit")
        self.assertEqual(response["screen"], "REVIEW")
        response = self.step(token, response, confirm=True)
        self.assertEqual(response["screen"], "DONE")
        self.assertIn("admin review", f.completion(token, self.lead))
        self.assertEqual(
            self.sql("SELECT status FROM festive_run_slots WHERE run_date=%s", (DAY,))[
                0
            ]["status"],
            "PENDING_APPROVAL",
        )

    def test_flow_rsvp_and_manage_complete_journey(self):
        self.published()
        token, r = f.create_session(self.runner, "JOIN")
        r = self.step(token, r, choice=DAY)
        self.assertEqual(
            r["data"]["options"],
            [{"id": "5km", "title": "5km"}, {"id": "10km", "title": "10km"}],
        )
        r = self.step(token, r, distance="5km", reminders=True)
        r = self.step(token, r, confirm=True)
        self.assertEqual(r["screen"], "DONE")
        token, r = f.create_session(self.runner, "MANAGE")
        self.assertEqual(r["data"]["options"][0]["id"], "r:" + DAY)
        r = self.step(token, r, choice="r:" + DAY)
        r = self.step(token, r, choice="withdraw_rsvp")
        r = self.step(token, r, confirm=True)
        self.assertEqual(r["screen"], "DONE")
        self.assertEqual(
            self.sql("SELECT status FROM festive_run_rsvps")[0]["status"], "WITHDRAWN"
        )

    def test_dynamic_availability_server_revalidation(self):
        a, ra = f.create_session(self.lead, "HOST")
        b, rb = f.create_session(self.cohost, "HOST")
        ra = self.step(a, ra, choice=DAY, role="LEAD")
        rb = self.step(b, rb, choice=DAY, role="LEAD")
        self.step(a, ra, confirm=True)
        rb = self.step(b, rb, confirm=True)
        self.assertEqual(rb["screen"], "BOOK")
        self.assertIn("taken", rb["data"]["error"])
        self.assertEqual(len(self.sql("SELECT * FROM festive_run_hosts")), 1)

    def test_stale_rsvp_review_rejected_after_material_change(self):
        self.published()
        token, r = f.create_session(self.runner, "JOIN")
        r = self.step(token, r, choice=DAY)
        r = self.step(token, r, distance="5km", reminders=True)
        self.call(
            s.save_details, self.lead, DAY, {**DETAILS, "start_time": "07:00"}, True
        )
        self.call(s.admin_action, self.admin, DAY, "APPROVE")
        r = self.step(token, r, confirm=True)
        self.assertIn("changed", r["data"]["error"])
        self.assertEqual(self.sql("SELECT * FROM festive_run_rsvps"), [])

    def test_flow_expiry_wrong_member_tampered_and_incomplete_completion(self):
        token, _r = f.create_session(self.lead, "HOST")
        with self.assertRaises(s.FestiveError):
            f.exchange({"flow_token": token, "action": "INIT"}, self.runner)
        with self.assertRaises(s.FestiveError):
            f.completion(token, self.lead)
        with self.assertRaises(s.FestiveError):
            f.exchange({"flow_token": "festive.bad", "action": "INIT"})
        self.sql("UPDATE festive_run_sessions SET expires_at=now()-interval '1 day'")
        with self.assertRaises(s.FestiveError):
            f.exchange({"flow_token": token, "action": "INIT"})

    def test_flow_back_resume_cancel(self):
        token, r = f.create_session(self.lead, "HOST")
        r = self.step(token, r, choice=DAY, role="LEAD")
        r = self.step(token, r, confirm=True)
        r = self.step(token, r, meeting_point="Partial", save_mode="draft")
        r = f.exchange({"flow_token": token, "action": "BACK", "screen": "DETAILS"})
        self.assertEqual(r["screen"], "DETAILS")
        self.assertEqual(r["data"]["meeting_point"], "Partial")
        self.assertEqual(
            f.exchange({"flow_token": token, "action": "INIT"})["screen"], "DETAILS"
        )
        r = self.step(token, r, intent="cancel")
        self.assertEqual(r["screen"], "DONE")
        self.assertEqual(len(self.sql("SELECT * FROM festive_run_hosts")), 1)

    def test_T12_T30_calendar_pagination_and_numbered_fallback(self):
        messages = []
        actions = SimpleNamespace(
            get_member=lambda phone: next(
                m for m in self.members if m["phone"] == phone
            )
        )
        with patch.object(
            t, "send", side_effect=lambda p, key=None: messages.append(p)
        ):
            chat.handle(actions, self.members[0]["phone"], "RUNS", None)
            rows = messages[-1]["interactive"]["action"]["sections"][0]["rows"]
            self.assertEqual(len(rows), 9)
            chat.handle(
                actions, self.members[0]["phone"], None, {"id": "festive:page:1"}
            )
            rows2 = messages[-1]["interactive"]["action"]["sections"][0]["rows"]
            self.assertEqual(len(rows2), 7)
            dates = {
                r["id"] for r in rows + rows2 if r["id"].startswith("festive:run:")
            }
            self.assertEqual(len(dates), 14)
            chat.handle(actions, self.members[0]["phone"], "FESTIVE TEXT", None)
            self.assertEqual(messages[-1]["type"], "text")
            chat.handle(actions, self.members[0]["phone"], "1", None)
            self.assertIn("Volunteer host needed", messages[-1]["text"]["body"])

    def test_fallback_host_runner_and_admin_uat(self):
        messages = []
        actions = SimpleNamespace(
            get_member=lambda phone: next(
                m for m in self.members if m["phone"] == phone
            )
        )

        def send(member_index, text=None, key=None):
            return chat.handle(
                actions,
                self.members[member_index]["phone"],
                text,
                {"id": key} if key else None,
            )

        def pick(member_index, option):
            state = chat.chat_state(self.members[member_index]["id"])
            index = next(
                i
                for i, o in enumerate(state["response"]["data"]["options"])
                if o["id"] == option
            )
            send(member_index, key=f"festive:pick:{state['revision']}:{index}")

        def confirm(member_index):
            send(
                member_index,
                key="festive:confirm:"
                + chat.chat_state(self.members[member_index]["id"])["revision"],
            )

        with patch.object(
            t, "send", side_effect=lambda p, key=None: messages.append(p)
        ):
            send(1, "HOST")
            pick(1, DAY)
            confirm(1)
            send(2, "HOST")
            pick(2, DAY)
            confirm(2)
            send(
                1,
                "\n".join(f"{k}={v}" for k, v in DETAILS.items())
                + "\nsave_mode=submit",
            )
            confirm(1)
            send(3, "FESTIVE ADMIN")
            pick(3, DAY)
            pick(3, "APPROVE")
            confirm(3)
            send(0, "RUNS")
            send(0, key="festive:run:" + DAY)
            send(0, "JOIN")
            pick(0, DAY)
            pick(0, "5km")
            send(0, key="festive:reminder:yes")
            confirm(0)
            send(0, "MY RUNS")
            self.assertEqual(
                chat.chat_state(self.runner)["response"]["data"]["options"][0]["id"],
                "r:" + DAY,
            )
            send(1, "MY HOSTS")
            pick(1, "h:" + DAY)
            self.assertIn(
                "5km: 1", chat.chat_state(self.lead)["response"]["data"]["summary"]
            )
            pick(1, "edit")
            send(1, "meeting_point=Changed test park\nsave_mode=submit")
            confirm(1)
            send(3, "FESTIVE ADMIN")
            pick(3, DAY)
            pick(3, "APPROVE")
            confirm(3)
            n.schedule(datetime.now(s.TZ) + timedelta(seconds=1))
            for job in self.sql(
                "SELECT payload FROM job_queue WHERE job_type='festive_notification'"
            ):
                self.deliver_at(job["payload"])
            self.assertEqual(
                self.sql(
                    "SELECT status FROM festive_run_notifications WHERE notification_type='CHANGED'"
                )[0]["status"],
                "SIMULATED",
            )
            send(0, "MY RUNS")
            pick(0, "r:" + DAY)
            pick(0, "withdraw_rsvp")
            confirm(0)
            send(1, "MY HOSTS")
            pick(1, "h:" + DAY)
            pick(1, "withdraw_host")
            confirm(1)
            send(3, "FESTIVE ADMIN")
            pick(3, DAY)
            pick(3, "REOPEN")
            confirm(3)
            self.assertEqual(self.call(s.calendar)[0]["status"], "OPEN")
        self.assertTrue(messages)
        self.assertEqual(self.sql("SELECT * FROM submissions"), [])

    def test_empty_calendar(self):
        self.sql("DELETE FROM festive_run_slots")
        _token, r = f.create_session(self.runner, "JOIN")
        self.assertEqual(r["data"]["options"], [])
        self.assertIn("No selections", r["data"]["summary"])

    def test_concurrent_flow_retries_one_mutation(self):
        token, r = f.create_session(self.lead, "HOST")
        r = self.step(token, r, choice=DAY, role="LEAD")
        request = {
            "flow_token": token,
            "action": "data_exchange",
            "screen": "BOOK",
            "data": {"revision": r["data"]["revision"], "confirm": True},
        }
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: f.exchange(request), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(len(self.sql("SELECT * FROM festive_run_hosts")), 1)

    def test_consent_withdrawal_cancels_hosted_run_and_queues_alert(self):
        self.published()
        self.call(s.rsvp, self.runner, DAY, "5km", True)
        self.sql(
            "UPDATE members SET popia_acknowledged=FALSE,popia_withdrawn_at=now() WHERE id=%s",
            (self.lead,),
        )
        self.assertFalse(
            self.sql(
                "SELECT popia_acknowledged FROM members WHERE id=%s", (self.lead,)
            )[0]["popia_acknowledged"]
        )
        self.assertEqual(self.call(s.calendar)[0]["status"], "CANCELLED")
        self.assertEqual(
            self.sql("SELECT notification_type FROM festive_run_notifications")[0][
                "notification_type"
            ],
            "CANCELLED",
        )
        with self.assertRaises(s.FestiveError):
            self.call(s.rsvp, self.runner, DAY, "5km")

    def test_festive_webhook_duplicate_and_failed_reply_retry(self):
        from fastapi import BackgroundTasks

        from app import webhook

        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "id": "festive-webhook-retry",
                                        "from": self.members[1]["phone"],
                                        "type": "text",
                                        "text": {"body": "HOST"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        with patch.object(webhook, "get_member", return_value=self.members[1]):
            result = webhook.process_webhook_payload(payload, BackgroundTasks())
            again = webhook.process_webhook_payload(payload, BackgroundTasks())
        self.assertEqual(result["status"], "festive")
        self.assertEqual(again["status"], "duplicate")
        self.assertEqual(len(self.sql("SELECT * FROM festive_run_sessions")), 1)
        jobs = self.sql("SELECT * FROM job_queue WHERE job_type='festive_reply'")
        self.assertEqual(len(jobs), 1)
        _dispatch_job("festive_reply", jobs[0]["payload"])
        self.assertEqual(self.sql("SELECT * FROM submissions"), [])

    def test_help_and_tt_commands_escape_interrupted_form(self):
        actions = SimpleNamespace(get_member=lambda phone: self.members[1])
        with patch.object(t, "send"):
            chat.handle(actions, self.members[1]["phone"], "HOST", None)
            self.assertIsNone(
                chat.handle(actions, self.members[1]["phone"], "HELP", None)
            )
        self.assertEqual(chat.chat_state(self.lead), {})

    def test_draft_pin_survives_native_form_edit(self):
        self.call(s.book, self.lead, DAY, "LEAD")
        self.call(
            s.save_details,
            self.lead,
            DAY,
            {**DETAILS, "latitude": -25.9, "longitude": 28.2},
        )
        self.call(s.save_details, self.lead, DAY, {**DETAILS, "title": "Updated title"})
        self.assertEqual(
            self.call(s.calendar, self.lead)[0]["draft"]["latitude"], -25.9
        )

    def test_rescheduled_reminder_does_not_send_from_stale_job(self):
        self.published()
        self.call(s.rsvp, self.runner, DAY, "5km", True)
        when = datetime(2026, 12, 12, 6, tzinfo=s.TZ)
        n.schedule(when)
        old_job = self.sql(
            "SELECT payload FROM job_queue WHERE job_type='festive_notification'"
        )[0]["payload"]
        self.call(
            s.save_details, self.lead, DAY, {**DETAILS, "start_time": "08:00"}, True
        )
        self.call(s.admin_action, self.admin, DAY, "APPROVE")
        n.schedule(when)
        self.deliver_at(old_job, when)
        self.assertEqual(
            self.sql(
                "SELECT status FROM festive_run_notifications WHERE notification_type='RUN_24'"
            )[0]["status"],
            "PENDING",
        )
        later = when + timedelta(hours=2)
        n.schedule(later)
        self.deliver_at(old_job, later)
        self.assertEqual(
            self.sql(
                "SELECT status FROM festive_run_notifications WHERE notification_type='RUN_24'"
            )[0]["status"],
            "SIMULATED",
        )

    def test_template_send_contract_and_successful_retry_no_duplicate(self):
        self.published()
        self.call(s.rsvp, self.runner, DAY, "5km", True)
        n.schedule(datetime(2026, 12, 12, 6, tzinfo=s.TZ))
        payload = self.sql(
            "SELECT payload FROM job_queue WHERE job_type='festive_notification'"
        )[0]["payload"]
        response = SimpleNamespace(
            ok=True, json=lambda: {"messages": [{"id": "wamid.fake-test"}]}
        )
        with (
            patch.dict(os.environ, {"FESTIVE_UAT_MODE": "false"}),
            patch.object(n.requests, "post", return_value=response) as post,
        ):
            self.deliver_at(payload)
            self.deliver_at(payload)
            self.assertEqual(post.call_count, 1)
            message = post.call_args.kwargs["json"]
        self.assertEqual(message["type"], "template")
        self.assertEqual(
            message["template"]["components"][1]["sub_type"], "quick_reply"
        )
        self.assertIn(
            "06:00 at Test public park",
            message["template"]["components"][0]["parameters"][1]["text"],
        )
        self.assertEqual(
            self.sql("SELECT status FROM festive_run_notifications")[0]["status"],
            "SENT",
        )

    def test_signed_encrypted_endpoint_returns_dynamic_dates(self):
        import base64
        import hashlib
        import hmac
        import json
        from pathlib import Path

        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from fastapi.testclient import TestClient

        from app import festive_endpoint as endpoint
        from app.main import app

        token, _response = f.create_session(self.lead, "HOST")
        encode = lambda value: (
            base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
        )
        jwt_head, jwt_body = encode({"alg": "HS256"}), encode({"flow_token": token})
        jwt_sig = (
            base64.urlsafe_b64encode(
                hmac.new(
                    b"test-secret", f"{jwt_head}.{jwt_body}".encode(), hashlib.sha256
                ).digest()
            )
            .decode()
            .rstrip("=")
        )
        plain = {
            "version": "4.0",
            "action": "INIT",
            "flow_token": token,
            "flow_token_signature": f"{jwt_head}.{jwt_body}.{jwt_sig}",
        }
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        aes, iv = os.urandom(16), os.urandom(16)
        b64 = lambda value: base64.b64encode(value).decode()
        envelope = {
            "encrypted_aes_key": b64(
                private.public_key().encrypt(
                    aes,
                    padding.OAEP(
                        mgf=padding.MGF1(hashes.SHA256()),
                        algorithm=hashes.SHA256(),
                        label=None,
                    ),
                )
            ),
            "initial_vector": b64(iv),
            "encrypted_flow_data": b64(
                AESGCM(aes).encrypt(iv, json.dumps(plain).encode(), None)
            ),
        }
        raw = json.dumps(envelope).encode()
        signature = (
            "sha256=" + hmac.new(b"test-secret", raw, hashlib.sha256).hexdigest()
        )
        with (
            patch.dict(os.environ, {"FESTIVE_FLOW_PRIVATE_KEY_PATH": "/fake/key"}),
            patch.object(endpoint, "WHATSAPP_APP_SECRET", "test-secret"),
            patch.object(Path, "read_bytes", return_value=pem),
        ):
            result = TestClient(app).post(
                "/festive/flows",
                content=raw,
                headers={"x-hub-signature-256": signature},
            )
        self.assertEqual(result.status_code, 200)
        data = json.loads(
            AESGCM(aes).decrypt(
                bytes(b ^ 255 for b in iv), base64.b64decode(result.text), None
            )
        )
        self.assertEqual(data["screen"], "CHOOSE")
        self.assertEqual(len(data["data"]["options"]), 14)
