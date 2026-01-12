from datetime import datetime, date
from app.db import get_db
from app.models.submission import Submission

# ─────────────────────────────────────────────
# CORE FETCH / CREATE
# ─────────────────────────────────────────────
def get_or_create_submission(phone: str) -> Submission:
    conn = get_db()
    cur = conn.cursor()

    today = date.today()

    cur.execute(
        """
        SELECT *
        FROM submissions
        WHERE phone = %s AND created_at::date = %s
        LIMIT 1
        """,
        (phone, today),
    )

    row = cur.fetchone()

    if row:
        cur.close()
        conn.close()
        return Submission(**row)

    cur.execute(
        """
        INSERT INTO submissions (
            phone,
            tt_code_verified,
            confirmed,
            created_at,
            updated_at
        )
        VALUES (%s, FALSE, FALSE, NOW(), NOW())
        RETURNING *
        """,
        (phone,),
    )

    submission = Submission(**cur.fetchone())
    conn.commit()
    cur.close()
    conn.close()
    return submission


# ─────────────────────────────────────────────
# UPDATE HELPERS
# ─────────────────────────────────────────────
def mark_code_verified(submission: Submission, code: str):
    _update(
        submission.phone,
        {"tt_code_verified": True, "tt_code": code},
    )


def save_distance(submission: Submission, distance: str):
    _update(submission.phone, {"distance": distance})


def save_time(submission: Submission, time_str: str, seconds: int):
    _update(
        submission.phone,
        {
            "time": time_str,
            "seconds": seconds,
        },
    )


def confirm_submission(submission: Submission):
    _update(submission.phone, {"confirmed": True})


# ─────────────────────────────────────────────
# EDIT WINDOW
# ─────────────────────────────────────────────
def is_edit_window_open(submission: Submission) -> bool:
    return not submission.confirmed


# ─────────────────────────────────────────────
# INTERNAL UPDATE
# ─────────────────────────────────────────────
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