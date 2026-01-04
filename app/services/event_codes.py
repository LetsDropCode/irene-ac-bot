# app/services/event_codes.py

from datetime import date
from app.db import get_conn
from app.services.code_generator import generate_event_code


def create_event_code(event: str, valid_date: date):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT code FROM event_codes
        WHERE event = ? AND event_date = ?
    """, (event, valid_date.isoformat()))

    row = cur.fetchone()
    if row:
        conn.close()
        return row["code"]

    code = generate_event_code()

    cur.execute("""
        INSERT INTO event_codes (event, code, event_date, created_at)
        VALUES (?, ?, ?, datetime('now'))
    """, (event, code, valid_date.isoformat()))

    conn.commit()
    conn.close()
    return code


def is_valid_code(event: str, code: str) -> bool:
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT 1 FROM event_codes
        WHERE event = ?
          AND code = ?
          AND event_date = ?
    """, (event, code, date.today().isoformat()))

    valid = cur.fetchone() is not None
    conn.close()
    return valid