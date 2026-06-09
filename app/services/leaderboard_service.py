# app/services/leaderboard_service.py

from app.db import get_cursor

def get_runner_leaderboard():
    with get_cursor() as cur:

        cur.execute("""
        SELECT
            m.id as member_id,
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
            AND s.distance_text IS NOT NULL
            AND s.distance_text <> ''
            AND s.activity = 'TT'
            AND DATE(s.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Johannesburg') = CURRENT_DATE
        ORDER BY
            CAST(s.distance_text AS INTEGER) DESC,
            position ASC
        """)
        return cur.fetchall()

def get_walker_feed():
    with get_cursor() as cur:

        cur.execute("""
        SELECT
            m.first_name,
            m.last_name,
            s.time_text,
            s.created_at
        FROM submissions s
        JOIN members m ON m.id = s.member_id
        WHERE
            s.status = 'COMPLETE'
            AND (s.distance_text IS NULL OR s.distance_text = '')
            AND m.participation_type = 'WALKER'
            AND DATE(s.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Johannesburg') = CURRENT_DATE
        ORDER BY s.created_at DESC
        LIMIT 10
        """)
        return cur.fetchall()

def get_season_pb_leaderboard():
    with get_cursor() as cur:
        cur.execute("""
            WITH best_times AS (
                SELECT
                    m.id AS member_id,
                    m.first_name,
                    m.last_name,
                    s.distance_text,
                    MIN(s.seconds) AS best_seconds

            FROM submissions s
            JOIN members m ON m.id = s.member_id

            WHERE
                s.status = 'COMPLETE'
                AND s.seconds IS NOT NULL
                AND s.distance_text IS NOT NULL
                AND s.distance_text <> ''
                AND s.activity = 'TT'
                AND DATE(s.created_at) >= DATE_TRUNC('year', CURRENT_DATE)

            GROUP BY
                m.id, m.first_name, m.last_name, s.distance_text
        ),

        ranked AS (
            SELECT *,
                RANK() OVER (
                    PARTITION BY distance_text
                    ORDER BY best_seconds ASC
                ) AS position
            FROM best_times
        )

        SELECT *
        FROM ranked
        ORDER BY
            CAST(distance_text AS INTEGER) DESC,
            position ASC;
        """)

        return cur.fetchall()

def get_fastest_improver():
    with get_cursor() as cur:

        cur.execute("""
        WITH today AS (
            SELECT *
            FROM submissions
            WHERE
                status = 'COMPLETE'
                AND seconds IS NOT NULL
                AND distance_text IS NOT NULL
                AND activity = 'TT'
                AND DATE(created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Johannesburg') = CURRENT_DATE
        ),

        prev AS (
            SELECT
                s.member_id,
                s.distance_text,
                MIN(s.seconds) AS prev_best
            FROM submissions s
            WHERE
                s.status = 'COMPLETE'
                AND s.seconds IS NOT NULL
                AND s.distance_text IS NOT NULL
                AND s.activity = 'TT'
                AND DATE(s.created_at) < CURRENT_DATE
            GROUP BY s.member_id, s.distance_text
        )

        SELECT
            m.first_name,
            m.last_name,
            t.distance_text,
            (prev.prev_best - t.seconds) AS improvement
        FROM today t
        JOIN prev ON prev.member_id = t.member_id
                 AND prev.distance_text = t.distance_text
        JOIN members m ON m.id = t.member_id
        WHERE (prev.prev_best - t.seconds) > 0
        ORDER BY improvement DESC
        LIMIT 1
        """)

        return cur.fetchone()

def get_today_winners():
    with get_cursor() as cur:

        cur.execute("""
        SELECT *
        FROM (
            SELECT
                m.first_name,
                m.last_name,
                s.distance_text,
                s.time_text,
                ROW_NUMBER() OVER (
                    PARTITION BY s.distance_text
                    ORDER BY s.seconds ASC
                ) AS rn
            FROM submissions s
            JOIN members m ON m.id = s.member_id
            WHERE
                s.status = 'COMPLETE'
                AND s.seconds IS NOT NULL
                AND s.distance_text IS NOT NULL
                AND s.activity = 'TT'
                AND DATE(s.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Johannesburg') = CURRENT_DATE
        ) t
        WHERE rn = 1
        ORDER BY CAST(distance_text AS INTEGER) DESC
        """)

        return cur.fetchall()

def get_user_today_summary(member_id: int):
    with get_cursor() as cur:

        cur.execute("""
        SELECT
            s.distance_text,
            s.time_text,
            s.seconds
        FROM submissions s
        WHERE
            s.member_id = %s
            AND s.status = 'COMPLETE'
            AND DATE(s.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Johannesburg') = CURRENT_DATE
        LIMIT 1
        """, (member_id,))

        return cur.fetchone()
