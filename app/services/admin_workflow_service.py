"""Date-specific admin follow-up and revision-guarded correction undo."""

from datetime import date, datetime, timedelta, timezone

from app import config
from app.db import get_cursor
from app.flows.submission_state import resolve_pending_submission_state
from app.services.admin_service import _record_admin_correction
from app.services.job_queue_service import enqueue_job
from app.services.submission_gate import ensure_tt_open, SA_TZ
from app.services.tt_status_service import latest_tt_date

JOB_ADMIN_PROMPT = "admin_pending_prompt"
PAGE_SIZE = 7


def require_admin(sender):
    if sender not in config.ADMIN_NUMBERS:
        raise PermissionError("Administrator access required")


def parse_event(value):
    day = date.fromisoformat(value)
    if day.weekday() != 1 or day > latest_tt_date() or day.year < 2000:
        raise ValueError("Choose a past or current Tuesday.")
    return day


def pending_members(sender, event_date, page=1, member_id=None):
    require_admin(sender)
    if not 1 <= page <= 10000:
        raise ValueError("Invalid page")
    with get_cursor(commit=False) as cur:
        cur.execute("""
            SELECT m.id, m.phone, m.first_name, m.last_name, m.participation_type,
                m.leaderboard_opt_out, m.profile_state,
                s.id AS submission_id, s.status, s.tt_code_verified, s.distance_text,
                s.time_text, s.seconds, s.mode, s.event_date,
                (SELECT MAX(i.received_at) FROM inbound_whatsapp_messages i
                    WHERE i.sender = m.phone AND i.status = 'PROCESSED') AS last_inbound_at,
                (SELECT CASE WHEN q.payload ? 'delivered_at' THEN 'SENT' ELSE q.status END FROM job_queue q WHERE q.dedupe_key =
                    'admin-prompt:' || m.id::text || ':' || a.event_date::text LIMIT 1) AS prompt_status,
                (SELECT q.status FROM job_queue q WHERE q.job_type = 'incomplete_submission_reminder'
                    AND q.payload->>'member_id' = m.id::text
                    AND q.payload->>'event_date' = a.event_date::text
                    ORDER BY q.id DESC LIMIT 1) AS reminder_status
            FROM attendance a JOIN members m ON m.id = a.member_id
            LEFT JOIN LATERAL (SELECT * FROM submissions s WHERE s.member_id = m.id
                AND s.activity = 'TT' AND s.event_date = a.event_date AND s.status = 'PENDING'
                ORDER BY s.id DESC LIMIT 1) s ON TRUE
            WHERE a.event = 'TT' AND a.event_date = %s AND m.popia_acknowledged = TRUE
                AND (%s IS NULL OR m.id = %s)
                AND NOT EXISTS (SELECT 1 FROM submissions done WHERE done.member_id = m.id
                    AND done.activity = 'TT' AND done.event_date = a.event_date AND done.status = 'COMPLETE')
            ORDER BY a.created_at, m.id LIMIT %s OFFSET %s
        """, (event_date, member_id, member_id, PAGE_SIZE + 1 if member_id is None else 1,
              (page - 1) * PAGE_SIZE if member_id is None else 0))
        rows = cur.fetchall()
    return rows[:PAGE_SIZE], len(rows) > PAGE_SIZE


def pending_stage(row):
    if not row.get("submission_id"):
        return "No result entry started"
    if not row.get("tt_code_verified"):
        return "Check-in needs review"
    return {
        "awaiting_workout": "Workout note not entered",
        "awaiting_workout_confirm": "Awaiting workout confirmation",
        "awaiting_both_choice": "Run/walk choice not selected",
        "awaiting_distance": "Distance not selected",
        "awaiting_time": "Time not entered",
        "awaiting_confirm": "Awaiting confirmation",
    }[resolve_pending_submission_state(row, row)]


