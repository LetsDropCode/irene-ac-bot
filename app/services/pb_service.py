from app.db import get_cursor


def is_personal_best(member_id: int, distance: str, seconds: int) -> bool:
    """
    Returns True if this is the member's fastest time ever for this distance.
    """

    with get_cursor(commit=False) as cur:

        cur.execute("""
            SELECT MIN(seconds) AS best_time
            FROM submissions
            WHERE member_id = %s
              AND distance_text = %s
              AND status = 'COMPLETE'
              AND seconds IS NOT NULL
        """, (member_id, distance))

        row = cur.fetchone()

        if not row or row["best_time"] is None:
            return True  # first ever result

        return seconds < row["best_time"]