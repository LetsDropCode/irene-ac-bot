"""Weekly contract tests: pure rendering, controlled time and fake transports."""

import copy
import os
import unittest
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
from app.flows import festive_weekly_flow as flow
from app.services import festive_weekly_notifications as n
from app.services import festive_weekly_service as w

ENV = {
    "FESTIVE_WEEKLY_DIGEST_ENABLED": "true",
    "FESTIVE_RUNS_ENABLED": "true",
    "FESTIVE_WEEKLY_AUTO_GROUP_POST": "false",
    "FESTIVE_WEEKLY_DIGEST_TIME": "06:00",
    "FESTIVE_WEEKLY_DIGEST_TIMEZONE": "Africa/Johannesburg",
    "FESTIVE_WEEKLY_BOT_LINK": "https://wa.me/27999990000?text=RUNS",
}


def row(day="2026-12-15", status="PUBLISHED"):
    return {
        "run_date": date.fromisoformat(day),
        "status": status,
        "hosts": [
            {
                "host_role": "LEAD",
                "first_name": "Test",
                "last_name": "Host",
                "member_id": 44,
                "phone": "27999991234",
            }
        ],
        "draft": {"meeting_point": "PRIVATE SECRET PARK"},
        "rsvp_names": ["Private Runner"],
        "published": {
            "title": "Test adventure",
            "start_time": "05:30",
            "meeting_point": "Approved park",
            "location_description": "15km starts at 05:00",
            "distances": ["5km", "15km"],
            "walkers_welcome": True,
            "coffee_arrangements": "TBC",
        },
    }


