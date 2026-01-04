# app/services/validation.py
from datetime import datetime
from app.services.event_detector import get_active_event

TT_ALLOWED_DISTANCES = {"4km", "6km", "8km"}

def validate_submission(parsed):
    """
    Returns (is_valid: bool, message: str, event: str | None)
    """

    if not parsed:
        return (
            False,
            "❌ I couldn’t understand that.\n\n"
            "Please send your result like this:\n"
            "*CODE 6km 24:12*",
            None,
        )

    # ✅ Always use server time
    now = datetime.now()
    event = get_active_event(now)

    if not event:
        return (
            False,
            "⏱️ Submissions are currently closed.\n"
            "Please try again during the official run window.",
            None,
        )

    distance = parsed["distance"]

    if event == "TT" and distance not in TT_ALLOWED_DISTANCES:
        return (
            False,
            "❌ Time Trial distances are *4km, 6km or 8km only*.",
            event,
        )

    return True, "OK", event