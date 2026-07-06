# app/services/leaderboard_service.py

from datetime import date

from app.db import get_cursor


def _event_date_filter(event_date):
    if event_date is None:
        return "CURRENT_DATE", ()

    if isinstance(event_date, date):
        return "%s", (event_date,)

    return "%s", (event_date,)


def get_runner_leaderboard(event_date=None):
    date_expr, params = _event_date_filter(event_date)

    with get_cursor(commit=False) as cur:
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
            AND DATE(s.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Johannesburg') = """ + date_expr + """
        ORDER BY
            CAST(s.distance_text AS INTEGER) DESC,
            position ASC
        """, params)
        return cur.fetchall()


def get_walker_feed(event_date=None):
    date_expr, params = _event_date_filter(event_date)

    with get_cursor(commit=False) as cur:
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
            AND DATE(s.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Johannesburg') = """ + date_expr + """
        ORDER BY s.created_at DESC
        LIMIT 10
        """, params)
        return cur.fetchall()


def get_checked_in_tt_member_phones(event_date):
    with get_cursor(commit=False) as cur:
        cur.execute("""
        SELECT DISTINCT m.phone
        FROM attendance a
        JOIN members m ON m.id = a.member_id
        WHERE a.event = 'TT'
          AND a.event_date = %s
          AND COALESCE(m.leaderboard_opt_out, FALSE) = FALSE
        ORDER BY m.phone
        """, (event_date,))

        return [row["phone"] for row in cur.fetchall()]

def get_overall_leaderboard(member_id=None, limit_per_distance=10):
    params = [limit_per_distance]

    viewer_filter = ""
    if member_id is not None:
        viewer_filter = "OR member_id = %s"
        params.append(member_id)

    with get_cursor(commit=False) as cur:
        cur.execute(f"""
        WITH normalized AS (
            SELECT
                m.id AS member_id,
                m.first_name,
                m.last_name,
                regexp_replace(LOWER(s.distance_text), '[^0-9]', '', 'g') AS distance_text,
                s.time_text,
                s.seconds,
                s.created_at
            FROM submissions s
            JOIN members m ON m.id = s.member_id
            WHERE
                s.status = 'COMPLETE'
                AND s.seconds IS NOT NULL
                AND s.seconds > 0
                AND s.distance_text IS NOT NULL
                AND s.distance_text <> ''
                AND s.activity = 'TT'
                AND m.participation_type IN ('RUNNER', 'BOTH')
                AND COALESCE(m.leaderboard_opt_out, FALSE) = FALSE
        ),

        best_times AS (
            SELECT DISTINCT ON (member_id, distance_text)
                member_id,
                first_name,
                last_name,
                distance_text,
                time_text,
                seconds AS best_seconds
            FROM normalized
            WHERE distance_text IN ('8', '6', '4')
            ORDER BY member_id, distance_text, seconds ASC, created_at ASC
        ),

        ranked AS (
            SELECT
                *,
                RANK() OVER (
                    PARTITION BY distance_text
                    ORDER BY best_seconds ASC
                ) AS position
            FROM best_times
        )

        SELECT *
        FROM ranked
        WHERE position <= %s
           {viewer_filter}
        ORDER BY
            CAST(distance_text AS INTEGER) DESC,
            position ASC,
            first_name ASC,
            last_name ASC;
        """, tuple(params))

        return cur.fetchall()

def get_member_rankings(member_id):
    with get_cursor(commit=False) as cur:
        cur.execute("""
        WITH normalized AS (
            SELECT
                m.id AS member_id,
                m.first_name,
                m.last_name,
                regexp_replace(LOWER(s.distance_text), '[^0-9]', '', 'g') AS distance_text,
                s.time_text,
                s.seconds,
                s.created_at
            FROM submissions s
            JOIN members m ON m.id = s.member_id
            WHERE
                s.status = 'COMPLETE'
                AND s.seconds IS NOT NULL
                AND s.seconds > 0
                AND s.distance_text IS NOT NULL
                AND s.distance_text <> ''
                AND s.activity = 'TT'
                AND m.participation_type IN ('RUNNER', 'BOTH')
                AND COALESCE(m.leaderboard_opt_out, FALSE) = FALSE
        ),

        best_times AS (
            SELECT DISTINCT ON (member_id, distance_text)
                member_id,
                first_name,
                last_name,
                distance_text,
                time_text,
                seconds AS best_seconds
            FROM normalized
            WHERE distance_text IN ('8', '6', '4')
            ORDER BY member_id, distance_text, seconds ASC, created_at ASC
        ),

        ranked AS (
            SELECT
                *,
                RANK() OVER (
                    PARTITION BY distance_text
                    ORDER BY best_seconds ASC
                ) AS position
            FROM best_times
        )

        SELECT *
        FROM ranked
        WHERE member_id = %s
        ORDER BY CAST(distance_text AS INTEGER) DESC;
        """, (member_id,))

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
