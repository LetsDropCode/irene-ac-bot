# app/services/submission_service.py

from datetime import date
from app.db import get_db
from app.models.submission import Submission


def time_to_seconds(value: str) -> int:
    """
    Converts mm:ss or hh:mm:ss to seconds
    """
    parts = value.split(":")

    if len(parts) == 2:  # mm:ss
        minutes, seconds = parts
        return int(minutes) * 60 + int(seconds)

    if len(parts) == 3:  # hh:mm:ss
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + int(seconds)

    raise ValueError("Invalid time format")


def get_or_create_submission(phone: str) -> Submission:
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM submissions
        WHERE phone = %s AND created_at::date = %s
        LIMIT 1
        """,
        (phone, date.today()),
    )

    row = cur.fetchone()

    if row:
        cur.close()
        conn.close()
        return Submission(**row)

    cur.execute(
        """
        INSERT INTO submissions (phone)
        VALUES (%s)
        RETURNING *
        """,
        (phone,),
    )

    submission = Submission(**cur.fetchone())
    conn.commit()
    cur.close()
    conn.close()
    return submission


def _update(phone: str, fields: dict):
    conn = get_db()
    cur = conn.cursor()

    set_clause = ", ".join(f"{k} = %s" for k in fields)
    values = list(fields.values()) + [phone]

    cur.execute(
        f"""
        UPDATE submissions
        SET {set_clause}, updated_at = NOW()
        WHERE phone = %s
        """,
        values,
    )

    conn.commit()
    cur.close()
    conn.close()


def mark_code_verified(submission: Submission, code: str):
    _update(submission.phone, {
        "tt_code_verified": True,
        "tt_code": code,
    })


def save_distance(submission: Submission, distance: str):
    _update(submission.phone, {"distance": distance})


def save_time(submission: Submission, time: str):
    seconds = time_to_seconds(time)
    _update(submission.phone, {
        "time": time,
        "seconds": seconds,
    })


def confirm_submission(submission: Submission):
    _update(submission.phone, {"confirmed": True})


def is_edit_window_open(submission: Submission) -> bool:
    return not submission.confirmed