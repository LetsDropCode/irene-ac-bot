# app/services/validation.py

from app.services.event_detection import get_active_event

TT_ALLOWED_DISTANCES = {"4km", "6km", "8km"}


def validate_submission(parsed: dict | None, now=None):
    """
    Validates a parsed submission.

    Returns:
        (is_valid: bool, message: str, event: str | None)
    """

    # 1️⃣ Parsing failed
    if parsed is None:
        return False, (
            "❌ Invalid format.\n\n"
            "Please submit like:\n"
            "4km 18:45 CODE"
        ), None

    # 2️⃣ Detect active event
    event = get_active_event(now)

    if event is None:
        return False, "⏱️ Submissions are currently closed.", None

    # 3️⃣ Defensive access (prevents KeyError)
    distance = parsed.get("distance")
    time_value = parsed.get("time")
    code = parsed.get("code")

    if not distance or not time_value or not code:
        return False, (
            "❌ Missing information.\n\n"
            "Format must be:\n"
            "4km 18:45 CODE"
        ), None

    # 4️⃣ TT-specific rules
    if event == "TT" and distance not in TT_ALLOWED_DISTANCES:
        return False, (
            "❌ Time Trial distances are:\n"
            "4km, 6km or 8km only."
        ), event

    # 5️⃣ Code validation placeholder (Phase 2B)
    # For now: format only, not value
    if len(code) < 3 or len(code) > 8:
        return False, "❌ Invalid code format.", event

    # ✅ All checks passed
    return True, "OK", event