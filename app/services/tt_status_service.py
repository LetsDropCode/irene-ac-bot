"""One compact, attendance-based event summary for both admin entry points."""

from datetime import datetime

from app.db import get_cursor
from app.services.engagement_service import MILESTONES, SA_TZ
from app.services.monthly_engagement_service import MONTHLY_GOAL


def get_event_summary(event_date=None):
    event_date = event_date or datetime.now(SA_TZ).date()
    with get_cursor(commit=False) as cur:
        cur.execute("""
            SELECT m.id, m.first_name, m.last_name, m.participation_type,
                h.total, h.month_total,
                EXISTS (SELECT 1 FROM submissions s WHERE s.member_id = m.id
                    AND s.activity = 'TT' AND s.event_date = %s
                    AND s.status = 'COMPLETE') AS completed,
                (SELECT MAX(s.created_at) FROM submissions s WHERE s.member_id = m.id
                    AND s.activity = 'TT' AND s.event_date = %s
                    AND s.status = 'COMPLETE') AS last_submission_at,
                h.total = 1 AND NOT EXISTS (
                    SELECT 1 FROM submissions s WHERE s.member_id = m.id
                        AND s.activity = 'TT' AND s.status = 'COMPLETE' AND s.event_date < %s
                ) AS first_timer
            FROM attendance a JOIN members m ON m.id = a.member_id
            JOIN LATERAL (
                SELECT COUNT(DISTINCT event_date) AS total,
                    COUNT(DISTINCT event_date) FILTER (WHERE event_date >= %s) AS month_total
                FROM attendance WHERE member_id = m.id AND event = 'TT' AND event_date <= %s
            ) h ON TRUE
            WHERE a.event = 'TT' AND a.event_date = %s AND m.popia_acknowledged = TRUE
            ORDER BY a.created_at, m.id
        """, (event_date, event_date, event_date, event_date.replace(day=1), event_date, event_date))
        rows = cur.fetchall()

    pending = [row for row in rows if not row["completed"]]
    milestones = [row for row in rows if row["total"] in MILESTONES and row["total"] > 1]
    times = [row["last_submission_at"] for row in rows if row["last_submission_at"]]
    summary = {
        "checked_in": len(rows), "submitted": len(rows) - len(pending), "pending": len(pending),
        "runners": sum(row["participation_type"] == "RUNNER" for row in rows),
        "walkers": sum(row["participation_type"] == "WALKER" for row in rows),
        "both": sum(row["participation_type"] == "BOTH" for row in rows),
        "first_timers": sum(row["first_timer"] for row in rows),
        "monthly_goals_reached": sum(row["month_total"] == MONTHLY_GOAL for row in rows),
        "milestones": len(milestones), "last_submission_at": max(times) if times else None,
    }
    return {"event_date": event_date, "summary": summary, "pending": pending[:5],
            "milestones": milestones[:3]}


def format_event_summary(data):
    summary = data.get("summary") or {}
    pending = data.get("pending") or []
    names = ", ".join(f"{row['first_name']} {row['last_name']}"[:70] for row in pending) or "None"
    remaining = (summary.get("pending") or 0) - len(pending)
    if remaining > 0:
        names += f" (+{remaining} more)"
    milestones = data.get("milestones") or []
    milestone_names = ", ".join(
        f"{row['first_name']} {row['last_name']}"[:70] + f" ({row['total']})" for row in milestones
    ) or "None"
    remaining_milestones = (summary.get("milestones") or 0) - len(milestones)
    if remaining_milestones > 0:
        milestone_names += f" (+{remaining_milestones} more)"
    last = summary.get("last_submission_at")
    lines = [f"Event: {data['event_date']}"] if data.get("event_date") else []
    lines.extend([
        f"Checked in: {summary.get('checked_in') or 0}",
        f"Submitted: {summary.get('submitted') or 0}",
        f"Pending: {summary.get('pending') or 0}",
        "Runners / Walkers / Both: "
        f"{summary.get('runners') or 0} / {summary.get('walkers') or 0} / {summary.get('both') or 0}",
        f"First recorded TTs: {summary.get('first_timers') or 0}",
        f"Monthly goals reached today: {summary.get('monthly_goals_reached') or 0}",
        f"Attendance milestones: {milestone_names}",
        f"Last submission: {last.strftime('%H:%M') if last else 'none yet'}", "",
        f"Top pending: {names}", "Send PENDING for follow-up tools.",
    ])
    return "\n".join(lines)


def get_tt_status():
    return "📋 *TT event summary*\n\n" + format_event_summary(get_event_summary())
