from datetime import date
from app.db import get_db
from app.services.time_utils import time_to_seconds

def get_or_create_submission(phone: str):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM submissions
        WHERE phone=%s AND created_at::date=%s
        LIMIT 1
        """,
        (phone, date.today())
    )

    row = cur.fetchone()
    if row:
        cur.close()
        conn.close()
        return row

    cur.execute(
        """
        INSERT INTO submissions (phone, confirmed)
        VALUES (%s, FALSE)
        RETURNING *;
        """,
        (phone,)
    )

    row = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return row

def mark_code_verified(phone, code):
    _update(phone, {"tt_code_verified": True, "tt_code": code})

def save_distance(phone, distance):
    _update(phone, {"distance": distance})

def save_time(phone, time):
    _update(phone, {
        "time": time,
        "seconds": time_to_seconds(time),
    })

def confirm_submission(phone):
    _update(phone, {"confirmed": True})

def is_edit_window_open(sub):
    return not sub["confirmed"]

def _update(phone, fields):
    conn = get_db()
    cur = conn.cursor()
    set_clause = ", ".join(f"{k}=%s" for k in fields)
    cur.execute(
        f"UPDATE submissions SET {set_clause} WHERE phone=%s",
        list(fields.values()) + [phone]
    )
    conn.commit()
    cur.close()
    conn.close()