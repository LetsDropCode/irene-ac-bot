# app/services/event_detection.py

from datetime import datetime, time
from typing import Optional

# ---- EVENT CONFIG ----
# Easy to adjust later or move to DB/admin panel

EVENTS = {
    "TT": {
        "weekday": 1,  # Tuesday (Mon=0)
        "open": time(17, 0),
        "close": time(22, 0),
    },
    "WEDLSD": {
        "weekday": 2,  # Wednesday
        "open": time(17, 0),
        "close": time(22, 0),
    },
    "SUNSOCIAL": {
        "weekday": 6,  # Sunday
        "open": time(5, 30),
        "close": time(22, 0),
    },
}

# ---- CORE LOGIC ----

def get_active_event(now: Optional[datetime] = None) -> Optional[str]:
    """
    Returns event code if submissions are open, else None
    """
    now = now or datetime.now()
    current_weekday = now.weekday()
    current_time = now.time()

    for event, config in EVENTS.items():
        if current_weekday != config["weekday"]:
            continue

        if config["open"] <= current_time <= config["close"]:
            return event

    return None