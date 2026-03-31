# app/services/leaderboard_service.py
def get_tonight_leaderboard():
    with get_cursor() as cur:

        cur.execute("""
        SELECT
            m.first_name,
            m.last_name,
            s.distance_text,
            s.time_text,
            s.seconds,
            RANK() OVER (
                PARTITION BY s.distance_text
                ORDER BY s.seconds ASC
            ) as position
        FROM submissions s
        JOIN members m ON m.id = s.member_id
        WHERE
            s.status = 'COMPLETE'
            AND s.seconds IS NOT NULL
            AND DATE(s.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Johannesburg') = CURRENT_DATE
        ORDER BY
            CAST(NULLIF(s.distance_text, '') AS INT) DESC,
            position ASC
        """)
        return cur.fetchall()