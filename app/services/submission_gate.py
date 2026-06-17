# app/services/submission_gate.py
from datetime import datetime, time
from zoneinfo import ZoneInfo

from app.db import get_cursor

SA_TZ = ZoneInfo("Africa/Johannesburg")
TT_DAY = 1  # Tuesday
TT_OPEN = time(17, 0)
TT_CLOSE = time(22, 30)


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
    except Exception as e:
        print("⚠️ Event config lookup failed:", str(e))
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


def ensure_tt_open(now=None, event: str = "TT"):
    now = now or datetime.now(SA_TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=SA_TZ)
    else:
        now = now.astimezone(SA_TZ)

    config = _gate_config(event)
    open_time = config["open_time"]
    close_time = config["close_time"]

    if now.weekday() != config["day_of_week"]:
        return False, "⛔ Time Trials only happen on *Tuesdays*."

    if now.time() < open_time:
        return False, f"⏱ Submissions open at *{open_time.strftime('%H:%M')}*."

    if now.time() > close_time:
        return False, f"⏱ Submissions close at *{close_time.strftime('%H:%M')}*."

    return True, None
