# app/services/event_detection.py

from datetime import datetime, time
from zoneinfo import ZoneInfo

# South Africa time
TZ = ZoneInfo("Africa/Johannesburg")

# Event windows (easy to adjust later)
EVENT_WINDOWS = {
    "TT": {
        "day": 1,  # Tuesday (Monday=0)
        "start": time(17, 0),
        "end": time(22, 0),
    },
    "WEDLSD": {
        "day": 2,  # Wednesday
        "start": time(17, 0),
        "end": time(22, 0),
    },
    "SUNSOCIAL": {
        "day": 6,  # Sunday
        "start": time(5, 30),
        "end": time(22, 0),
    },
}


def get_active_event(now: datetime | None = None) -> str | None:
    """
    Returns:
        "TT", "WEDLSD", "SUNSOCIAL" or None
    """
    if not now:
        now = datetime.now(TZ)

    current_day = now.weekday()
    current_time = now.time()

    for event, rules in EVENT_WINDOWS.items():
        if (
            current_day == rules["day"]
            and rules["start"] <= current_time <= rules["end"]
        ):
            return event

    return None