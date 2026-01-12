from datetime import datetime
from zoneinfo import ZoneInfo

SA_TZ = ZoneInfo("Africa/Johannesburg")

TT_DAY = 1  # Tuesday
TT_START = datetime(16, 30)
TT_END = datetime(22, 30)

def ensure_tt_open():
    now = datetime.now(SA_TZ)

    if now.weekday() != TT_DAY:
        return False, "⛔ Time Trials only happen on *Tuesdays*."

    if not (TT_START <= now.time() <= TT_END):
        return False, "⏱ TT submissions are open from *16:30–22:30*."

    return True, None