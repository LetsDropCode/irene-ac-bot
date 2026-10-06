"""One Wednesday reminder for consented members with unfinished TT results."""

from datetime import date, datetime, time, timedelta

from app.db import get_cursor
from app.services.job_queue_service import JOB_INCOMPLETE_REMINDER, enqueue_job
from app.services.proactive_template_service import proactive_template_payload
from app.services.submission_gate import NEXT_DAY_RESULT_DEADLINE, SA_TZ, TT_DAY

REMINDER_START = time(11, 0)


def _reminder_window(now: datetime) -> bool:
    return (
        now.weekday() == (TT_DAY + 1) % 7
        and REMINDER_START <= now.time() < NEXT_DAY_RESULT_DEADLINE
    )


def get_incomplete_submissions(event_date: date):
    with get_cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT s.id AS submission_id, s.member_id
            FROM submissions s
            JOIN members m ON m.id = s.member_id
            WHERE s.event_date = %s AND s.activity = 'TT' AND s.status = 'PENDING'
              AND s.tt_code_verified = TRUE
              AND m.popia_acknowledged = TRUE
              AND m.reminders_opt_in = TRUE
            ORDER BY s.id
            """,
            (event_date,),
        )
        return cur.fetchall()


def queue_incomplete_submission_reminders(now: datetime | None = None):
    """Run Wednesday before 13:00 SAST; dedupe by submission row."""
    now = now or datetime.now(SA_TZ)
    now = now.replace(tzinfo=SA_TZ) if now.tzinfo is None else now.astimezone(SA_TZ)
    event_date = now.date() - timedelta(days=1)
    if not _reminder_window(now):
        return {"event_date": event_date.isoformat(), "queued": 0, "outside_window": True}

    queued = 0
    for row in get_incomplete_submissions(event_date):
        enqueue_job(
            JOB_INCOMPLETE_REMINDER,
            {
                "submission_id": row["submission_id"],
                "member_id": row["member_id"],
                "event_date": event_date.isoformat(),
            },
            dedupe_key=f"incomplete-reminder:{row['submission_id']}",
        )
        queued += 1
    return {"event_date": event_date.isoformat(), "queued": queued, "outside_window": False}


def send_incomplete_submission_reminder(payload: dict) -> bool:
    """Recheck eligibility at delivery; never send after confirm/deadline."""
    from app.whatsapp import _send_direct

    now = datetime.now(SA_TZ)
    event_date = date.fromisoformat(payload["event_date"])
    if not _reminder_window(now) or event_date != now.date() - timedelta(days=1):
        return False

    with get_cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT m.phone, m.first_name
            FROM submissions s
            JOIN members m ON m.id = s.member_id
            WHERE s.id = %s AND s.member_id = %s AND s.event_date = %s
              AND s.activity = 'TT'
              AND s.status = 'PENDING' AND s.tt_code_verified = TRUE
              AND m.popia_acknowledged = TRUE AND m.reminders_opt_in = TRUE
            FOR SHARE OF s, m
            """,
            (payload["submission_id"], payload["member_id"], event_date),
        )
        member = cur.fetchone()
        if not member:
            return False
        if not _reminder_window(datetime.now(SA_TZ)):
            return False
        payload = proactive_template_payload(
            member["phone"],
            "WHATSAPP_REMINDER_TEMPLATE_NAME",
            [member["first_name"] or "there"],
        )
        if not _send_direct(payload):
            raise RuntimeError("Reminder WhatsApp send returned false")
    return True
