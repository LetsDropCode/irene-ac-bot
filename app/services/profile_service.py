
from app.db import get_cursor

def get_user_profile(member_id):
    with get_cursor() as cur:

        # Total runs
        cur.execute("""
            SELECT COUNT(*) as total_runs
            FROM submissions
            WHERE member_id = %s
            AND status = 'COMPLETE'
        """, (member_id,))
        total_runs = cur.fetchone()["total_runs"]

        # Personal bests per distance
        cur.execute("""
            SELECT distance_text, MIN(seconds) as best_seconds
            FROM submissions
            WHERE member_id = %s
            AND status = 'COMPLETE'
            AND seconds IS NOT NULL
            GROUP BY distance_text
        """, (member_id,))
        pbs = cur.fetchall()

        # Last 3 runs
        cur.execute("""
            SELECT distance_text, time_text
            FROM submissions
            WHERE member_id = %s
            AND status = 'COMPLETE'
            ORDER BY created_at DESC
            LIMIT 3
        """, (member_id,))
        recent = cur.fetchall()

        return {
            "total_runs": total_runs,
            "pbs": pbs,
            "recent": recent
        }