def prompt_eligibility(row, event_date, now=None):
    now = now or datetime.now(SA_TZ)
    now = now.replace(tzinfo=SA_TZ) if now.tzinfo is None else now.astimezone(SA_TZ)
    if event_date not in {now.date(), now.date() - timedelta(days=1)}:
        return False, "This TT's submission window has closed. Use Add missed TT if needed."
    allowed, _ = ensure_tt_open(now=now, submission_event_date=event_date)
    if not allowed:
        return False, "This TT's submission window has closed. Use Add missed TT if needed."
    if not row.get("submission_id") or not row.get("tt_code_verified"):
        return False, "There is no verified unfinished entry to resume. Open the member record."
    # Free-form prompts require a live WhatsApp customer-service window.
    inbound = row.get("last_inbound_at")
    if inbound and inbound.tzinfo is None:
        inbound = inbound.replace(tzinfo=timezone.utc)
    if not inbound or not timedelta(0) <= now - inbound < timedelta(hours=24):
        return False, "The member needs to message the bot again before a prompt can be resent."
    if row.get("reminder_status") in {"PENDING", "RUNNING", "DONE"}:
        return False, "A result reminder is already queued or sent for this TT."
    return True, None


def queue_member_prompt(sender, member_id, event_date):
    require_admin(sender)
    rows, _ = pending_members(sender, event_date, member_id=member_id)
    if not rows:
        return False, "This member no longer has an outstanding result."
    row = rows[0]
    if row.get("prompt_status"):
        return False, "A prompt is already recorded for this TT. Check Queue status for its outcome."
    allowed, reason = prompt_eligibility(row, event_date)
    if not allowed:
        return False, reason
    enqueue_job(JOB_ADMIN_PROMPT, {"member_id": member_id, "event_date": event_date.isoformat()},
                dedupe_key=f"admin-prompt:{member_id}:{event_date.isoformat()}")
    return True, "Prompt queued once for this member. Delivery rechecks their result and deadline."


def deliver_member_prompt(payload):
    from app.whatsapp import _send_direct
    event_date = date.fromisoformat(payload["event_date"])
    # Protect consent/result during network delivery. Don't enqueue a second,
    # rendered message that could bypass the checks on a later retry.
    with get_cursor() as cur:
        cur.execute("""
            SELECT m.phone, m.participation_type, s.*,
                (SELECT MAX(received_at) FROM inbound_whatsapp_messages WHERE sender = m.phone AND status = 'PROCESSED') AS last_inbound_at,
                (SELECT status FROM job_queue q WHERE q.job_type = 'incomplete_submission_reminder'
                    AND q.payload->>'member_id' = m.id::text AND q.payload->>'event_date' = s.event_date::text
                    ORDER BY q.id DESC LIMIT 1) AS reminder_status
            FROM members m JOIN submissions s ON s.member_id = m.id
            WHERE m.id = %s AND m.popia_acknowledged = TRUE AND s.activity = 'TT'
                AND s.event_date = %s AND s.status = 'PENDING' AND s.tt_code_verified = TRUE
                AND NOT EXISTS (SELECT 1 FROM submissions done WHERE done.member_id = m.id
                    AND done.activity = 'TT' AND done.event_date = s.event_date AND done.status = 'COMPLETE')
            FOR SHARE OF m, s
        """, (payload["member_id"], event_date))
        row = cur.fetchone()
        if not row:
            return False
        row["submission_id"] = row["id"]
        allowed, _ = prompt_eligibility(row, event_date)
        if not allowed:
            return False
        body = f"Your {event_date:%d %B} TT result is unfinished: {pending_stage(row).lower()}. Reply RESUME to continue where you left off."
        if not _send_direct({"messaging_product": "whatsapp", "to": row["phone"], "type": "text", "text": {"body": body}}):
            raise RuntimeError("Admin prompt send failed")
        cur.execute("""UPDATE job_queue SET payload = payload || jsonb_build_object('delivered_at', CURRENT_TIMESTAMP)
            WHERE dedupe_key = %s""", (f"admin-prompt:{payload['member_id']}:{event_date}",))
    return True


