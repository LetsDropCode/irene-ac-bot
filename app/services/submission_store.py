from app.db import get_conn
from app.services.time_utils import time_to_seconds


def get_best_seconds(member_id, event, distance):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT MIN(seconds) AS best
        FROM submissions
        WHERE member_id = ? AND event = ? AND distance = ?
    """, (member_id, event, distance))

    row = cur.fetchone()
    conn.close()
    return row["best"] if row and row["best"] else None


def save_submission(member_id, event, distance, time_text):
    seconds = time_to_seconds(time_text)
    best = get_best_seconds(member_id, event, distance)

    is_pb = 1 if best is None or seconds < best else 0

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO submissions (member_id, event, distance, time, seconds, is_pb)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (member_id, event, distance, time_text, seconds, is_pb))

    conn.commit()
    conn.close()

    return is_pb