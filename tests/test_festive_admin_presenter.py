import os
import unittest
from datetime import date, datetime
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
from app.services import festive_admin_presenter as ui
from app.services import festive_service as domain


def run(status="OPEN", **changes):
    return {
        "run_date": date(2026, 12, 13),
        "status": status,
        "hosts": [],
        "rsvp_count": 0,
        "approval_status": None,
        "draft": {},
        "published": None,
        **changes,
    }


class CaptainPresenterTests(unittest.TestCase):
    def setUp(self):
        p = patch.object(
            domain, "now", return_value=datetime(2026, 11, 20, tzinfo=domain.TZ)
        )
        p.start()
        self.addCleanup(p.stop)

    def test_dashboard_counts_distinguish_cancelled_from_vacant(self):
        body, counts = ui.dashboard(
            [
                run(),
                run("CANCELLED"),
                run("PUBLISHED"),
                run("PENDING_APPROVAL", approval_status="PENDING"),
            ]
        )
        self.assertEqual(
            counts, {"review": 1, "open": 1, "pending": 0, "published": 1, "all": 4}
        )
        self.assertIn("1 hosting dates open", body)
        self.assertNotIn("PENDING_APPROVAL", body)

    def test_actions_match_status_and_date(self):
        cases = [
            (run(), ["REASSIGN", "CANCEL"]),
            (run("CANCELLED"), ["REOPEN"]),
            (run("COMPLETED"), []),
            (run("PUBLISHED"), ["CANCEL"]),
            (
                run("PUBLISHED", approval_status="PENDING"),
                ["APPROVE", "CHANGES", "CANCEL"],
            ),
        ]
        for row, expected in cases:
            self.assertEqual([o["id"] for o in ui.options(row)], expected)
        row = run("PUBLISHED", run_date=date(2026, 11, 19))
        self.assertEqual([o["id"] for o in ui.options(row)], ["COMPLETE"])
        self.assertEqual(ui.options(run(run_date=date(2026, 11, 19))), [])

    def test_pending_amendments_compare_to_public_details(self):
        body = ui.review(
            run(
                "PUBLISHED",
                approval_status="PENDING",
                published={"start_time": "06:00", "meeting_point": "Test park"},
                draft={"start_time": "06:30", "meeting_point": "Test park"},
            )
        )
        self.assertIn("Was: 06:00\nNow: 06:30", body)
        self.assertIn("Members still see the previous approved details", body)
        self.assertNotIn('"start_time"', body)
        self.assertNotIn("Meeting point changed", body)

    def test_missing_optional_boolean_and_removed_fields(self):
        text = ui.details(
            {"walkers_welcome": False, "coffee_arrangements": "TBC"},
            {"maps_url": "https://example.org/route"},
        )
        self.assertIn("Walkers welcome changed", text)
        self.assertIn("Now: No", text)
        self.assertIn("To be confirmed", text)
        self.assertIn("Now: Not supplied", text)
        self.assertNotIn("False", text)

    def test_draft_and_missing_required_fields_are_clear(self):
        text = ui.review(
            run(
                "DETAILS_PENDING",
                approval_status="DRAFT",
                draft={"meeting_point": "Test park"},
            )
        )
        self.assertIn("Private draft · not submitted", text)
        self.assertIn("Still needed:", text)
        self.assertIn("Start time", text)
        self.assertNotIn("Approve", text)

    def test_cancel_and_reopen_confirmation_explain_consequences(self):
        cancel = ui.confirmation(run("PUBLISHED"), "CANCEL")
        reopen = ui.confirmation(run("CANCELLED"), "REOPEN")
        self.assertIn("RSVPs are retained", cancel)
        self.assertIn("clears the current hosts and saved run details", reopen)
        self.assertIn("withdraws active RSVPs", reopen)

    def test_assignment_confirmation_names_member(self):
        text = ui.confirmation(
            run(),
            "REASSIGN",
            {"id": 17, "first_name": "Test", "last_name": "Volunteer"},
        )
        self.assertIn("*Test Volunteer* · member 17", text)
        self.assertIn("saved run details will be cleared", text)

    def test_long_notes_are_not_truncated(self):
        marker = "Last safety detail"
        data = {"route_description": "r" * 600, "safety_notes": "s" * 480 + marker}
        self.assertIn(
            marker,
            ui.review(run("PENDING_APPROVAL", approval_status="PENDING", draft=data)),
        )

    def test_review_queue_excludes_past_and_cancelled(self):
        self.assertFalse(
            ui.matches(run("CANCELLED", approval_status="PENDING"), "review")
        )
        self.assertFalse(
            ui.matches(
                run(
                    "PENDING_APPROVAL",
                    approval_status="PENDING",
                    run_date=date(2026, 11, 19),
                ),
                "review",
            )
        )

    def test_success_does_not_claim_host_message_sent(self):
        text = ui.success("CHANGES")
        self.assertIn("Ask the lead host", text)
        self.assertNotIn("sent", text)
