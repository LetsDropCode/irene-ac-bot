"""Private monthly attendance goals and one optional recap per member/month."""

import os
from datetime import date, datetime, timedelta

from app.db import get_cursor
from app.services.engagement_service import SA_TZ
from app.services.job_queue_service import JOB_MONTHLY_RECAP, enqueue_job
from app.services.profile_formatter import _format_seconds
from app.services.proactive_template_service import proactive_template_payload

MONTHLY_GOAL = 3


def month_bounds(day: date):
    start = day.replace(day=1)
    end = (start + timedelta(days=32)).replace(day=1)
    return start, end


def previous_month(today=None):
    today = today or datetime.now(SA_TZ).date()
    return (today.replace(day=1) - timedelta(days=1)).replace(day=1)


def get_monthly_goal(member_id: int, today=None):
    today = today or datetime.now(SA_TZ).date()
    start, _ = month_bounds(today)
    with get_cursor(commit=False) as cur:
        cur.execute("""
            SELECT COUNT(DISTINCT event_date) AS attendance FROM attendance
            WHERE member_id = %s AND event = 'TT' AND event_date BETWEEN %s AND %s
        """, (member_id, start, today))
        return {"month": start, "attendance": cur.fetchone()["attendance"]}


def format_goal_line(data):
    count = data["attendance"]
    label = data["month"].strftime("%B")
    suffix = " · goal reached!" if count >= MONTHLY_GOAL else ""
    return f"🎯 {label} goal: {count} of {MONTHLY_GOAL} TT check-ins{suffix}"


def get_monthly_recap(member_id: int, month=None):
    start, end = month_bounds(month or previous_month())
    with get_cursor(commit=False) as cur:
        cur.execute("""
            SELECT COUNT(DISTINCT event_date) AS attendance FROM attendance
            WHERE member_id = %s AND event = 'TT' AND event_date >= %s AND event_date < %s
        """, (member_id, start, end))
        attendance = cur.fetchone()["attendance"]
        cur.execute("""
            SELECT COUNT(*) AS activities,
                COALESCE(SUM(CASE WHEN distance_text IN ('4', '6', '8')
                    THEN distance_text::integer ELSE 0 END), 0) AS distance_km
            FROM submissions
            WHERE member_id = %s AND activity = 'TT' AND status = 'COMPLETE'
              AND event_date >= %s AND event_date < %s
        """, (member_id, start, end))
        totals = cur.fetchone()
        # Compare matching distances against all history BEFORE this month.
        # Backdated entries use their event date; walks are never timed PBs.
        cur.execute("""
            SELECT distance_text,
                MIN(seconds) FILTER (WHERE event_date >= %s) AS best_seconds,
                MIN(seconds) FILTER (WHERE event_date < %s) AS previous_seconds
            FROM submissions
            WHERE member_id = %s AND activity = 'TT' AND status = 'COMPLETE'
              AND event_date < %s AND (mode = 'RUN' OR mode IS NULL)
              AND seconds > 0 AND distance_text IN ('4', '6', '8')
            GROUP BY distance_text
            HAVING COUNT(*) FILTER (WHERE event_date >= %s) > 0
            ORDER BY distance_text
        """, (start, start, member_id, end, start))
        bests = cur.fetchall()
    return {"month": start, "attendance": attendance, **totals, "bests": bests}


def recap_highlights(data):
    highlights = []
    for best in data["bests"]:
        current, previous = best["best_seconds"], best["previous_seconds"]
        if previous is None:
            highlights.append(f"First {best['distance_text']} km best: {_format_seconds(current)}")
        elif current < previous:
            highlights.append(f"{best['distance_text']} km PB: {_format_seconds(current)} "
                              f"(improved by {_format_seconds(previous - current)})")
    return highlights


def format_monthly_recap(data):
    lines = [f"📅 *Your {data['month']:%B %Y} TT recap*", "",
             f"TT check-ins: {data['attendance']}",
             f"Completed activities: {data['activities']}",
             f"Recorded distance: {data['distance_km']} km", format_goal_line(data)]
    lines.extend(recap_highlights(data))
    if not data["attendance"] and not data["activities"]:
        lines.append("No TT activity recorded for this month. Join in whenever you're ready.")
    lines.extend(["", "Distance includes results with a recorded distance; free-text walks aren't estimated.",
                  "RECAPS ON/OFF — optional monthly messages. MY GOAL — this month's progress."])
    return "\n".join(lines)


def recap_messages_available():
    return bool(os.getenv("WHATSAPP_MONTHLY_RECAP_TEMPLATE_NAME", "").strip())


def _recap_window(now):
    # Wait until last-month Tuesday results can be completed on Wednesday.
    # Three afternoons allow catch-up after short scheduler outages.
    return now.day <= 3 and 14 <= now.hour < 20


def queue_monthly_recaps(now=None):
    now = now or datetime.now(SA_TZ)
    now = now.replace(tzinfo=SA_TZ) if now.tzinfo is None else now.astimezone(SA_TZ)
    start, end = month_bounds(previous_month(now.date()))
    result = {"month": start.isoformat(), "queued": 0}
    if not _recap_window(now) or not recap_messages_available():
        return result
    with get_cursor() as cur:
        cur.execute("""
            SELECT m.id FROM members m
            WHERE m.popia_acknowledged = TRUE AND m.recaps_opt_in = TRUE
              AND EXISTS (SELECT 1 FROM attendance a WHERE a.member_id = m.id
                  AND a.event = 'TT' AND a.event_date >= %s AND a.event_date < %s)
              AND NOT EXISTS (SELECT 1 FROM job_queue q WHERE q.dedupe_key =
                  'monthly-recap:' || m.id::text || ':' || %s)
            ORDER BY m.id
            FOR SHARE OF m
        """, (start, end, start.isoformat()))
        for member in cur.fetchall():
            enqueue_job(JOB_MONTHLY_RECAP,
                        {"member_id": member["id"], "month": start.isoformat()},
                        dedupe_key=f"monthly-recap:{member['id']}:{start.isoformat()}", cursor=cur)
            result["queued"] += 1
    return result


def send_monthly_recap(payload, now=None):
    from app.whatsapp import _send_direct

    now = now or datetime.now(SA_TZ)
    now = now.replace(tzinfo=SA_TZ) if now.tzinfo is None else now.astimezone(SA_TZ)
    month = date.fromisoformat(payload["month"])
    if month != previous_month(now.date()) or now.day > 3:
        return False  # Never deliver stale recaps on a later retry.
    with get_cursor(commit=False) as cur:
        cur.execute("""
            SELECT phone FROM members WHERE id = %s
              AND popia_acknowledged = TRUE AND recaps_opt_in = TRUE
            FOR SHARE
        """, (payload["member_id"],))
        member = cur.fetchone()
        if not member:
            return False
        data = get_monthly_recap(payload["member_id"], month)
        if not data["attendance"]:
            return False
        message = proactive_template_payload(
            member["phone"], "WHATSAPP_MONTHLY_RECAP_TEMPLATE_NAME",
            [f"{month:%B %Y}", str(data["attendance"]), str(data["activities"]),
             str(data["distance_km"]),
             "Reached" if data["attendance"] >= MONTHLY_GOAL else f"{data['attendance']} of {MONTHLY_GOAL}",
             "; ".join(recap_highlights(data)) or "No new timed running best this month."],
        )
        if not _send_direct(message):
            raise RuntimeError("Monthly recap WhatsApp send returned false")
    return True
