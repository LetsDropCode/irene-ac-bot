# app/services/submission_service.py

from app.db import get_db


def store_submission(
    member_id: int,
    activity: str,
    time_text: str,
    seconds: int,
    mode: str,
    distance_text: str | None = None,
):
    """
    Stores a validated submission in the database.
    """

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO submissions
        (member_id, activity, distance_text, time_text, seconds, mode)
        VALUES (%s, %s, %s, %s, %s, %s);
        """,
        (
            member_id,
            activity,
            distance_text,
            time_text,
            seconds,
            mode,
        )
    )

    conn.commit()
    cur.close()
    conn.close()