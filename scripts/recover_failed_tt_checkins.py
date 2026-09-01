"""Recover valid TT-code messages that failed during the 1 September outage.

Only inbound messages marked with the known post-validation database error are
eligible. This lets us restore their check-in without treating arbitrary failed
messages as valid TT codes.
"""

import argparse
from datetime import date

from app.db import get_cursor
from app.services.attendance_service import mark_attendance
from app.services.member_service import get_member
from app.services.submission_service import get_or_create_submission, verify_tt_code
from app.whatsapp import send_both_submission_buttons, send_distance_buttons, send_text

FAILURE_TEXT = "no results to fetch"


def affected_senders(event_date: date) -> list[str]:
    with get_cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT DISTINCT sender
            FROM inbound_whatsapp_messages
            WHERE status = 'FAILED'
              AND error = %s
              AND (received_at AT TIME ZONE 'Africa/Johannesburg')::date = %s
            ORDER BY sender
            """,
            (FAILURE_TEXT, event_date),
        )
        return [row["sender"] for row in cur.fetchall() if row.get("sender")]


def get_event_code(event_date: date) -> str | None:
    with get_cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT code
            FROM event_codes
            WHERE event = 'TT' AND event_date = %s
            LIMIT 1
            """,
            (event_date,),
        )
        row = cur.fetchone()
        return row["code"] if row else None


def send_next_step(phone: str, participation_type: str | None):
    send_text(
        phone,
        "✅ Your TT check-in has been restored for Tuesday, 1 September. "
        "Please continue with your result below.",
    )
    if participation_type == "WALKER":
        send_text(phone, "🚶 Send a short note about your walk or workout, e.g. 45 min walk.")
    elif participation_type == "BOTH":
        send_both_submission_buttons(phone)
    else:
        send_distance_buttons(phone)


def recover(event_date: date, dry_run: bool = False) -> int:
    code = get_event_code(event_date)
    if not code:
        raise RuntimeError(f"No TT code exists for {event_date.isoformat()}.")

    senders = affected_senders(event_date)
    if dry_run:
        return len(senders)

    recovered = 0
    for phone in senders:
        member = get_member(phone)
        if not member:
            continue

        submission = get_or_create_submission(member["id"])
        if not submission:
            continue

        if not submission.get("tt_code_verified"):
            verify_tt_code(submission["id"], code)
            mark_attendance(member["id"])

        send_next_step(phone, member.get("participation_type"))
        recovered += 1

    return recovered


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="2026-09-01", type=date.fromisoformat)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    count = recover(args.date, dry_run=args.dry_run)
    print(f"{'Would recover' if args.dry_run else 'Recovered'} {count} member(s).")
