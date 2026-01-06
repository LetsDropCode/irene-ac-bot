# app/services/event_detector.py

from datetime import datetime
from app.db import get_db


def get_today_event() -> str | None:
    """
    Returns the event scheduled for TODAY (ignores time window)
    """
    today = datetime.now().weekday()  # Monday = 0

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT event
        FROM event_config
        WHERE day_of_week = %s
          AND active = 1
        LIMIT 1;
        """,
        (today,),
    )

    row = cur.fetchone()
    cur.close()
    conn.close()

    return row["event"] if row else None


def get_active_event() -> str | None:
    """
    Returns the event that is ACTIVE RIGHT NOW (time-based)
    """
    now = datetime.now()
    day_of_week = now.weekday()
    current_time = now.strftime("%H:%M")

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT event
        FROM event_config
        WHERE day_of_week = %s
          AND active = 1
          AND %s BETWEEN open_time AND close_time
        LIMIT 1;
        """,
        (day_of_week, current_time),
    )

    row = cur.fetchone()
    cur.close()
    conn.close()

    return row["event"] if row else None