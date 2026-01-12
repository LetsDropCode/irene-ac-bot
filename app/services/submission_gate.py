from datetime import datetime, time
from zoneinfo import ZoneInfo

SA_TZ = ZoneInfo("Africa/Johannesburg")
TT_DAY = 1  # Tuesday
TT_CLOSE = time(22, 30)


def ensure_tt_open():
    now = datetime.now(SA_TZ)

    if now.weekday() != TT_DAY:
        return False, "⛔ Time Trials only happen on *Tuesdays*."

    if now.time() > TT_CLOSE:
        return False, "⏱ Submissions close at *22:30*."

    return True, None