# app/services/event_detector.py
from datetime import datetime, time
import pytz

TZ = pytz.timezone("Africa/Johannesburg")

TT_START = time(16, 30)
TT_END = time(22, 30)

def is_tt_window() -> bool:
    now = datetime.now(TZ).time()
    return TT_START <= now <= TT_END