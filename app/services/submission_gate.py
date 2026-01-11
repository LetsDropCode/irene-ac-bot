from datetime import datetime, time
import pytz

TZ = pytz.timezone("Africa/Johannesburg")

TT_DAY = 1          # Tuesday (Mon=0)
TT_START = time(16, 30)
TT_END = time(22, 30)


def ensure_tt_open():
    now = datetime.now(TZ)

    if now.weekday() != TT_DAY:
        return False, "⛔ Time Trials only happen on *Tuesdays*."

    if not (TT_START <= now.time() <= TT_END):
        return False, (
            "⏱ Time Trial submissions are open from "
            "*16:30 to 22:30*."
        )

    return True, None