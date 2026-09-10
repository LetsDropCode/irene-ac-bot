# app/services/submission_service.py
from app.db import get_cursor
from app.services.submission_gate import self_correctable_event_date


def get_or_create_submission(member_id: int):
    with get_cursor(commit=False) as cur:

        cur.execute("""
            SELECT *
            FROM submissions
            WHERE member_id = %s
                AND status != 'CANCELLED'
                AND event_date = (CURRENT_TIMESTAMP AT TIME ZONE 'Africa/Johannesburg')::date
            ORDER BY created_at DESC
             LIMIT 1
        """, (member_id,))

        w = cur.fetchone()

        if w:
            return w

    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO submissions (member_id, activity, status, time_text, seconds, event_date)
            VALUES (
                %s,
                'TT',
                'PENDING',
                '',
                0,
                (CURRENT_TIMESTAMP AT TIME ZONE 'Africa/Johannesburg')::date
            )
            ON CONFLICT (member_id, event_date)
            WHERE status = 'PENDING'
            DO UPDATE SET member_id = EXCLUDED.member_id
            RETURNING *
        """, (member_id,))

        return cur.fetchone()


def get_resumable_submission(member_id: int):
    """Return today's, or last night's, verified pending TT submission.

    A checked-in member may finish the following morning, but only before the
    submission gate's next-day deadline. The gate remains responsible for
    enforcing that deadline.
    """
    with get_cursor(commit=False) as cur:
        cur.execute("""
            SELECT *
            FROM submissions
            WHERE member_id = %s
              AND status = 'PENDING'
              AND tt_code_verified = TRUE
              AND event_date IN (
                  (CURRENT_TIMESTAMP AT TIME ZONE 'Africa/Johannesburg')::date,
                  (CURRENT_TIMESTAMP AT TIME ZONE 'Africa/Johannesburg')::date - 1
              )
            ORDER BY event_date DESC, created_at DESC
            LIMIT 1
        """, (member_id,))
        return cur.fetchone()


def get_active_submission(member_id: int):
    """Return a legacy, unfinished submission for today without creating one.

    New check-ins are created only after the TT gate and code validation. This
    lookup exists solely so members with a pre-existing pending row can finish
    it safely during the transition.
    """
    with get_cursor(commit=False) as cur:
        cur.execute("""
            SELECT *
            FROM submissions
            WHERE member_id = %s
              AND status = 'PENDING'
              AND event_date = (CURRENT_TIMESTAMP AT TIME ZONE 'Africa/Johannesburg')::date
            ORDER BY created_at DESC
            LIMIT 1
        """, (member_id,))
        return cur.fetchone()


def get_completed_submission_for_current_event(member_id: int):
    """Find today's completed TT for the member's self-correction path."""
    with get_cursor(commit=False) as cur:
        cur.execute("""
            SELECT *
            FROM submissions
            WHERE member_id = %s
              AND status = 'COMPLETE'
              AND activity = 'TT'
              AND event_date = (CURRENT_TIMESTAMP AT TIME ZONE 'Africa/Johannesburg')::date
            ORDER BY created_at DESC
            LIMIT 1
        """, (member_id,))
        return cur.fetchone()


def get_self_correctable_tt_submission(member_id: int):
    """Resolve the member's completed TT that may still be self-corrected.

    The resolver selects only the configured TT event date for today or its
    immediate recovery day. The caller applies ``ensure_tt_open`` to that
    date, keeping the existing Tuesday-to-Wednesday deadline authoritative.
    """
    event_date = self_correctable_event_date()
    if not event_date:
        return None

    with get_cursor(commit=False) as cur:
        cur.execute("""
            SELECT *
            FROM submissions
            WHERE member_id = %s
              AND status = 'COMPLETE'
              AND activity = 'TT'
              AND tt_code_verified = TRUE
              AND event_date = %s
            ORDER BY created_at DESC
            LIMIT 1
        """, (member_id, event_date))
        return cur.fetchone()


def start_member_self_correction(member_id: int, submission_id: int, mode: str):
    """Create or resume a transient proposal without touching the result."""
    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO member_self_corrections (member_id, submission_id, mode)
            SELECT %s, s.id, %s
            FROM submissions s
            WHERE s.id = %s
              AND s.member_id = %s
              AND s.status = 'COMPLETE'
              AND s.activity = 'TT'
              AND s.tt_code_verified = TRUE
            ON CONFLICT (submission_id) DO UPDATE
            SET updated_at = CURRENT_TIMESTAMP
            RETURNING *
        """, (member_id, mode, submission_id, member_id))
        return cur.fetchone()


