# app/services/validation.py

from datetime import datetime, date
from app.db import get_db
from app.services.event_detector import get_active_event

TT_ALLOWED_DISTANCES = {"4km", "6km", "8km"}

def is_valid_code(event: str, code: str) -> bool:
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT 1
        FROM event_codes
        WHERE event = %s
          AND code = %s
          AND event_date = CURRENT_DATE
    """, (event, code))

    valid = cur.fetchone() is not None
    cur.close()
    conn.close()
    return valid


def validate_submission(parsed, now=None):
    if not parsed:
        return False, "❌ Format must be: CODE 6km 24:12", None

    event = get_active_event(now)
    if not event:
        return False, "⏱️ Submissions are currently closed.", None

    if not is_valid_code(event, parsed["code"]):
        return False, "❌ Invalid or expired run code.", event

    if event == "TT" and parsed["distance"] not in TT_ALLOWED_DISTANCES:
        return False, "❌ TT distances are 4km, 6km or 8km only.", event

    return True, "OK", event
