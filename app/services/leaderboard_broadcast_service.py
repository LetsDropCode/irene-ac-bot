from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.services.leaderboard_formatter import format_full_leaderboard
from app.services.job_queue_service import enqueue_whatsapp_text
from app.services.leaderboard_service import (
    get_checked_in_tt_member_phones,
    get_runner_leaderboard,
    get_walker_feed,
)

SA_TZ = ZoneInfo("Africa/Johannesburg")


def yesterday_sa():
    return datetime.now(SA_TZ).date() - timedelta(days=1)


def build_next_day_leaderboard_message(event_date):
    runners = get_runner_leaderboard(event_date)
    walkers = get_walker_feed(event_date)

    if not runners and not walkers:
        return None

    date_label = event_date.strftime("%d %b")
    leaderboard = format_full_leaderboard(
        runners,
        walkers,
        title=f"Yesterday's TT Leaderboard ({date_label})",
    )

    return (
        "Morning TT crew 🔥\n\n"
        f"{leaderboard}\n\n"
        "Thanks for showing up. See you at the next one."
    )


def send_next_day_leaderboard(event_date=None):
    event_date = event_date or yesterday_sa()
    recipients = get_checked_in_tt_member_phones(event_date)
    message = build_next_day_leaderboard_message(event_date)

    if not recipients or not message:
        return {
            "event_date": event_date.isoformat(),
            "queued": 0,
            "skipped": len(recipients),
        }

    queued = 0
    for phone in recipients:
        if enqueue_whatsapp_text(phone, message):
            queued += 1

    return {
        "event_date": event_date.isoformat(),
        "queued": queued,
        "skipped": len(recipients) - queued,
    }
