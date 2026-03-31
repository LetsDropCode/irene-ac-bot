# app/services/validation.py
import re
from datetime import date
from app.db import get_db
from app.db import get_cursor

TIME_PATTERN = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")

def is_valid_time(value: str) -> bool:
    return bool(value and TIME_PATTERN.match(value.strip()))

def is_valid_tt_code(code: str) -> bool:
    if not code:
        return False

    conn = get_db()
    cur = conn.cursor()

def is_valid_tt_code(code: str) -> bool:

    if not code:
        return False

    with get_cursor(commit=False) as cur:
        cur.execute("""
            SELECT 1
            FROM event_codes
            WHERE UPPER(code) = UPPER(%s)
              AND event_date = CURRENT_DATE
            LIMIT 1
        """, (code.strip(),))

        return cur.fetchone() is not None    
    
    cur.close()
    conn.close()
    return valid