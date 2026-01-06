# app/services/submission_gate.py

from app.db import get_db


def set_submission_state(event: str, is_open: int) -> None:
    """
    Opens or closes submissions for an event.
    is_open: 1 = open, 0 = closed
    """
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE event_config
        SET active = %s
        WHERE event = %s;
        """,
        (is_open, event)
    )

    conn.commit()
    cur.close()
    conn.close()


def submissions_are_open(event: str) -> bool:
    """
    Returns True if submissions are open for the event.
    """
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT active
        FROM event_config
        WHERE event = %s
        LIMIT 1;
        """,
        (event,)
    )

    row = cur.fetchone()
    cur.close()
    conn.close()

    return bool(row and row["active"] == 1)