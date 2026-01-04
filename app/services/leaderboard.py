from app.db import get_conn
from datetime import date, timedelta


def get_week_bounds(today=None):
    today = today or date.today()
    start = today - timedelta(days=today.weekday())  # Monday
    end = start + timedelta(days=6)
    return start, end


def get_weekly_leaderboard(event, distance, limit=5):
    start, end = get_week_bounds()

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            m.first_name,
            m.last_name,
            MIN(s.seconds) AS best_seconds,
            s.time
        FROM submissions s
        JOIN members m ON m.id = s.member_id
        WHERE
            s.event = ?
            AND s.distance = ?
            AND date(s.created_at) BETWEEN ? AND ?
        GROUP BY s.member_id
        ORDER BY best_seconds ASC
        LIMIT ?
    """, (event, distance, start, end, limit))

    rows = cur.fetchall()
    conn.close()

    return rows