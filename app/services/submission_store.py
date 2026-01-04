# app/services/submission_store.py

from datetime import date
from app.db import get_conn
from app.services.time_utils import time_to_seconds


def save_submission(member_id, event, distance, time_text):
    conn = get_conn()
    cur = conn.cursor()

    today = date.today().isoformat()

    # 🚫 Block duplicate submission
    cur.execute("""
        SELECT 1 FROM submissions
        WHERE member_id = ?
          AND activity = ?
          AND DATE(created_at) = ?
    """, (member_id, event, today))

    if cur.fetchone():
        conn.close()
        return "DUPLICATE"

    seconds = time_to_seconds(time_text)

    # 🔥 Check PB
    cur.execute("""
        SELECT MIN(seconds) FROM submissions
        WHERE member_id = ?
          AND activity = ?
          AND distance_text = ?
    """, (member_id, event, distance))

    row = cur.fetchone()
    is_pb = row[0] is None or seconds < row[0]

    # ✅ Insert submission
    cur.execute("""
        INSERT INTO submissions (
            member_id, activity, distance_text, time_text, seconds
        ) VALUES (?, ?, ?, ?, ?)
    """, (member_id, event, distance, time_text, seconds))

    conn.commit()
    conn.close()

    return is_pb