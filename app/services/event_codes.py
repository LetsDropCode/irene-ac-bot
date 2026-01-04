# app/services/event_codes.py
from datetime import date
from app.db import get_db
from app.services.code_generator import generate_event_code

def create_event_code(event: str, event_date=None):
    if not event_date:
        event_date = date.today().isoformat()

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT code FROM event_codes
        WHERE event = ? AND event_date = ?
    """, (event, event_date))

    existing = cur.fetchone()
    if existing:
        conn.close()
        return existing["code"]

    code = generate_event_code()

    cur.execute("""
        INSERT INTO event_codes (event, code, event_date, created_at)
        VALUES (?, ?, ?, datetime('now'))
    """, (event, code, event_date))

    conn.commit()
    conn.close()
    return code