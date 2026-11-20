"""Real PostgreSQL captain journeys. All outbound transports are mocked."""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import festive_runs_integration as base

from app.flows import festive_admin_flow as admin
from app.flows import festive_flow as chat
from app.services import festive_flow_service as flow


@unittest.skipUnless(base.SAFE, "requires disposable local integration database")
class CaptainUXIntegrationTests(unittest.TestCase):
    call = base.FestiveIntegrationTests.call
    sql = base.FestiveIntegrationTests.sql
    published = base.FestiveIntegrationTests.published
    step = base.FestiveIntegrationTests.step

    def setUp(self):
        base.FestiveIntegrationTests.setUp(self)
        self.messages = []
        p = patch.object(
            base.t,
            "send",
            side_effect=lambda payload, key=None: self.messages.append(payload),
        )
        p.start()
        self.addCleanup(p.stop)
        self.actions = SimpleNamespace(
            get_member=lambda phone: next(
                m for m in self.members if m["phone"] == phone
            )
        )

    def send(self, text=None, key=None, who=3):
        return chat.handle(
            self.actions, self.members[who]["phone"], text, {"id": key} if key else None
        )

    def pick(self, option):
        state = chat.chat_state(self.admin)
        index = next(
            i
            for i, o in enumerate(state["response"]["data"]["options"])
            if o["id"] == option
        )
        return self.send(key=f"festive:pick:{chat.callback_revision(state)}:{index}")

    def open_run(self):
        self.send("FESTIVE ADMIN")
        self.send(key=admin.PREFIX + "queue:all")
        self.pick(base.DAY)

    def confirm(self):
        state = chat.chat_state(self.admin)
        return self.send(key="festive:confirm:" + chat.callback_revision(state))

    def test_native_dashboard_and_weekly_shortcut(self):
        with patch.dict(os.environ, {"FESTIVE_WEEKLY_DIGEST_ENABLED": "true"}):
            self.send("FESTIVE ADMIN")
        rows = self.messages[-1]["interactive"]["action"]["sections"][0]["rows"]
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[0]["title"], "Ready for review")
        self.assertEqual(rows[-1]["id"], admin.PREFIX + "weekly")

    def test_text_empty_review_queue_and_return_home(self):
        self.send("FESTIVE ADMIN TEXT")
        self.assertIn("1. Ready for review", self.messages[-1]["text"]["body"])
        self.send("1")
        self.assertIn("You're all caught up", self.messages[-1]["text"]["body"])
        self.send("1")
        self.assertEqual(chat.chat_state(self.admin)["mode"], "admin_home")

    def test_readable_review_approval_and_next_review(self):
        self.call(base.s.book, self.lead, base.DAY, "LEAD")
        self.call(base.s.save_details, self.lead, base.DAY, base.DETAILS, True)
        self.send("FESTIVE ADMIN")
        self.send(key=admin.PREFIX + "queue:review")
        self.pick(base.DAY)
        text = chat.chat_state(self.admin)["response"]["data"]["summary"]
        self.assertIn("Start time: 06:00", text)
        self.assertNotIn('"meeting_point"', text)
        self.pick("APPROVE")
        self.assertIn(
            "become visible", chat.chat_state(self.admin)["response"]["data"]["summary"]
        )
        self.confirm()
        self.assertEqual(self.call(base.s.calendar)[0]["status"], "PUBLISHED")
        self.assertIn("Next review", str(self.messages[-1]))
        self.assertEqual(self.sql("SELECT * FROM submissions"), [])

    def test_name_search_assignment_confirm_and_back(self):
        self.open_run()
        self.pick("REASSIGN")
        self.send("Cohost")
        state = chat.chat_state(self.admin)
        target = next(k for k in state["shown"] if ":assign:" in k)
        self.assertNotIn(self.members[2]["phone"], str(self.messages[-1]))
        self.send(key=target)
        self.assertIn(
            "Cohost Test", chat.chat_state(self.admin)["response"]["data"]["summary"]
        )
        self.assertEqual(self.sql("SELECT * FROM festive_run_hosts"), [])
        self.confirm()
        self.assertEqual(
            self.sql("SELECT member_id FROM festive_run_hosts WHERE status='ACTIVE'")[
                0
            ]["member_id"],
            self.cohost,
        )

    def test_name_search_text_numbered_selection_and_back(self):
        self.send("FESTIVE ADMIN TEXT")
        self.send("2")
        self.pick(base.DAY)
        self.pick("REASSIGN")
        self.send("Cohost")
        self.send("1")
        self.assertEqual(chat.chat_state(self.admin)["screen"], "REVIEW")
        self.send("BACK")
        self.assertEqual(chat.chat_state(self.admin)["screen"], "ACTION")
        self.assertEqual(self.sql("SELECT * FROM festive_run_hosts"), [])

    def test_search_back_returns_to_run_without_reassignment(self):
        self.open_run()
        self.pick("REASSIGN")
        self.send("BACK")
        self.assertEqual(chat.chat_state(self.admin)["screen"], "ACTION")
        self.assertFalse(chat.chat_state(self.admin)["replacement_pending"])

    def test_search_does_not_swallow_runs_or_weekly_commands(self):
        self.open_run()
        self.pick("REASSIGN")
        self.send("RUNS")
        self.assertEqual(chat.chat_state(self.admin)["mode"], "calendar")

    def test_search_excludes_nonconsenting_and_treats_wildcards_literally(self):
        self.sql(
            "UPDATE members SET popia_acknowledged=FALSE WHERE id=%s", (self.cohost,)
        )
        self.open_run()
        self.pick("REASSIGN")
        self.send("Cohost")
        self.assertIn("No eligible member", self.messages[-1]["text"]["body"])
        self.send("%%")
        self.assertIn("No eligible member", self.messages[-1]["text"]["body"])

    def test_nonadmins_cannot_open_hub_search_or_use_forged_buttons(self):
        for text, key in [
            ("FESTIVE ADMIN", None),
            (None, admin.PREFIX + "queue:all"),
            (None, admin.PREFIX + "search"),
        ]:
            self.send(text, key, who=0)
            self.assertIn("administrator", self.messages[-1]["text"]["body"])
        self.assertEqual(self.sql("SELECT * FROM festive_run_sessions"), [])

    def test_stale_draft_is_not_approved_without_review(self):
        self.call(base.s.book, self.lead, base.DAY, "LEAD")
        self.call(base.s.save_details, self.lead, base.DAY, base.DETAILS, True)
        token, r = flow.create_session(self.admin, "ADMIN")
        r = self.step(token, r, choice=base.DAY)
        self.call(
            base.s.save_details,
            self.lead,
            base.DAY,
            {**base.DETAILS, "start_time": "07:00"},
            True,
        )
        r = self.step(token, r, choice="APPROVE")
        self.assertEqual(r["screen"], "ACTION")
        self.assertIn("changed", r["data"]["error"])
        self.assertEqual(self.call(base.s.calendar)[0]["status"], "PENDING_APPROVAL")

    def test_back_from_confirmation_refreshes_amended_draft(self):
        self.call(base.s.book, self.lead, base.DAY, "LEAD")
        self.call(base.s.save_details, self.lead, base.DAY, base.DETAILS, True)
        token, r = flow.create_session(self.admin, "ADMIN")
        r = self.step(token, r, choice=base.DAY)
        r = self.step(token, r, choice="APPROVE")
        self.call(
            base.s.save_details,
            self.lead,
            base.DAY,
            {**base.DETAILS, "start_time": "07:00"},
            True,
        )
        r = flow.exchange(
            {"flow_token": token, "action": "BACK", "screen": "REVIEW"}, self.admin
        )
        self.assertIn("07:00", r["data"]["summary"])
        r = self.step(token, r, choice="APPROVE")
        r = self.step(token, r, confirm=True)
        self.assertEqual(r["screen"], "DONE")
        self.assertEqual(
            self.call(base.s.calendar)[0]["published"]["start_time"], "07:00"
        )

    def test_old_review_buttons_cannot_confirm_new_session(self):
        self.open_run()
        self.pick("CANCEL")
        old = chat.callback_revision(chat.chat_state(self.admin))
        self.open_run()
        self.pick("CANCEL")
        self.send(key="festive:confirm:" + old)
        self.assertIn("old", self.messages[-1]["text"]["body"])
        self.assertEqual(self.call(base.s.calendar)[0]["status"], "OPEN")

    def test_same_lead_selection_keeps_existing_draft(self):
        self.call(base.s.book, self.lead, base.DAY, "LEAD")
        self.call(base.s.save_details, self.lead, base.DAY, base.DETAILS)
        token, r = flow.create_session(self.admin, "ADMIN")
        r = self.step(token, r, choice=base.DAY)
        r = self.step(token, r, choice="REASSIGN", replacement=self.lead)
        self.assertIn("already the lead", r["data"]["error"])
        self.assertEqual(
            self.sql("SELECT draft FROM festive_run_details")[0]["draft"][
                "meeting_point"
            ],
            base.DETAILS["meeting_point"],
        )

    def test_long_review_is_sent_in_full_and_menu_body_is_short(self):
        self.call(base.s.book, self.lead, base.DAY, "LEAD")
        details = {
            **base.DETAILS,
            "route_description": "r" * 600,
            "safety_notes": "s" * 480 + "LAST NOTE",
            "location_description": "l" * 300,
            "maps_url": "https://example.org/" + ("x" * 450),
            "route_url": "https://example.org/" + ("y" * 450),
        }
        self.call(base.s.save_details, self.lead, base.DAY, details, True)
        self.open_run()
        self.assertIn(
            "LAST NOTE",
            " ".join(m.get("text", {}).get("body", "") for m in self.messages),
        )
        self.assertLessEqual(
            len(self.messages[-1]["interactive"]["body"]["text"]), 1024
        )
        self.assertTrue(
            all(len(m.get("text", {}).get("body", "")) <= 4096 for m in self.messages)
        )

    def test_history_pages_keep_all_fourteen_dates(self):
        self.send("FESTIVE ADMIN")
        self.send(key=admin.PREFIX + "queue:all")
        first = chat.chat_state(self.admin)
        self.assertEqual(len(first["response"]["data"]["options"]), 14)
        self.assertLessEqual(len(first["shown"]), 10)
        self.send(key="festive:page:1")
        self.assertEqual(chat.chat_state(self.admin)["page"], 1)

    def test_member_search_pagination_and_search_again(self):
        for i in range(10):
            self.sql(
                "INSERT INTO members(phone,first_name,last_name,popia_acknowledged) VALUES (%s,%s,'Test',TRUE)",
                (f"279999910{i:02}", f"Volunteer {i}"),
            )
        self.open_run()
        self.pick("REASSIGN")
        self.send("Volunteer")
        state = chat.chat_state(self.admin)
        self.assertEqual(len(state["search_results"]), 9)
        self.assertLessEqual(len(state["shown"]), 10)
        self.send(key="festive:page:1")
        self.assertEqual(chat.chat_state(self.admin)["page"], 1)
        self.send(key=admin.PREFIX + "search")
        self.assertEqual(chat.chat_state(self.admin)["mode"], "admin_search")
        self.send("Volunteer 9")
        state = chat.chat_state(self.admin)
        self.assertEqual(len(state["search_results"]), 1)
        self.send(key=state["shown"][0])
        self.assertIn(
            "Volunteer 9", chat.chat_state(self.admin)["response"]["data"]["summary"]
        )

    def test_weekly_shortcut_and_return_to_captain_desk(self):
        from app.flows import festive_weekly_flow as weekly_ui

        with (
            patch.dict(os.environ, {"FESTIVE_WEEKLY_DIGEST_ENABLED": "true"}),
            patch.object(weekly_ui, "send", side_effect=self.messages.append),
        ):
            self.send("FESTIVE ADMIN")
            self.send(key=admin.PREFIX + "weekly")
            self.assertEqual(chat.chat_state(self.admin)["mode"], "weekly")
            self.assertIn("FESTIVE ADMIN", str(self.messages[-1]))
            self.send("FESTIVE ADMIN")
            self.assertEqual(chat.chat_state(self.admin)["mode"], "admin_home")

    def test_cancel_confirmation_distinguishes_closing_menu(self):
        self.open_run()
        self.pick("CANCEL")
        buttons = self.messages[-1]["interactive"]["action"]["buttons"]
        self.assertEqual(
            [b["reply"]["title"] for b in buttons],
            ["Cancel this run", "Back", "Close menu"],
        )
