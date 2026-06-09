# app/services/submission_service.py
from app.db import get_cursor


def get_or_create_submission(member_id: int):
    with get_cursor(commit=False) as cur:

        cur.execute("""
            SELECT *
            FROM submissions
            WHERE member_id = %s
                AND status != 'CANCELLED'
                AND DATE(created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Johannesburg') = CURRENT_DATE
            ORDER BY created_at DESC
             LIMIT 1
        """, (member_id,))

        w = cur.fetchone()

        if w:
            return w

    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO submissions (member_id, activity, status, time_text, seconds)
            VALUES (%s, 'TT', 'PENDING', '', 0)
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


def reopen_submission_for_edit(submission_id: int):
    with get_cursor() as cur:
        cur.execute("""
            UPDATE submissions
            SET status = 'PENDING',
                confirmed = FALSE,
                distance_text = NULL,
                time_text = '',
                seconds = 0
            WHERE id = %s
            RETURNING *
        """, (submission_id,))

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
            SET status = 'COMPLETE',
                confirmed = TRUE
            WHERE id = %s
                    AND status != 'COMPLETE'
            RETURNING *
        """, (submission_id,))

        return cur.fetchone()

def release_pending_submissions(member_id: int):
    """
    Cancel ONLY abandoned / unverified submissions.
    Never touch active sessions.
    """

    with get_cursor() as cur:
        cur.execute("""
            UPDATE submissions
            SET status = 'CANCELLED'
            WHERE member_id = %s
              AND status = 'PENDING'
                AND DATE(created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Johannesburg') = CURRENT_DATE
              AND tt_code_verified = FALSE
        """, (member_id,))

        return cur.fetchone()

def get_pending_members():
    with get_cursor(commit=False) as cur:

        cur.execute("""
        SELECT
            m.id,
            m.first_name,
            m.last_name,
            m.phone,
            s.distance_text,
            s.time_text,
            s.created_at
        FROM submissions s
        JOIN members m ON m.id = s.member_id
        WHERE
            s.status = 'PENDING'
            AND s.tt_code_verified = TRUE
            AND DATE(s.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Johannesburg') = CURRENT_DATE
        ORDER BY s.created_at ASC
        """)

        return cur.fetchall()
