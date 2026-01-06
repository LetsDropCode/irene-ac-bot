# app/services/event_code_validator.py

from datetime import date
from app.db import get_db


def validate_event_code(code: str, event: str) -> tuple[bool, str]:
    """
    Validates a code for the detected event *today*
    """

    if not code:
        return False, "❌ A code is required for this run."

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT 1
        FROM event_codes
        WHERE UPPER(code) = UPPER(%s)
          AND event = %s
          AND event_date = %s;
        """,
        (code.strip(), event, date.today())
    )

    valid = cur.fetchone() is not None

    cur.close()
    conn.close()

    if not valid:
        return False, (
            f"❌ That code isn’t valid for *{event}* today.\n\n"
            "Please check with your run leader."
        )

    return True, event