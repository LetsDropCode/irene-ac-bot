import random
import string
from datetime import date
from app.db import get_db


def generate_code(length: int = 6) -> str:
    return "".join(
        random.choices(string.ascii_uppercase + string.digits, k=length)
    )


def create_today_tt_code() -> str:
    """
    Creates a TT code for TODAY.
    Ensures only one active code exists per day.
    """
    conn = get_db()
    cur = conn.cursor()

    # Check if code already exists today
    cur.execute(
        """
        SELECT code
        FROM event_codes
        WHERE event_date = %s
        LIMIT 1
        """,
        (date.today(),),
    )

    row = cur.fetchone()
    if row:
        cur.close()
        conn.close()
        return row["code"]

    code = generate_code()

    cur.execute(
        """
        INSERT INTO event_codes (code, event_date)
        VALUES (%s, %s)
        """,
        (code, date.today()),
    )

    conn.commit()
    cur.close()
    conn.close()

    return code