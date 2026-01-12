from datetime import datetime, time
from zoneinfo import ZoneInfo

# South Africa timezone (no pytz needed)
SA_TZ = ZoneInfo("Africa/Johannesburg")

# TT submission window (Phase 1 rule)
TT_CLOSE_TIME = time(22, 30)  # 22:30 local time


def ensure_tt_open() -> bool:
    """
    Returns True if TT submissions are currently allowed.
    Submissions automatically close daily at 22:30 (SA time).
    """
    now = datetime.now(SA_TZ).time()
    return now < TT_CLOSE_TIME


def tt_status_message() -> str:
    """
    Human-readable TT status message for members.
    """
    if ensure_tt_open():
        return "⏱️ Time Trial submissions are OPEN.\nPlease submit your distance and time."
    return (
        "🚫 Time Trial submissions are CLOSED.\n"
        "Submissions close daily at 22:30.\n"
        "Please try again tomorrow."
    )