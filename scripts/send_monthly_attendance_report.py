import argparse
import sys
from pathlib import Path

# Support the documented `venv/bin/python scripts/send_monthly_attendance_report.py`
# invocation by making the repository package importable.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.monthly_attendance_report_service import (
    build_attendance_report,
    build_attendance_report_text,
    previous_month_report_date,
    send_monthly_attendance_report,
)


def main():
    parser = argparse.ArgumentParser(description="Send the Irene AC monthly TT attendance dashboard.")
    parser.add_argument("--report-date", help="Report end date in YYYY-MM-DD format. Defaults to today in South Africa.")
    parser.add_argument("--previous-month", action="store_true", help="Report on the last day of the previous month.")
    parser.add_argument("--dry-run", action="store_true", help="Build the report and print the text summary without emailing.")
    args = parser.parse_args()

    report_date = previous_month_report_date() if args.previous_month else args.report_date

    if args.dry_run:
        report = build_attendance_report(report_date)
        print(build_attendance_report_text(report))
        return

    result = send_monthly_attendance_report(report_date)
    print(
        "Monthly TT attendance report sent "
        f"for {result['report_date']}: "
        f"recipients={result['recipients']} "
        f"mtd_checkins={result['mtd_checkins']} "
        f"ytd_checkins={result['ytd_checkins']}"
    )


if __name__ == "__main__":
    main()
