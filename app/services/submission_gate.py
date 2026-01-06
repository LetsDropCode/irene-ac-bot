# app/services/submission_gate.py

from app.db import get_db


def set_submission_state(event: str, is_open: int) -> None:
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE event_config
        SET submissions_open = %s
        WHERE event = %s;
        """,
        (is_open, event),
    )

    conn.commit()
    cur.close()
    conn.close()


def is_submission_open(event: str) -> bool:
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT submissions_open
        FROM event_config
        WHERE event = %s
        LIMIT 1;
        """,
        (event,),
    )

    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        return False

    return bool(row["submissions_open"])