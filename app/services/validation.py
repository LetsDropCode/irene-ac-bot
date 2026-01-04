# app/services/validation.py

from datetime import datetime, date
from app.services.event_detector import get_active_event
from app.services.event_codes import is_valid_code

TT_ALLOWED_DISTANCES = {"4km", "6km", "8km"}


def validate_submission(parsed, now=None):
    """
    Validates a parsed submission.
    Returns: (is_valid: bool, message: str, event: str | None)
    """

    if not parsed:
        return False, "❌ Format must be: CODE 6km 24:12", None

    now = now or datetime.now()

    # ----------------------------------
    # Detect active event
    # ----------------------------------
    event = get_active_event(now)

    if not event:
        return False, "⏱️ Submissions are currently closed.", None

    distance = parsed["distance"]
    time = parsed["time"]
    code = parsed["code"]

    # ----------------------------------
    # Distance validation
    # ----------------------------------
    if event == "TT" and distance not in TT_ALLOWED_DISTANCES:
        return False, "❌ TT distances are 4km, 6km or 8km only.", event

    # ----------------------------------
    # Code validation
    # ----------------------------------
    if not is_valid_code(event, code):
        return False, "❌ Invalid or expired run code.", event

    return True, "OK", event