# app/services/event_codes.py
from datetime import date
from app.db import get_db
from app.services.code_generator import generate_event_code

def create_event_code(event: str, valid_date: date):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT code
        FROM event_codes
        WHERE event = %s AND event_date = %s
    """, (event, valid_date))

    row = cur.fetchone()
    if row:
        cur.close()
        conn.close()
        return row["code"]

    code = generate_event_code()

    cur.execute("""
        INSERT INTO event_codes (event, code, event_date)
        VALUES (%s, %s, %s)
    """, (event, code, valid_date))

    conn.commit()
    cur.close()
    conn.close()
    return code