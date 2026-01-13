from app.db import get_cursor


def get_or_create_submission(member_id: int):
    with get_cursor() as cur:
        cur.execute("""
            SELECT *
            FROM submissions
            WHERE member_id = %s
              AND status = 'PENDING'
            ORDER BY created_at DESC
            LIMIT 1
        """, (member_id,))

        row = cur.fetchone()
        if row:
            return row

        cur.execute("""
            INSERT INTO submissions (member_id, status)
            VALUES (%s, 'PENDING')
            RETURNING *
        """, (member_id,))
        return cur.fetchone()


def verify_tt_code(submission_id: int, code: str):
    with get_cursor() as cur:
        cur.execute("""
            UPDATE submissions
            SET tt_code = %s,
                tt_code_verified = TRUE
            WHERE id = %s
            RETURNING *
        """, (code, submission_id))
        return cur.fetchone()


def save_distance(submission_id: int, distance: str):
    with get_cursor() as cur:
        cur.execute("""
            UPDATE submissions
            SET distance_text = %s
            WHERE id = %s
            RETURNING *
        """, (distance, submission_id))
        return cur.fetchone()


def save_time(submission_id: int, time_text: str, seconds: int):
    with get_cursor() as cur:
        cur.execute("""
            UPDATE submissions
            SET time_text = %s,
                seconds = %s
            WHERE id = %s
            RETURNING *
        """, (time_text, seconds, submission_id))
        return cur.fetchone()


def confirm_submission(submission_id: int):
    with get_cursor() as cur:
        cur.execute("""
            UPDATE submissions
            SET status = 'COMPLETE'
            WHERE id = %s
            RETURNING *
        """, (submission_id,))
        return cur.fetchone()