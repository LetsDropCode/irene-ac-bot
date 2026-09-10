# app/services/submission_gate.py
from datetime import date, datetime, time, timedelta
import logging
from zoneinfo import ZoneInfo

from app.db import get_cursor

SA_TZ = ZoneInfo("Africa/Johannesburg")
TT_DAY = 1  # Tuesday
TT_OPEN = time(17, 0)
TT_CLOSE = time(22, 30)
NEXT_DAY_RESULT_DEADLINE = time(13, 0)
logger = logging.getLogger(__name__)


def _parse_time(value: str, fallback: time) -> time:
    if not value:
        return fallback

    try:
        hour, minute = value.split(":")[:2]
        return time(int(hour), int(minute))
    except (TypeError, ValueError):
        return fallback


def _get_event_config(event: str):
    try:
        with get_cursor(commit=False) as cur:
            cur.execute("""
                SELECT event, day_of_week, open_time, close_time, active
                FROM event_config
                WHERE event = %s
                  AND active = 1
                ORDER BY id DESC
                LIMIT 1
            """, (event,))
            return cur.fetchone()
    except Exception:
        # Database/driver exceptions may contain connection information.
        logger.error("Event configuration lookup failed")
        return None


def _gate_config(event: str):
    config = _get_event_config(event)

    if not config:
        return {
            "day_of_week": TT_DAY,
            "open_time": TT_OPEN,
            "close_time": TT_CLOSE,
        }

    return {
        "day_of_week": int(config.get("day_of_week", TT_DAY)),
        "open_time": _parse_time(config.get("open_time"), TT_OPEN),
        "close_time": _parse_time(config.get("close_time"), TT_CLOSE),
    }


def self_correctable_event_date(now=None, event: str = "TT"):
    """Return the one TT date a member may currently self-correct.

    This deliberately identifies the event date only; ``ensure_tt_open``
    remains responsible for enforcing the Tuesday window and Wednesday
    deadline. Keeping the configured TT weekday here prevents a Wednesday row
    from shadowing the completed Tuesday result.
    """
    now = now or datetime.now(SA_TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=SA_TZ)
    else:
        now = now.astimezone(SA_TZ)

    event_day = _gate_config(event)["day_of_week"]
    if now.weekday() == event_day:
        return now.date()
    if now.weekday() == (event_day + 1) % 7:
        return now.date() - timedelta(days=1)
    return None


def ensure_tt_open(now=None, event: str = "TT", submission_event_date: date | None = None):
    now = now or datetime.now(SA_TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=SA_TZ)
    else:
        now = now.astimezone(SA_TZ)

    config = _gate_config(event)
    open_time = config["open_time"]
    close_time = config["close_time"]

    # Members who checked in during the Tuesday window may finish the same
    # result until 13:00 the next day. Their submission keeps Tuesday's date.
    if submission_event_date == now.date() - timedelta(days=1):
        if submission_event_date.weekday() == config["day_of_week"] and now.time() <= NEXT_DAY_RESULT_DEADLINE:
            return True, None
        return False, (
            f"⛔ The deadline for the {submission_event_date.strftime('%-d %B')} TT was "
            f"*{NEXT_DAY_RESULT_DEADLINE.strftime('%H:%M')}* today."
        )

    if now.weekday() != config["day_of_week"]:
        return False, "⛔ Time Trials only happen on *Tuesdays*."

    if now.time() < open_time:
        return False, f"⏱ Submissions open at *{open_time.strftime('%H:%M')}*."

    if now.time() > close_time:
        return False, f"⏱ Submissions close at *{close_time.strftime('%H:%M')}*."

    return True, None
