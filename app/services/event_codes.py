# app/services/event_codes.py
from datetime import date
from app.db import get_db
from app.services.code_generator import generate_event_code

def create_event_code(event: str, valid_date: date):
    conn = get_db()
    cur = conn.cursor()

    # Check if code already exists
    cur.execute("""
        SELECT code FROM event_codes
        WHERE event = ? AND valid_date = ?
    """, (event, valid_date))
    
    existing = cur.fetchone()
    if existing:
        conn.close()
        return existing["code"]

    code = generate_event_code()

    cur.execute("""
        INSERT INTO event_codes (event, code, valid_date, created_at)
        VALUES (?, ?, ?, datetime('now'))
    """, (event, code, valid_date))

    conn.commit()
    conn.close()
    return code