from datetime import datetime
from app.db import get_db

def create_submission(phone: str, tt_code: str):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO submissions (member_id, activity, time_text, seconds)
        SELECT id, 'TT', '', 0
        FROM members
        WHERE phone = %s
        RETURNING id;
    """, (phone,))

    submission_id = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    conn.close()
    return submission_id


def save_distance(submission_id: int, distance: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE submissions
        SET distance_text = %s
        WHERE id = %s;
    """, (distance, submission_id))
    conn.commit()
    cur.close()
    conn.close()


def save_time(submission_id: int, time_text: str, seconds: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE submissions
        SET time_text = %s,
            seconds = %s
        WHERE id = %s;
    """, (time_text, seconds, submission_id))
    conn.commit()
    cur.close()
    conn.close()


def confirm_submission(submission_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE submissions
        SET created_at = NOW()
        WHERE id = %s;
    """, (submission_id,))
    conn.commit()
    cur.close()
    conn.close()