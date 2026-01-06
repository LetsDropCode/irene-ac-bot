from app.db import get_db


def set_submission_state(event: str, is_open: bool):
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