from datetime import datetime, time
from app.db import get_db

def get_active_event(now=None):
    """
    Returns event name if an event is currently open, else None
    """
    now = now or datetime.now()
    weekday = now.weekday()  # Monday=0
    current_time = now.time()

    db = get_db()
    cur = db.cursor()

    cur.execute("""
        SELECT event, open_time, close_time
        FROM event_config
        WHERE day_of_week = ?
          AND active = 1
    """, (weekday,))

    rows = cur.fetchall()
    db.close()

    for row in rows:
        open_t = time.fromisoformat(row["open_time"])
        close_t = time.fromisoformat(row["close_time"])

        if open_t <= current_time <= close_t:
            return row["event"]

    return None