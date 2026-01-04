# app/services/validation.py
from app.services.event_detection import get_active_event

TT_ALLOWED_DISTANCES = {"4km", "6km", "8km"}

def validate_submission(parsed, now=None):
    """
    Returns (is_valid: bool, message: str, event: str | None)
    """
    if not parsed:
        return False, "❌ Format must be: CODE 6km 24:12", None

    event = get_active_event(now)
    if not event:
        return False, "⏱️ Submissions are currently closed.", None

    distance = parsed.get("distance")
    if not distance:
        return False, "❌ Distance is missing.", event

    if event == "TT" and distance not in TT_ALLOWED_DISTANCES:
        return False, "❌ TT distances are 4km, 6km or 8km only.", event

    return True, "OK", event