def get_member_self_correction(member_id: int):
    """Return a member's active proposal together with immutable original data."""
    with get_cursor(commit=False) as cur:
        cur.execute("""
            SELECT
                c.id,
                c.member_id,
                c.submission_id,
                c.mode,
                c.distance_text,
                c.time_text,
                c.seconds,
                s.event_date,
                s.distance_text AS original_distance_text,
                s.time_text AS original_time_text,
                s.seconds AS original_seconds
            FROM member_self_corrections c
            JOIN submissions s ON s.id = c.submission_id
            WHERE c.member_id = %s
              AND s.status = 'COMPLETE'
              AND s.tt_code_verified = TRUE
            ORDER BY c.updated_at DESC, c.id DESC
            LIMIT 1
        """, (member_id,))
        return cur.fetchone()


def save_member_self_correction_distance(correction_id: int, member_id: int, distance: str):
    with get_cursor() as cur:
        cur.execute("""
            UPDATE member_self_corrections
            SET distance_text = %s,
                time_text = NULL,
                seconds = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
              AND member_id = %s
              AND mode = 'RUN'
            RETURNING *
        """, (distance, correction_id, member_id))
        return cur.fetchone()


def save_member_self_correction_time(correction_id: int, member_id: int, time_text: str, seconds: int):
    with get_cursor() as cur:
        cur.execute("""
            UPDATE member_self_corrections
            SET time_text = %s,
                seconds = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
              AND member_id = %s
              AND mode = 'RUN'
              AND distance_text IN ('4', '6', '8')
            RETURNING *
        """, (time_text, seconds, correction_id, member_id))
        return cur.fetchone()


def save_member_self_correction_workout(correction_id: int, member_id: int, workout: str):
    with get_cursor() as cur:
        cur.execute("""
            UPDATE member_self_corrections
            SET distance_text = NULL,
                time_text = %s,
                seconds = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
              AND member_id = %s
              AND mode = 'WORKOUT'
            RETURNING *
        """, (workout, correction_id, member_id))
        return cur.fetchone()


def cancel_member_self_correction(correction_id: int, member_id: int):
    with get_cursor() as cur:
        cur.execute("""
            DELETE FROM member_self_corrections
            WHERE id = %s AND member_id = %s
            RETURNING id
        """, (correction_id, member_id))
        return cur.fetchone()


def apply_member_self_correction(correction_id: int, member_id: int):
    """Atomically apply a complete proposal and consume it exactly once."""
    with get_cursor() as cur:
        cur.execute("""
            WITH proposal AS (
                DELETE FROM member_self_corrections
                WHERE id = %s
                  AND member_id = %s
                  AND (
                    (mode = 'RUN' AND distance_text IN ('4', '6', '8')
                     AND COALESCE(time_text, '') <> '' AND COALESCE(seconds, 0) > 0)
                    OR
                    (mode = 'WORKOUT' AND COALESCE(time_text, '') <> '')
                  )
                RETURNING *
            )
            UPDATE submissions s
            SET distance_text = CASE WHEN p.mode = 'WORKOUT' THEN NULL ELSE p.distance_text END,
                time_text = p.time_text,
                seconds = CASE WHEN p.mode = 'WORKOUT' THEN 0 ELSE p.seconds END,
                mode = p.mode,
                status = 'COMPLETE',
                confirmed = TRUE
            FROM proposal p
            WHERE s.id = p.submission_id
              AND s.member_id = p.member_id
              AND s.status = 'COMPLETE'
              AND s.tt_code_verified = TRUE
            RETURNING s.*
        """, (correction_id, member_id))
        return cur.fetchone()


def verify_tt_code(submission_id: int, code: str):

    with get_cursor() as cur:

        cur.execute("""
            UPDATE submissions
            SET tt_code = %s,
                tt_code_verified = TRUE
            WHERE id = %s
            RETURNING *
        """, (code, submission_id))

        return cur.fetchone()


def save_distance(submission_id: int, distance: str):

    with get_cursor() as cur:

        cur.execute("""
            UPDATE submissions
            SET distance_text = %s,
                time_text = '',
                seconds = 0,
                mode = 'RUN'
            WHERE id = %s
            RETURNING *
        """, (distance, submission_id))

        return cur.fetchone()


def reopen_submission_for_edit(submission_id: int):
    with get_cursor() as cur:
        cur.execute("""
            UPDATE submissions
            SET status = 'PENDING',
                confirmed = FALSE,
                distance_text = NULL,
                time_text = '',
                seconds = 0,
                mode = 'RUN'
            WHERE id = %s
            RETURNING *
        """, (submission_id,))

        return cur.fetchone()


def reopen_workout_submission_for_edit(submission_id: int):
    with get_cursor() as cur:
        cur.execute("""
            UPDATE submissions
            SET status = 'PENDING',
                confirmed = FALSE,
                distance_text = NULL,
                time_text = '',
                seconds = 0,
                mode = 'WORKOUT'
            WHERE id = %s
            RETURNING *
        """, (submission_id,))
        return cur.fetchone()


def set_submission_mode(submission_id: int, mode: str):
    with get_cursor() as cur:
        cur.execute("""
            UPDATE submissions
            SET mode = %s
            WHERE id = %s
            RETURNING *
        """, (mode, submission_id))
        return cur.fetchone()


