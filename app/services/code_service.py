# app/services/code_service.py

import random
import string
from datetime import date
from app.db import get_db

CODE_LENGTH = 4

def generate_code() -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=CODE_LENGTH))


def get_or_create_daily_code(event: str) -> str:
    """
    Returns today's code for the event.
    Creates it if it doesn't exist.
    """
    today = date.today().isoformat()
    db = get_db()
    cur = db.cursor()

    cur.execute(
        """
        SELECT code FROM event_codes
        WHERE event = ? AND event_date = ?
        """,
        (event, today),
    )

    row = cur.fetchone()
    if row:
        return row[0]

    code = generate_code()

    cur.execute(
        """
        INSERT INTO event_codes (event, event_date, code)
        VALUES (?, ?, ?)
        """,
        (event, today, code),
    )

    db.commit()
    return code


def validate_code(event: str, submitted_code: str) -> bool:
    today = date.today().isoformat()
    db = get_db()
    cur = db.cursor()

    cur.execute(
        """
        SELECT 1 FROM event_codes
        WHERE event = ? AND event_date = ? AND code = ?
        """,
        (event, today, submitted_code.upper()),
    )

    return cur.fetchone() is not None