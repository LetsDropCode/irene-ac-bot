from app.db import get_cursor


def _record_admin_correction(cur, row: dict, admin_member_id: int = None, reason: str = None):
    if not row or not admin_member_id:
        return

    cur.execute("""
        INSERT INTO admin_corrections (
            admin_member_id,
            submission_id,
            member_id,
            old_distance_text,
            old_time_text,
            old_seconds,
            new_distance_text,
            new_time_text,
            new_seconds,
            reason
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        admin_member_id,
        row["id"],
        row["member_id"],
        row.get("old_distance_text"),
        row.get("old_time_text"),
        row.get("old_seconds"),
        row.get("distance_text"),
        row.get("time_text"),
        row.get("seconds"),
        reason,
    ))


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


def get_member_submission_history(identifier: str, limit: int = 20):
    lookup = (identifier or "").strip()
    if not lookup:
        return []

    digits = "".join(ch for ch in lookup if ch.isdigit())
    member_id = int(digits) if digits and digits == lookup and len(digits) <= 6 else None
    phone = digits if digits else lookup

    with get_cursor(commit=False) as cur:
        cur.execute("""
        SELECT
            m.id AS member_id,
            m.first_name,
            m.last_name,
            m.phone,
            m.participation_type,
            s.id AS submission_id,
            s.activity,
            s.distance_text,
            s.time_text,
            s.seconds,
            s.status,
            s.confirmed,
            DATE(s.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Johannesburg') AS event_date,
            s.created_at
        FROM submissions s
        JOIN members m ON m.id = s.member_id
        WHERE s.status != 'CANCELLED'
          AND (
                (%s IS NOT NULL AND m.id = %s)
                OR (%s <> '' AND m.phone = %s)
          )
        ORDER BY s.created_at DESC
        LIMIT %s
        """, (member_id, member_id, phone, phone, limit))

        return cur.fetchall()


def get_submission_for_admin(submission_id: int):
    with get_cursor(commit=False) as cur:
        cur.execute("""
        SELECT
            m.id AS member_id,
            m.first_name,
            m.last_name,
            m.phone,
            s.id AS submission_id,
            s.activity,
            s.distance_text,
            s.time_text,
            s.seconds,
            s.status,
            s.confirmed,
            DATE(s.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Johannesburg') AS event_date,
            s.created_at
        FROM submissions s
        JOIN members m ON m.id = s.member_id
        WHERE s.id = %s
          AND s.status != 'CANCELLED'
        """, (submission_id,))

        return cur.fetchone()


def correct_submission_by_id(
    submission_id: int,
    distance: str,
    time_text: str,
    seconds: int,
    admin_member_id: int = None,
    reason: str = "selected_submission",
):
    with get_cursor() as cur:
        cur.execute("""
        WITH target AS (
            SELECT
                s.id,
                s.distance_text AS old_distance_text,
                s.time_text AS old_time_text,
                s.seconds AS old_seconds,
                DATE(s.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Johannesburg') AS event_date
            FROM submissions s
            WHERE s.id = %s
              AND s.status != 'CANCELLED'
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
                target.event_date,
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
        """, (submission_id, distance, time_text, seconds))

        row = cur.fetchone()
        _record_admin_correction(cur, row, admin_member_id, reason)
        return row


def correct_submission_time_by_id(
    submission_id: int,
    time_text: str,
    seconds: int,
    admin_member_id: int = None,
    reason: str = "selected_submission_time",
):
    with get_cursor() as cur:
        cur.execute("""
        WITH target AS (
            SELECT
                s.id,
                s.distance_text AS old_distance_text,
                s.time_text AS old_time_text,
                s.seconds AS old_seconds,
                DATE(s.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Johannesburg') AS event_date
            FROM submissions s
            WHERE s.id = %s
              AND s.status != 'CANCELLED'
        ),
        updated AS (
            UPDATE submissions s
            SET time_text = %s,
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
                target.event_date,
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
        """, (submission_id, time_text, seconds))

        row = cur.fetchone()
        _record_admin_correction(cur, row, admin_member_id, reason)
        return row


def correct_runner_time(
    identifier: str,
    distance: str,
    time_text: str,
    seconds: int,
    admin_member_id: int = None,
    reason: str = "today_correction",
):
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

        row = cur.fetchone()
        _record_admin_correction(cur, row, admin_member_id, reason)
        return row


def correct_runner_time_on_date(
    identifier: str,
    event_date: str,
    distance: str,
    time_text: str,
    seconds: int,
    admin_member_id: int = None,
    reason: str = "date_correction",
):
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
                s.seconds AS old_seconds,
                DATE(s.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Johannesburg') AS event_date
            FROM submissions s
            JOIN members m ON m.id = s.member_id
            WHERE s.status != 'CANCELLED'
              AND DATE(s.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Johannesburg') = %s
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
                target.event_date,
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
            event_date,
            member_id,
            member_id,
            phone,
            phone,
            distance,
            time_text,
            seconds,
        ))

        row = cur.fetchone()
        _record_admin_correction(cur, row, admin_member_id, reason)
        return row


def correct_runner_pb(
    identifier: str,
    distance: str,
    time_text: str,
    seconds: int,
    admin_member_id: int = None,
    reason: str = "pb_correction",
):
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
                s.seconds AS old_seconds,
                s.created_at AS old_created_at
            FROM submissions s
            JOIN members m ON m.id = s.member_id
            WHERE s.status = 'COMPLETE'
              AND s.seconds IS NOT NULL
              AND s.seconds > 0
              AND s.distance_text IS NOT NULL
              AND s.distance_text <> ''
              AND s.activity = 'TT'
              AND m.participation_type IN ('RUNNER', 'BOTH')
              AND regexp_replace(LOWER(s.distance_text), '[^0-9]', '', 'g') = %s
              AND (
                    (%s IS NOT NULL AND m.id = %s)
                    OR (%s <> '' AND m.phone = %s)
              )
            ORDER BY s.seconds ASC, s.created_at ASC
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
                s.created_at,
                target.old_distance_text,
                target.old_time_text,
                target.old_seconds,
                target.old_created_at
        )
        SELECT
            updated.*,
            m.first_name,
            m.last_name,
            m.phone
        FROM updated
        JOIN members m ON m.id = updated.member_id
        """, (
            distance,
            member_id,
            member_id,
            phone,
            phone,
            distance,
            time_text,
            seconds,
        ))

        row = cur.fetchone()
        _record_admin_correction(cur, row, admin_member_id, reason)
        return row
