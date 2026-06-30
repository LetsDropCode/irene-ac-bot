# app/services/validation.py
import re
from app.db import get_cursor

TIME_PATTERN = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")


def is_valid_time(value: str) -> bool:
    if not value or not TIME_PATTERN.match(value.strip()):
        return False

    parts = [int(part) for part in value.strip().split(":")]
    minutes = parts[-2]
    seconds = parts[-1]

    return minutes < 60 and seconds < 60


def time_to_seconds(value: str) -> int:
    parts = [int(part) for part in value.strip().split(":")]
    seconds = parts[-1] + parts[-2] * 60
    if len(parts) == 3:
        seconds += parts[0] * 3600
    return seconds


def is_valid_tt_code(code: str) -> bool:
    if not code:
        return False

    with get_cursor(commit=False) as cur:
        cur.execute("""
            SELECT 1
            FROM event_codes
            WHERE UPPER(code) = UPPER(%s)
              AND event_date = (CURRENT_TIMESTAMP AT TIME ZONE 'Africa/Johannesburg')::date
            LIMIT 1
        """, (code.strip(),))

        return cur.fetchone() is not None
