from app.db import get_cursor


def get_previous_best(member_id: int, distance: str, exclude_submission_id: int = None):
    params = [member_id, distance]
    exclude_clause = ""

    if exclude_submission_id is not None:
        exclude_clause = "AND id <> %s"
        params.append(exclude_submission_id)

    with get_cursor(commit=False) as cur:
        cur.execute(f"""
            SELECT MIN(seconds) AS best_time
            FROM submissions
            WHERE member_id = %s
              AND distance_text = %s
              AND status = 'COMPLETE'
              AND seconds IS NOT NULL
              {exclude_clause}
        """, tuple(params))

        row = cur.fetchone()
        return row["best_time"] if row else None


def is_personal_best(member_id: int, distance: str, seconds: int) -> bool:
    """
    Returns True if this is the member's fastest time ever for this distance.
    """

    best_time = get_previous_best(member_id, distance)

    if best_time is None:
        return True

    return seconds < best_time
