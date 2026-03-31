# app/services/tt_status_service.py
from app.db import get_cursor


def get_tt_status():

    with get_cursor() as cur:

        cur.execute("""
        SELECT
            COUNT(*) FILTER (WHERE tt_code_verified = TRUE) AS participants,
            COUNT(*) FILTER (WHERE status = 'COMPLETE') AS completed,
            COUNT(*) FILTER (WHERE status = 'PENDING') AS pending
        FROM submissions
        WHERE DATE(created_at) = CURRENT_DATE
        """)

        row = cur.fetchone()

        return f"""
🏃 *Tonight's TT Status*

Participants: {row['participants']}
Completed: {row['completed']}
Pending: {row['pending']}
"""