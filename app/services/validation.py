# app/services/validation.py
from app.db import get_db
from datetime import date

def is_valid_code(event, code):
    db = get_db()
    cur = db.cursor()

    cur.execute("""
        SELECT 1 FROM event_codes
        WHERE event = ? AND code = ? AND event_date = ?
    """, (event, code, date.today().isoformat()))

    valid = cur.fetchone() is not None
    db.close()
    return valid