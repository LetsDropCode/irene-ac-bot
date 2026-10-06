"""Private attendance streaks and member-controlled proactive messages."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.db import get_cursor
from app.services.job_queue_service import JOB_ATTENDANCE_MILESTONE, JOB_INCOMPLETE_REMINDER
from app.services.proactive_template_service import proactive_template_payload

SA_TZ = ZoneInfo("Africa/Johannesburg")
MILESTONES = (1, 5, 10, 25, 50, 100)
PREFERENCES = {
    "reminders": "reminders_opt_in",
    "milestones": "milestones_opt_in",
}


def set_engagement_preference(member_id: int, preference: str, enabled: bool) -> bool:
    """The column is selected from a fixed allowlist, never from user input."""
    column = PREFERENCES.get(preference)
    if column is None:
        raise ValueError("Unknown engagement preference")
    with get_cursor() as cur:
        cur.execute(
            f"UPDATE members SET {column} = %s "
            "WHERE id = %s AND popia_acknowledged = TRUE RETURNING id",
            (enabled, member_id),
        )
        if cur.fetchone() is None:
            return False
        if not enabled:
            job_type = JOB_INCOMPLETE_REMINDER if preference == "reminders" else JOB_ATTENDANCE_MILESTONE
            cur.execute(
                """
                DELETE FROM job_queue
                WHERE job_type = %s AND payload->>'member_id' = %s
                  AND status IN ('PENDING', 'FAILED')
                """,
                (job_type, str(member_id)),
            )
        return True


def _last_tuesday(today: date) -> date:
    return today - timedelta(days=(today.weekday() - 1) % 7)


def calculate_attendance_stats(event_dates, today: date):
    """Calculate TT-only weekly streaks from distinct attendance dates."""
    dates = sorted({
        day for value in event_dates
        if (day := value.date() if isinstance(value, datetime) else value).weekday() == 1
    })
    longest = 0
    run = 0
    previous = None
    for event_date in dates:
        run = run + 1 if previous and event_date - previous == timedelta(days=7) else 1
        longest = max(longest, run)
        previous = event_date

    last_tuesday = _last_tuesday(today)
    # A member has until this week's Tuesday check-in to extend their streak.
    # On Tuesday itself, last week's attendance is still current.
    current_dates = {last_tuesday}
    if today.weekday() == 1:
        current_dates.add(last_tuesday - timedelta(days=7))
    current = run if dates and dates[-1] in current_dates else 0
    total = len(dates)
    return {
        "total": total,
        "current_streak": current,
        "longest_streak": longest,
        "latest_date": dates[-1] if dates else None,
        "next_milestone": next((target for target in MILESTONES if total < target), None),
    }


def get_attendance_stats(member_id: int, today: date | None = None):
    today = today or datetime.now(SA_TZ).date()
    with get_cursor(commit=False) as cur:
        cur.execute(
            "SELECT event_date FROM attendance WHERE member_id = %s AND event = 'TT' "
            "AND event_date <= %s ORDER BY event_date",
            (member_id, today),
        )
        dates = [row["event_date"] for row in cur.fetchall()]
    return calculate_attendance_stats(dates, today)


def format_streak_summary(stats: dict) -> str:
    next_target = stats["next_milestone"]
    next_line = (
        f"Next attendance milestone: {next_target} check-ins "
        f"({next_target - stats['total']} to go)."
        if next_target else "You have reached every listed attendance milestone."
    )
    return (
        "🏃 *Your TT attendance*\n\n"
        f"Check-ins: {stats['total']}\n"
        f"Current weekly streak: {stats['current_streak']}\n"
        f"Longest weekly streak: {stats['longest_streak']}\n"
        f"{next_line}\n\n"
        "Send MILESTONES ON for private milestone messages, or REMINDERS ON "
        "for unfinished-result reminders. Both are optional."
    )


def milestone_message(stats: dict) -> str | None:
    total = stats["total"]
    streak = stats["current_streak"]
    if total not in MILESTONES and streak < 2:
        return None
    lines = ["🎉 *Your Irene AC TT attendance*"]
    if total in MILESTONES:
        lines.append(f"You reached {total} TT check-in{'s' if total != 1 else ''}!")
    if streak >= 2:
        lines.append(f"Your weekly TT streak is now {streak}.")
    lines.append("Send MILESTONES OFF anytime to stop these messages.")
    return "\n".join(lines)


def send_attendance_milestone(payload: dict) -> bool:
    """Recheck consent and opt-in under a lock before network delivery."""
    from app.whatsapp import _send_direct

    member_id = payload["member_id"]
    event_date = date.fromisoformat(payload["event_date"])
    with get_cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT m.phone FROM members m
            JOIN attendance a ON a.member_id = m.id
            WHERE m.id = %s AND a.event = 'TT' AND a.event_date = %s
              AND m.popia_acknowledged = TRUE AND m.milestones_opt_in = TRUE
            FOR SHARE OF m, a
            """,
            (member_id, event_date),
        )
        member = cur.fetchone()
        if not member:
            return False
        stats = get_attendance_stats(member_id, today=event_date)
        message = milestone_message(stats)
        if not message:
            return False
        payload = proactive_template_payload(
            member["phone"],
            "WHATSAPP_MILESTONE_TEMPLATE_NAME",
            [str(stats["total"]), str(stats["current_streak"])],
        )
        if not _send_direct(payload):
            raise RuntimeError("Milestone WhatsApp send returned false")
    return True
