from app.db import get_cursor


def get_admin_dashboard():
    with get_cursor(commit=False) as cur:
        cur.execute("""
        SELECT
            COUNT(*) FILTER (WHERE s.tt_code_verified = TRUE) AS checked_in,
            COUNT(*) FILTER (WHERE s.status = 'COMPLETE') AS submitted,
            COUNT(*) FILTER (
                WHERE s.status = 'PENDING'
                  AND s.tt_code_verified = TRUE
            ) AS pending,
            COUNT(*) FILTER (
                WHERE s.tt_code_verified = TRUE
                  AND m.participation_type = 'RUNNER'
            ) AS runners,
            COUNT(*) FILTER (
                WHERE s.tt_code_verified = TRUE
                  AND m.participation_type = 'WALKER'
            ) AS walkers,
            COUNT(*) FILTER (
                WHERE s.tt_code_verified = TRUE
                  AND m.participation_type = 'BOTH'
            ) AS both,
            MAX(s.created_at) FILTER (WHERE s.status = 'COMPLETE') AS last_submission_at
        FROM submissions s
        JOIN members m ON m.id = s.member_id
        WHERE DATE(s.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Johannesburg')
            = CURRENT_DATE
        """)
        summary = cur.fetchone()

        cur.execute("""
        SELECT
            m.first_name,
            m.last_name
        FROM submissions s
        JOIN members m ON m.id = s.member_id
        WHERE s.status = 'PENDING'
          AND s.tt_code_verified = TRUE
          AND DATE(s.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Johannesburg')
            = CURRENT_DATE
        ORDER BY s.created_at ASC
        LIMIT 5
        """)
        pending = cur.fetchall()

    return {
        "summary": summary,
        "pending": pending,
    }


def search_members_for_admin(query: str):
    term = (query or "").strip()
    if not term:
        return []

    digits = "".join(ch for ch in term if ch.isdigit())
    like_term = f"%{term}%"
    phone_term = f"%{digits}%" if digits else None

    with get_cursor(commit=False) as cur:
        cur.execute("""
        SELECT
            m.id,
            m.phone,
            m.first_name,
            m.last_name,
            m.participation_type,
            m.leaderboard_opt_out,
            s.status AS today_status,
            s.tt_code_verified,
            s.distance_text,
            s.time_text,
            s.seconds
        FROM members m
        LEFT JOIN LATERAL (
            SELECT *
            FROM submissions s
            WHERE s.member_id = m.id
              AND s.status != 'CANCELLED'
              AND DATE(s.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Johannesburg')
                = CURRENT_DATE
            ORDER BY s.created_at DESC
            LIMIT 1
        ) s ON TRUE
        WHERE (
            CONCAT_WS(' ', m.first_name, m.last_name) ILIKE %s
            OR m.phone ILIKE COALESCE(%s, '')
        )
        ORDER BY m.first_name ASC, m.last_name ASC
        LIMIT 5
        """, (like_term, phone_term))

        return cur.fetchall()
