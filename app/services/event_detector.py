# app/services/event_detector.py

from datetime import datetime
from app.db import get_db


def get_active_event() -> str | None:
    """
    Returns the active event name for *now*
    based on event_config.
    """

    now = datetime.now()
    day_of_week = now.weekday()  # Monday = 0
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
        (day_of_week, current_time)
    )

    row = cur.fetchone()

    cur.close()
    conn.close()

    if not row:
        return None

    return row["event"]