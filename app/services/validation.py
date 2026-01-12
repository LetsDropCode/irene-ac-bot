import re
from datetime import date
from app.db import get_db

TIME_PATTERN = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")


def is_valid_time(value: str) -> bool:
    return bool(TIME_PATTERN.match(value.strip()))


def is_valid_tt_code(code: str) -> bool:
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT 1
        FROM event_codes
        WHERE UPPER(code) = UPPER(%s)
          AND event_date = %s
        """,
        (code.strip(), date.today()),
    )

    valid = cur.fetchone() is not None
    cur.close()
    conn.close()
    return valid