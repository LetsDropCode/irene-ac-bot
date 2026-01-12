# app/services/time_utils.py

from datetime import datetime, time
from zoneinfo import ZoneInfo

SA_TZ = ZoneInfo("Africa/Johannesburg")


def now_sa() -> datetime:
    """Current datetime in South Africa"""
    return datetime.now(tz=SA_TZ)


def today_sa() -> datetime.date:
    return now_sa().date()


def is_tuesday_sa() -> bool:
    # Monday = 0, Tuesday = 1
    return now_sa().weekday() == 1


def after_time_sa(cutoff: time) -> bool:
    return now_sa().time() >= cutoff


def time_to_seconds(value: str) -> int:
    """
    Converts mm:ss or hh:mm:ss to seconds
    """
    parts = value.split(":")

    if len(parts) == 2:  # mm:ss
        minutes, seconds = parts
        return int(minutes) * 60 + int(seconds)

    if len(parts) == 3:  # hh:mm:ss
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + int(seconds)

    raise ValueError("Invalid time format")