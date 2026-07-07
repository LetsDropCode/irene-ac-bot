# app/services/leaderboard_service.py

from datetime import date

from app.db import get_cursor


def _event_date_filter(event_date):
    if event_date is None:
        return "(CURRENT_TIMESTAMP AT TIME ZONE 'Africa/Johannesburg')::date", ()

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
            AND m.participation_type IN ('RUNNER', 'BOTH')
            AND COALESCE(m.leaderboard_opt_out, FALSE) = FALSE
            AND s.event_date = """ + date_expr + """
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
            AND m.participation_type IN ('WALKER', 'BOTH')
            AND COALESCE(m.leaderboard_opt_out, FALSE) = FALSE
            AND s.event_date = """ + date_expr + """
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
