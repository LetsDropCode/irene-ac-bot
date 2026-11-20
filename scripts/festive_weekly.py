"""Read-only deployment check and copy-ready previews; never sends or persists.

Examples: python scripts/festive_weekly.py --check
          python scripts/festive_weekly.py --preview-week 2026-12-07
"""

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db import get_cursor
from app.services import festive_service as domain
from app.services import festive_weekly_service as weekly
from app.services.festive_config import flag
from app.services.festive_weekly_notifications import template_ready


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--preview-week", choices=[str(w) for w in weekly.WEEKS])
    args = parser.parse_args()
    if not args.check and not args.preview_week:
        parser.error("Choose --check or --preview-week")
    if args.check:
        error = None
        try:
            weekly.settings()
        except domain.FestiveError as exc:
            error = str(exc)
        with get_cursor(commit=False) as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute(
                "SELECT name FROM schema_migrations WHERE name='2026-11-20-festive-weekly-v1'"
            )
            migrated = bool(cur.fetchone())
            cur.execute(
                "SELECT run_date,status FROM festive_run_slots ORDER BY run_date"
            )
            calendar = cur.fetchall()
        print(
            json.dumps(
                {
                    "delivery_mode": "A: automatic generation + admin sharing",
                    "enabled": weekly.active(),
                    "configuration_error": error,
                    "migration_applied": migrated,
                    "calendar_dates": [str(r["run_date"]) for r in calendar],
                    "exact_programme_dates": tuple(str(r["run_date"]) for r in calendar)
                    == domain.DATES,
                    "schedule": {
                        "time": os.getenv("FESTIVE_WEEKLY_DIGEST_TIME", "06:00"),
                        "timezone": os.getenv(
                            "FESTIVE_WEEKLY_DIGEST_TIMEZONE", "Africa/Johannesburg"
                        ),
                        "editions": [str(w) for w in weekly.WEEKS],
                    },
                    "admin_notification_enabled": flag(
                        "FESTIVE_WEEKLY_ADMIN_NOTIFICATION_ENABLED"
                    ),
                    "approved_template_configured": template_ready(),
                    "group_delivery_supported": False,
                },
                indent=2,
            )
        )
        if (
            error
            or not migrated
            or tuple(str(r["run_date"]) for r in calendar) != domain.DATES
        ):
            return 1
    if args.preview_week:
        week = date.fromisoformat(args.preview_week)
        _, link = weekly.settings()
        with get_cursor(commit=False) as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            rows = domain.calendar(cur)
        for part in weekly.render(weekly.snapshot(rows, week), week, link):
            print(part, end="\n\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
