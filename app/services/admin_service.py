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


def correct_runner_time(identifier: str, distance: str, time_text: str, seconds: int):
    lookup = (identifier or "").strip()
    if not lookup:
        return None

    digits = "".join(ch for ch in lookup if ch.isdigit())
    member_id = int(digits) if digits and digits == lookup and len(digits) <= 6 else None
    phone = digits if digits else lookup

    with get_cursor() as cur:
        cur.execute("""
        WITH target AS (
            SELECT
                s.id,
                s.distance_text AS old_distance_text,
                s.time_text AS old_time_text,
                s.seconds AS old_seconds
            FROM submissions s
            JOIN members m ON m.id = s.member_id
            WHERE s.status != 'CANCELLED'
              AND s.tt_code_verified = TRUE
              AND DATE(s.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Johannesburg')
                = CURRENT_DATE
              AND (
                    (%s IS NOT NULL AND m.id = %s)
                    OR (%s <> '' AND m.phone = %s)
              )
            ORDER BY s.created_at DESC
            LIMIT 1
        ),
        updated AS (
            UPDATE submissions s
            SET distance_text = %s,
                time_text = %s,
                seconds = %s,
                status = 'COMPLETE',
                confirmed = TRUE
            FROM target
            WHERE s.id = target.id
            RETURNING
                s.id,
                s.member_id,
                s.distance_text,
                s.time_text,
                s.seconds,
                target.old_distance_text,
                target.old_time_text,
                target.old_seconds
        )
        SELECT
            updated.*,
            m.first_name,
            m.last_name,
            m.phone
        FROM updated
        JOIN members m ON m.id = updated.member_id
        """, (
            member_id,
            member_id,
            phone,
            phone,
            distance,
            time_text,
            seconds,
        ))

        return cur.fetchone()
