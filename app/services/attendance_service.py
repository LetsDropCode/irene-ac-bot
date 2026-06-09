# app/services/attendance_service.py
from app.db import get_cursor


def mark_attendance(member_id: int, event: str = "TT", source: str = "whatsapp"):
    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO attendance (member_id, event, event_date, source)
            VALUES (
                %s,
                %s,
                (CURRENT_TIMESTAMP AT TIME ZONE 'Africa/Johannesburg')::date,
                %s
            )
            ON CONFLICT (member_id, event, event_date)
            DO UPDATE SET source = EXCLUDED.source
            RETURNING *
        """, (member_id, event, source))

        return cur.fetchone()
