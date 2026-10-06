"""Member consent withdrawal and confirmed erasure from the active database."""

from app.db import get_cursor

DELETE_CONFIRMATION_STATE = "CONFIRM_DELETE_DATA"


def get_member_result_history(member_id: int):
    with get_cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT event_date, mode, distance_text, time_text, status
            FROM submissions
            WHERE member_id = %s
            ORDER BY event_date DESC, id DESC
            """,
            (member_id,),
        )
        return cur.fetchall()


def _remove_queued_member_messages(cur, member_id: int, phone: str) -> None:
    # Both follow-up jobs and serialized WhatsApp sends can contain member data.
    # Completed/failed jobs are removed too; otherwise their payloads retain it.
    cur.execute(
        """
        DELETE FROM job_queue
        WHERE payload->>'member_id' = %s
           OR payload->>'sender' = %s
           OR payload->'payload'->>'to' = %s
        """,
        (str(member_id), phone, phone),
    )
    # A broadcast addressed to someone else can still contain this member's
    # name/result in its already-rendered body. Remove broadcasts for their TT
    # dates; a future broadcast can be freshly rendered without this member.
    cur.execute(
        """
        DELETE FROM job_queue q
        WHERE EXISTS (
            SELECT 1 FROM submissions s
            WHERE s.member_id = %s
              AND q.dedupe_key LIKE ('leaderboard:' || s.event_date::text || ':%')
        )
        """,
        (member_id,),
    )


def withdraw_consent_and_request_erasure(phone: str) -> bool:
    """Stop member processing now; require a separate confirmation to erase."""
    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE members
            SET popia_acknowledged = FALSE,
                popia_withdrawn_at = CURRENT_TIMESTAMP,
                leaderboard_opt_out = TRUE,
                profile_state = %s
            WHERE phone = %s
            RETURNING id
            """,
            (DELETE_CONFIRMATION_STATE, phone),
        )
        member = cur.fetchone()
        if not member:
            return False
        _remove_queued_member_messages(cur, member["id"], phone)
        return True


def cancel_erasure_request(phone: str) -> bool:
    """Cancel erasure without silently restoring withdrawn consent."""
    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE members SET profile_state = NULL
            WHERE phone = %s AND profile_state = %s
            RETURNING id
            """,
            (phone, DELETE_CONFIRMATION_STATE),
        )
        return cur.fetchone() is not None


def erase_member_after_confirmation(phone: str) -> bool:
    """Atomically remove a confirmed member and related active records."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id FROM members
            WHERE phone = %s AND profile_state = %s
            FOR UPDATE
            """,
            (phone, DELETE_CONFIRMATION_STATE),
        )
        member = cur.fetchone()
        if not member:
            return False
        member_id = member["id"]

        _remove_queued_member_messages(cur, member_id, phone)
        # Retain opaque message IDs solely to reject old webhook retries (an
        # old OK must not recreate this profile), but remove sender and errors.
        cur.execute(
            """
            UPDATE inbound_whatsapp_messages
            SET sender = NULL,
                error = NULL,
                status = 'PROCESSED',
                processed_at = COALESCE(processed_at, CURRENT_TIMESTAMP)
            WHERE sender = %s
            """,
            (phone,),
        )
        cur.execute("DELETE FROM member_self_corrections WHERE member_id = %s", (member_id,))
        cur.execute("DELETE FROM admin_corrections WHERE member_id = %s", (member_id,))
        # Corrections made by this member as an admin belong to other members.
        # Keep their correction history but remove this member's identity.
        cur.execute(
            "UPDATE admin_corrections SET admin_member_id = NULL WHERE admin_member_id = %s",
            (member_id,),
        )
        cur.execute("DELETE FROM attendance WHERE member_id = %s", (member_id,))
        cur.execute("DELETE FROM submissions WHERE member_id = %s", (member_id,))
        cur.execute("DELETE FROM members WHERE id = %s", (member_id,))
        return True
