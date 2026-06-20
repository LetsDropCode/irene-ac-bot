import os
import unittest
from datetime import date, datetime
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from app.services import monthly_attendance_report_service as service


def row(member_id, event_date, first_name, last_name, participation_type, submitted=True, pending=False):
    return {
        "member_id": member_id,
        "event_date": event_date,
        "source": "whatsapp",
        "checked_in_at": datetime(event_date.year, event_date.month, event_date.day, 18, 0),
        "phone": f"2770000000{member_id}",
        "first_name": first_name,
        "last_name": last_name,
        "participation_type": participation_type,
        "submitted_result": submitted,
        "pending_result": pending,
    }


class MonthlyAttendanceReportServiceTests(unittest.TestCase):
    def sample_rows(self):
        return [
            row(1, date(2026, 1, 13), "Lindsay", "Bull", "RUNNER"),
            row(2, date(2026, 6, 2), "Mia", "Walker", "WALKER", submitted=False, pending=True),
            row(1, date(2026, 6, 9), "Lindsay", "Bull", "RUNNER"),
            row(3, date(2026, 6, 9), "Sam", "Both", "BOTH"),
        ]

    def test_build_attendance_report_splits_mtd_and_ytd(self):
        report = service.build_attendance_report(date(2026, 6, 30), rows=self.sample_rows())

        self.assertEqual(report["mtd"]["total_checkins"], 3)
        self.assertEqual(report["mtd"]["unique_members"], 3)
        self.assertEqual(report["mtd"]["events"], 2)
        self.assertEqual(report["mtd"]["submitted_results"], 2)
        self.assertEqual(report["mtd"]["missing_results"], 1)
        self.assertEqual(report["mtd"]["by_type"], {"RUNNER": 1, "WALKER": 1, "BOTH": 1, "UNKNOWN": 0})

        self.assertEqual(report["ytd"]["total_checkins"], 4)
        self.assertEqual(report["ytd"]["unique_members"], 3)
        self.assertEqual(report["ytd"]["events"], 3)
        self.assertEqual(report["ytd"]["top_members"][0]["name"], "Lindsay Bull")
        self.assertEqual(report["ytd"]["top_members"][0]["checkins"], 2)

    def test_dashboard_email_contains_html_and_csv_attachment(self):
        with patch.object(service.config, "SMTP_FROM_EMAIL", "bot@irenerunner.co.za"):
            report = service.build_attendance_report(date(2026, 6, 30), rows=self.sample_rows())
            message = service.build_attendance_email(report, recipients=("admin@example.com",))

        self.assertEqual(message["To"], "admin@example.com")
        self.assertIn("Irene AC TT Attendance Dashboard - June 2026", message["Subject"])

        body = message.get_body(preferencelist=("html",)).get_content()
        self.assertIn("Month to date", body)
        self.assertIn("Year to date", body)
        self.assertIn("YTD top attendees", body)

        attachments = list(message.iter_attachments())
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].get_filename(), "irene-ac-tt-attendance-ytd-2026-06-30.csv")
        self.assertIn("Lindsay Bull", attachments[0].get_content())
        self.assertIn("in_month_to_date", attachments[0].get_content())

    def test_send_monthly_attendance_report_uses_default_recipients(self):
        captured = []
        with patch.object(service, "fetch_attendance_rows", return_value=self.sample_rows()), patch.object(
            service.config,
            "SMTP_FROM_EMAIL",
            "bot@irenerunner.co.za",
        ), patch.object(service, "_send_email", side_effect=lambda message: captured.append(message)):
            result = service.send_monthly_attendance_report(date(2026, 6, 30))

        self.assertEqual(result["report_date"], "2026-06-30")
        self.assertEqual(result["recipients"], 2)
        self.assertEqual(result["mtd_checkins"], 3)
        self.assertEqual(result["ytd_checkins"], 4)
        self.assertEqual(captured[0]["To"], "bulllindsa@icloud.com, info@irenerunner.co.za")


if __name__ == "__main__":
    unittest.main()
