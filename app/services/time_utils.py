from datetime import datetime, time
import pytz

TZ = pytz.timezone("Africa/Johannesburg")

TT_DAY = 1  # Tuesday (Mon=0)
TT_START = time(16, 30)
TT_END = time(22, 30)

def now_local():
    return datetime.now(TZ)

def is_tt_day():
    return now_local().weekday() == TT_DAY

def is_tt_window_open():
    now = now_local().time()
    return TT_START <= now <= TT_END

def tt_status():
    if not is_tt_day():
        return "not_tt_day"
    if not is_tt_window_open():
        return "closed"
    return "open"