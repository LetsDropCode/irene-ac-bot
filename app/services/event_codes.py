# app/services/event_codes.py
import random
import string
from datetime import date
from app.db import get_db

def _generate_code():
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=5))

def get_or_create_event_code(event: str):
    today = date.today()

    conn = get_db()
    cur = conn.cursor()

    # Check if code already exists
    cur.execute("""
        SELECT code
        FROM event_codes
        WHERE event = %s AND event_date = %s
    """, (event, today))

    row = cur.fetchone()
    if row:
        cur.close()
        conn.close()
        return row["code"]

    # Create new code
    code = _generate_code()

    cur.execute("""
        INSERT INTO event_codes (event, code, event_date)
        VALUES (%s, %s, %s)
    """, (event, code, today))

    conn.commit()
    cur.close()
    conn.close()

    return code