class WeeklyContractTests(unittest.TestCase):
    def setUp(self):
        p = patch.dict(os.environ, ENV)
        p.start()
        self.addCleanup(p.stop)

    def render(self, rows, week=w.WEEKS[1]):
        return "\n\n".join(w.render(w.snapshot(rows, week), week, w.settings()[1]))

    def test_T01_four_mondays(self):
        self.assertEqual(
            [d.isoformat() for d in w.WEEKS],
            ["2026-12-07", "2026-12-14", "2026-12-21", "2026-12-28"],
        )
        self.assertTrue(all(d.weekday() == 0 for d in w.WEEKS))

    def test_T02_exact_fourteen_dates(self):
        rows = [row(day, "OPEN") for day in w.domain.DATES]
        grouped = [w.snapshot(rows, week) for week in w.WEEKS]
        self.assertEqual([len(g) for g in grouped], [1, 5, 4, 4])
        self.assertEqual([r["date"] for g in grouped for r in g], list(w.domain.DATES))

    def test_T03_monday_sunday_boundaries(self):
        rows = [row(d, "OPEN") for d in w.domain.DATES]
        for week in w.WEEKS:
            for item in w.snapshot(rows, week):
                self.assertLessEqual(week, date.fromisoformat(item["date"]))
                self.assertLessEqual(
                    date.fromisoformat(item["date"]), week + timedelta(days=6)
                )

    def test_T04_year_transition(self):
        text = self.render([row(d, "OPEN") for d in w.domain.DATES], w.WEEKS[-1])
        self.assertIn("03 January 2027", text)
        self.assertIn("SATURDAY, 2 JANUARY", text)
        self.assertNotIn("27 DECEMBER", text)

    def test_T05_local_schedule_and_missed_window(self):
        self.assertEqual(w.due_weeks(datetime(2026, 12, 7, 3, 59, tzinfo=UTC)), ())
        self.assertEqual(w.due_weeks(datetime(2026, 12, 7, 4, tzinfo=UTC)), w.WEEKS[:1])
        self.assertEqual(
            w.due_weeks(datetime(2026, 12, 16, 12, tzinfo=UTC)), w.WEEKS[:2]
        )
        with self.assertRaises(ValueError):
            w.due_weeks(datetime(2026, 12, 7, 6))

    def test_T06_approved_details_including_separate_distance_start(self):
        text = self.render([row()])
        for value in (
            "Test Host",
            "05:30",
            "15km starts at 05:00",
            "Approved park",
            "5km, 15km",
            "Walkers: Yes",
        ):
            self.assertIn(value, text)

    def test_T07_open_slots(self):
        text = self.render([row(status="OPEN")])
        self.assertIn("HOST NEEDED", text)
        self.assertNotIn("Approved park", text)
        self.assertNotIn("Test Host", text)

    def test_T08_assigned_incomplete(self):
        for status in ("HOST_ASSIGNED", "DETAILS_PENDING", "PENDING_APPROVAL"):
            text = self.render([row(status=status)])
            self.assertIn("Test Host", text)
            self.assertIn("Run details to follow!", text)
            self.assertNotIn("05:30", text)

    def test_T09_draft_never_leaks_or_changes_digest(self):
        a = row()
        b = copy.deepcopy(a)
        b["draft"] = {"meeting_point": "OTHER SECRET"}
        b["revision"] = 999
        b["rsvp_count"] = 900
        self.assertEqual(w.snapshot([a], w.WEEKS[1]), w.snapshot([b], w.WEEKS[1]))
        self.assertNotIn("PRIVATE", self.render([a]))

    def test_T10_chronology(self):
        text = self.render([row("2026-12-20"), row("2026-12-15")])
        self.assertLess(text.index("15 DECEMBER"), text.index("20 DECEMBER"))

    def test_T11_optional_missing(self):
        r = row()
        r["hosts"] = []
        r["published"] = {"meeting_point": "Approved park"}
        text = self.render([r])
        self.assertNotIn("Start:", text)
        self.assertNotIn("Walkers:", text)
        self.assertNotIn("Coffee afterwards:", text)
        self.assertNotIn("Hosted by:", text)

    def test_T12_no_fictional_start_venue_or_coffee(self):
        r = row()
        r["published"] = {}
        text = self.render([r])
        self.assertIn("details to follow", text)
        self.assertNotIn("Start:", text)
        self.assertNotIn("Meet:", text)
        self.assertNotIn("Coffee afterwards:", self.render([row()]))

    def test_T16_material_changes_label_all_approved_fields(self):
        before = w.snapshot([row()], w.WEEKS[1])
        after = copy.deepcopy(before)
        after[0]["details"]["start_time"] = "07:00"
        after[0]["details"]["meeting_point"] = "New approved park"
        changes, messages = w.correction(before, after)
        self.assertEqual(changes[0]["fields"], ["Start time", "Meeting point"])
        self.assertIn("New approved park", " ".join(messages))

    def test_T17_cancelled_notice_and_completed_excluded(self):
        before = w.snapshot([row()], w.WEEKS[1])
        after = w.snapshot([row(status="CANCELLED")], w.WEEKS[1])
        self.assertIn("cancelled", " ".join(w.correction(before, after)[1]))
        for state in ("CANCELLED", "COMPLETED"):
            self.assertNotIn("📅", self.render([row(status=state)]))

    def test_T18_host_change_and_vacancy_filled(self):
        before = w.snapshot([row()], w.WEEKS[1])
        r = row()
        r["hosts"][0]["first_name"] = "Replacement"
        changed = w.snapshot([r], w.WEEKS[1])
        self.assertIn("Host / co-host", w.differences(before, changed)[0]["fields"])
        open_before = w.snapshot([row(status="OPEN")], w.WEEKS[1])
        self.assertTrue(w.differences(open_before, changed))

    def test_T22_whatsapp_format_and_neat_split_no_truncation(self):
        r = row()
        r["published"].update(
            route_description="r" * 600,
            safety_notes="s" * 500,
            location_description="l" * 300,
            route_url="https://example.org/" + "x" * 450,
            maps_url="https://maps.google.com/" + "x" * 450,
        )
        rows = [
            {**r, "run_date": date.fromisoformat(day)} for day in w.domain.DATES[1:6]
        ]
        parts = w.render(w.snapshot(rows, w.WEEKS[1]), w.WEEKS[1], w.settings()[1])
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(p) <= 4096 for p in parts))
        self.assertEqual(" ".join(parts).count("s" * 500), 5)
        self.assertTrue(all("**" not in p for p in parts))
        self.assertIn("1/", parts[0])

    def test_T24_group_delivery_defaults_off_and_fail_closed(self):
        with (
            patch.dict(os.environ, {"FESTIVE_WEEKLY_AUTO_GROUP_POST": "true"}),
            self.assertRaisesRegex(w.domain.FestiveError, "not verified"),
        ):
            w.settings()

    def test_T25_stops_after_programme(self):
        self.assertEqual(w.due_weeks(datetime(2027, 1, 4, tzinfo=w.domain.TZ)), ())
        self.assertEqual(
            w.due_weeks(datetime(2027, 1, 3, 23, 59, tzinfo=w.domain.TZ)), w.WEEKS
        )

    def test_T26_empty_week(self):
        self.assertIn("No upcoming festive runs", self.render([]))

    def test_T28_expired_freeform_reply_suppressed(self):
        with (
            patch.dict(os.environ, {"FESTIVE_UAT_MODE": "false"}),
            patch.object(
                w.domain, "now", return_value=datetime(2026, 12, 8, tzinfo=w.domain.TZ)
            ),
            patch("app.whatsapp._send_direct") as send,
        ):
            flow.deliver_reply(
                {
                    "payload": {"to": "27999990000"},
                    "expires_at": "2026-12-07T23:00:00+02:00",
                }
            )
            send.assert_not_called()

    def test_T28_template_requires_explicit_readiness(self):
        with patch.dict(
            os.environ,
            {
                "FESTIVE_WEEKLY_NOTIFICATION_TEMPLATE": "",
                "FESTIVE_WEEKLY_TEMPLATE_APPROVED": "false",
            },
        ):
            self.assertFalse(n.template_ready())

    def test_T29_no_identity_contact_or_draft_fields_in_snapshot(self):
        r = row()
        r["published"]["meeting_point"] = (
            "Park contact +27 82 123 4567 or person@example.org"
        )
        text = self.render([r])
        for secret in (
            "27999991234",
            "+27 82 123 4567",
            "person@example.org",
            "Private Runner",
            "PRIVATE SECRET",
        ):
            self.assertNotIn(secret, text)
        self.assertEqual(
            set(w.snapshot([r], w.WEEKS[1])[0]), {"date", "status", "hosts", "details"}
        )

    def test_T30_disabled_means_no_database_or_output(self):
        with (
            patch.dict(os.environ, {"FESTIVE_WEEKLY_DIGEST_ENABLED": "false"}),
            patch.object(w, "get_cursor") as cur,
        ):
            self.assertEqual(w.schedule(), {"generated": 0})
            cur.assert_not_called()

    def test_config_missing_bot_link_never_fabricates_number(self):
        with (
            patch.dict(os.environ, {"FESTIVE_WEEKLY_BOT_LINK": ""}),
            self.assertRaisesRegex(w.domain.FestiveError, "verified bot"),
        ):
            w.settings()

    def test_cohost_and_approved_pin(self):
        r = row()
        r["hosts"].append(
            {"host_role": "COHOST", "first_name": "Co", "last_name": "Host"}
        )
        r["published"].update(latitude=-25.9, longitude=28.2, coffee_arrangements="yes")
        text = self.render([r])
        self.assertIn("Co-host: Co Host", text)
        self.assertIn("query=-25.9,28.2", text)
        self.assertIn("Coffee afterwards: Yes", text)

    def test_numbered_long_unbroken_sections_preserve_all_content(self):
        original = "X" * 9000
        parts = w.split_messages([original])
        self.assertEqual(sum(p.count("X") for p in parts), 9000)
        self.assertTrue(all(len(p) <= 4096 for p in parts))

    def test_unrelated_command_not_captured_by_weekly_menu(self):
        self.assertIsNone(
            flow.handle("ignored", 1, {"mode": "weekly"}, "RUNS", "", "RUNS")
        )

    def test_invalid_zone_fails_closed(self):
        with (
            patch.dict(os.environ, {"FESTIVE_WEEKLY_DIGEST_TIMEZONE": "UTC"}),
            self.assertRaises(w.domain.FestiveError),
        ):
            w.settings()

    def test_weekly_scheduler_failure_does_not_block_tt_runner(self):
        from app import main

        with (
            patch.object(main, "JOB_RUNNER_TOKEN", "secret"),
            patch.object(
                main,
                "queue_incomplete_submission_reminders",
                return_value={"queued": 0},
            ),
            patch.object(main, "queue_monthly_recaps", return_value={"queued": 0}),
            patch.object(
                main, "queue_monthly_attendance_email", return_value={"queued": 0}
            ),
            patch("app.services.festive_notifications.schedule"),
            patch.object(w, "schedule", side_effect=RuntimeError("offline")),
            patch.object(main, "run_due_jobs", return_value=1) as runner,
            self.assertLogs("app.main", level="ERROR"),
        ):
            result = main.run_jobs(x_job_token="secret")
        self.assertEqual(result["processed"], 1)
        runner.assert_called_once()

    def test_pending_approval_changes_do_not_trigger_revision(self):
        a, b = row(status="HOST_ASSIGNED"), row(status="PENDING_APPROVAL")
        self.assertEqual(w.snapshot([a], w.WEEKS[1]), w.snapshot([b], w.WEEKS[1]))
