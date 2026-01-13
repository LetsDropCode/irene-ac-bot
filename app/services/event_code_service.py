# app/services/event_code_service.py
import random
from datetime import date
from app.db import get_db


def generate_tt_code(event: str = "TT") -> str:
    """
    Generates (or returns existing) TT code for today.
    Ensures ONE code per event per day.
    """
    conn = get_db()
    cur = conn.cursor()

    today = date.today()

    cur.execute(
        """
        SELECT code
        FROM event_codes
        WHERE event = %s
          AND event_date = %s
        LIMIT 1
        """,
        (event, today),
    )

    row = cur.fetchone()
    if row:
        cur.close()
        conn.close()
        return row["code"]

    code = str(random.randint(1000, 9999))

    cur.execute(
        """
        INSERT INTO event_codes (event, code, event_date)
        VALUES (%s, %s, %s)
        """,
        (event, code, today),
    )

    conn.commit()
    cur.close()
    conn.close()

    return code