from datetime import date
from app.db import get_cursor
from app.models.submission import Submission


def get_or_create_submission(member: dict) -> Submission:
    """
    Returns today's submission for a member.
    Creates one if it does not exist.
    """

    with get_cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM submissions
            WHERE member_id = %s
              AND created_at::date = %s
            LIMIT 1
            """,
            (member["id"], date.today()),
        )

        row = cur.fetchone()
        if row:
            return Submission(**row)

        # Create a NEW submission with REQUIRED defaults
        cur.execute(
            """
            INSERT INTO submissions (
                member_id,
                activity,
                mode,
                confirmed,
                tt_code_verified
            )
            VALUES (%s, 'TT', 'RUN', FALSE, FALSE)
            RETURNING *
            """,
            (member["id"],),
        )

        return Submission(**cur.fetchone())


def save_distance(submission: Submission, distance: str):
    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE submissions
            SET distance_text = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (distance, submission.id),
        )


def save_time(submission: Submission, time_text: str, seconds: int):
    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE submissions
            SET time_text = %s,
                seconds = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (time_text, seconds, submission.id),
        )


def mark_code_verified(submission: Submission, code: str):
    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE submissions
            SET tt_code_verified = TRUE,
                code_used = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (code, submission.id),
        )


def confirm_submission(submission: Submission):
    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE submissions
            SET confirmed = TRUE,
                updated_at = NOW()
            WHERE id = %s
            """,
            (submission.id,),
        )


def is_edit_window_open(submission: Submission) -> bool:
    return not submission.confirmed