def recent_changes(sender, member_id=None, page=1, correction_id=None):
    require_admin(sender)
    if not 1 <= page <= 10000:
        raise ValueError("Invalid page")
    with get_cursor(commit=False) as cur:
        cur.execute("""
            SELECT c.*, m.first_name, m.last_name, s.event_date, s.revision,
                a.first_name AS admin_first_name, a.last_name AS admin_last_name
            FROM admin_corrections c JOIN members m ON m.id = c.member_id
            JOIN submissions s ON s.id = c.submission_id
            LEFT JOIN members a ON a.id = c.admin_member_id
            WHERE m.popia_acknowledged = TRUE
                AND (%s IS NULL OR c.member_id = %s) AND (%s IS NULL OR c.id = %s)
            ORDER BY c.id DESC LIMIT %s OFFSET %s
        """, (member_id, member_id, correction_id, correction_id, PAGE_SIZE + 1,
              (page - 1) * PAGE_SIZE))
        rows = cur.fetchall()
    return rows[:PAGE_SIZE], len(rows) > PAGE_SIZE


def can_undo(row):
    return (row.get("before_state") is not None and row.get("after_revision") == row.get("revision")
            and not (row.get("reason") or "").startswith("undo:"))


def undo_correction(sender, correction_id):
    require_admin(sender)
    with get_cursor() as cur:
        cur.execute("SELECT id FROM members WHERE phone = %s AND popia_acknowledged = TRUE", (sender,))
        admin = cur.fetchone()
        if not admin:
            return False, "An active admin profile is required."
        # Match the member -> submission lock order used by admin missed-TT entry.
        cur.execute("""SELECT m.id FROM members m JOIN admin_corrections c ON c.member_id = m.id
            WHERE c.id = %s AND m.popia_acknowledged = TRUE FOR UPDATE OF m""", (correction_id,))
        if not cur.fetchone():
            return False, "The member or change is no longer available."
        cur.execute("""SELECT c.*, s.revision FROM admin_corrections c
            JOIN submissions s ON s.id = c.submission_id WHERE c.id = %s FOR UPDATE OF s, c""", (correction_id,))
        change = cur.fetchone()
        if not change or not can_undo(change):
            return False, "Undo is unavailable: the result changed again, was already undone, or this older change has no complete snapshot."
        state = change["before_state"]
        if state["status"] == "PENDING":
            cur.execute("""SELECT 1 FROM submissions old JOIN submissions other
                ON old.member_id = other.member_id AND old.event_date = other.event_date
                WHERE old.id = %s AND other.id <> old.id AND other.status = 'PENDING'""", (change["submission_id"],))
            if cur.fetchone():
                return False, "Undo would conflict with a newer pending result. Review the member history."
        cur.execute("""SELECT jsonb_build_object('distance_text', distance_text, 'time_text', time_text,
            'seconds', seconds, 'mode', mode, 'status', status, 'confirmed', confirmed) AS state
            FROM submissions WHERE id = %s""", (change["submission_id"],))
        current = cur.fetchone()["state"]
        cur.execute("""UPDATE submissions SET distance_text = %s, time_text = %s, seconds = %s,
            mode = %s, status = %s, confirmed = %s WHERE id = %s RETURNING *""",
            (state["distance_text"], state["time_text"], state["seconds"], state["mode"], state["status"],
             state["confirmed"], change["submission_id"]))
        restored = dict(cur.fetchone(), old_state=current, old_distance_text=current["distance_text"],
                        old_time_text=current["time_text"], old_seconds=current["seconds"])
        _record_admin_correction(cur, restored, admin["id"], f"undo:{correction_id}")
        # Don't deliver stale queued result congratulations after an undo.
        cur.execute("""DELETE FROM job_queue WHERE job_type = 'post_confirm_messages'
            AND payload->'submission'->>'id' = %s AND status IN ('PENDING', 'FAILED')""", (str(change["submission_id"]),))
    return True, "Correction undone. The previous result is restored and the undo is recorded."