def save_workout_for_confirmation(submission_id: int, workout_text: str):
    """Persist a verified workout note while leaving it available for review.

    Keeping the submission pending means a failed WhatsApp delivery, or a
    member returning later, can resume at the Confirm/Edit screen.
    """
    with get_cursor() as cur:
        cur.execute("""
            UPDATE submissions
            SET time_text = %s,
                seconds = 0,
                distance_text = NULL,
                mode = 'WORKOUT',
                status = 'PENDING',
                confirmed = FALSE
            WHERE id = %s
              AND status = 'PENDING'
              AND tt_code_verified = TRUE
              AND COALESCE(time_text, '') = ''
            RETURNING *
        """, (workout_text, submission_id))
        return cur.fetchone()


def confirm_workout_submission(submission_id: int):
    """Complete a saved workout exactly once.

    The legacy condition keeps recovery working for old workout rows that did
    not have ``mode`` populated, while excluding runner submissions.
    """
    with get_cursor() as cur:
        cur.execute("""
            UPDATE submissions
            SET status = 'COMPLETE',
                confirmed = TRUE,
                mode = 'WORKOUT'
            WHERE id = %s
              AND status = 'PENDING'
              AND tt_code_verified = TRUE
              AND COALESCE(time_text, '') <> ''
              AND (
                    mode = 'WORKOUT'
                    OR (distance_text IS NULL AND mode IS NULL)
              )
            RETURNING *
        """, (submission_id,))
        return cur.fetchone()


def save_time(submission_id: int, time_text: str, seconds: int):

    with get_cursor() as cur:

        cur.execute("""
            UPDATE submissions
            SET time_text = %s,
                seconds = %s
            WHERE id = %s
            RETURNING *
        """, (time_text, seconds, submission_id))

        return cur.fetchone()


def confirm_submission(submission_id: int):
    """Complete a reviewed runner result exactly once.

    The confirmation button can be delivered late, so the database—not only
    the webhook state machine—must reject a confirmation until the checked-in
    submission contains a complete runner result.
    """
    with get_cursor() as cur:

        cur.execute("""
            UPDATE submissions
            SET status = 'COMPLETE',
                confirmed = TRUE,
                mode = 'RUN'
            WHERE id = %s
              AND status = 'PENDING'
              AND tt_code_verified = TRUE
              AND distance_text IN ('4', '6', '8')
              AND COALESCE(time_text, '') <> ''
              AND COALESCE(seconds, 0) > 0
            RETURNING *
        """, (submission_id,))

        return cur.fetchone()

def release_pending_submissions(member_id: int):
    """
    Cancel ONLY abandoned / unverified submissions.
    Never touch active sessions.
    """

    with get_cursor() as cur:
        cur.execute("""
            UPDATE submissions
            SET status = 'CANCELLED'
            WHERE member_id = %s
              AND status = 'PENDING'
              AND event_date = (CURRENT_TIMESTAMP AT TIME ZONE 'Africa/Johannesburg')::date
              AND tt_code_verified = FALSE
        """, (member_id,))

        # This UPDATE intentionally has no RETURNING clause. Calling fetchone()
        # here raises psycopg2.ProgrammingError ("no results to fetch"), which
        # stopped every valid TT-code submission before it could be verified.
        return cur.rowcount

def get_pending_members():
    with get_cursor(commit=False) as cur:

        cur.execute("""
        SELECT
            m.id,
            m.first_name,
            m.last_name,
            m.phone,
            s.distance_text,
            s.time_text,
            s.created_at
        FROM submissions s
        JOIN members m ON m.id = s.member_id
        WHERE
            s.status = 'PENDING'
            AND s.tt_code_verified = TRUE
            AND s.event_date = (CURRENT_TIMESTAMP AT TIME ZONE 'Africa/Johannesburg')::date
        ORDER BY s.created_at ASC
        """)

        return cur.fetchall()


def get_tonight_unprompted_checked_in_members():
    """Return every checked-in member with an unfinished result for today.

    The legacy name is retained because this powers the existing admin recovery
    action. Returning partial submissions lets recovery continue at the correct
    step rather than restarting someone who has already supplied a distance.
    """
    with get_cursor(commit=False) as cur:
        cur.execute("""
        SELECT
            m.id AS member_id,
            m.phone,
            m.participation_type,
            m.profile_state,
            s.id AS submission_id,
            s.distance_text,
            s.time_text,
            s.mode,
            s.status,
            s.tt_code_verified
        FROM submissions s
        JOIN members m ON m.id = s.member_id
        WHERE
            s.status = 'PENDING'
            AND s.tt_code_verified = TRUE
            AND s.event_date = (CURRENT_TIMESTAMP AT TIME ZONE 'Africa/Johannesburg')::date
        ORDER BY s.created_at ASC
        """)

        return cur.fetchall()
