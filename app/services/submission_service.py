from datetime import date, datetime, timedelta
from app.db import get_cursor


# ─────────────────────────────────────────────
# GET OR CREATE SUBMISSION (ONE PER DAY)
# ─────────────────────────────────────────────
def get_or_create_submission(member):
    today = date.today()

    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id,
                   distance_text,
                   seconds,
                   confirmed,
                   tt_code_verified,
                   created_at
            FROM submissions
            WHERE member_id = %s
              AND created_at::date = %s
            """,
            (member["id"], today),
        )

        row = cur.fetchone()

        if row:
            return _row_to_submission(row)

        cur.execute(
            """
            INSERT INTO submissions (member_id, created_at, confirmed)
            VALUES (%s, NOW(), FALSE)
            RETURNING id,
                      distance_text,
                      seconds,
                      confirmed,
                      tt_code_verified,
                      created_at
            """,
            (member["id"],),
        )

        return _row_to_submission(cur.fetchone())


# ─────────────────────────────────────────────
# INTERNAL MAPPER
# ─────────────────────────────────────────────
def _row_to_submission(row):
    return {
        "id": row[0],
        "distance": row[1],
        "seconds": row[2],
        "confirmed": row[3],
        "tt_code_verified": row[4],
        "created_at": row[5],
    }


# ─────────────────────────────────────────────
# SAVE DISTANCE
# ─────────────────────────────────────────────
def save_distance(submission, distance_km):
    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE submissions
            SET distance_text = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (f"{distance_km}km", submission["id"]),
        )


# ─────────────────────────────────────────────
# SAVE TIME (SECONDS)
# ─────────────────────────────────────────────
def save_time(submission, seconds):
    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE submissions
            SET seconds = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (seconds, submission["id"]),
        )


# ─────────────────────────────────────────────
# TT CODE VERIFICATION
# ─────────────────────────────────────────────
def mark_code_verified(submission):
    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE submissions
            SET tt_code_verified = TRUE,
                updated_at = NOW()
            WHERE id = %s
            """,
            (submission["id"],),
        )


# ─────────────────────────────────────────────
# CONFIRM SUBMISSION
# ─────────────────────────────────────────────
def confirm_submission(submission):
    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE submissions
            SET confirmed = TRUE,
                updated_at = NOW()
            WHERE id = %s
            """,
            (submission["id"],),
        )


# ─────────────────────────────────────────────
# EDIT WINDOW (15 MINUTES)
# ─────────────────────────────────────────────
def is_edit_window_open(submission):
    return datetime.utcnow() - submission["created_at"] <= timedelta(minutes=15)