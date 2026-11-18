"""Static Flow registry and atomic, owner-bound completion callbacks.

Callbacks run under the member/session locks and must use the supplied cursor
for every write and queued reply. Never perform network I/O in a callback.
Dynamic data exchange is intentionally not implemented.
"""

import hashlib
import json
import secrets
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from zoneinfo import ZoneInfo

from app import config
from app.db import get_cursor
from app.native_messages import reply_buttons, static_flow
from app.services.job_queue_service import enqueue_job, JOB_WHATSAPP_SEND
from app.services.admin_submission_service import validate_event_date


@dataclass(frozen=True)
class StaticFlow:
    key: str
    state_prefix: str
    admin_only: bool
    validate: Callable
    complete: Callable


REGISTRY = {}


def register_static_flow(definition):
    if definition.key in REGISTRY:
        raise ValueError("Flow key already registered")
    REGISTRY[definition.key] = definition


def parse_completion(response_json):
    if not isinstance(response_json, str) or len(response_json) > 16384:
        return {}
    try:
        data = json.loads(response_json)
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict) or not isinstance(data.get("flow_token"), str):
        return {}
    if not 16 <= len(data["flow_token"]) <= 256:
        return {}
    return data


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def enqueue_flow_launch(cur, member, definition, payload_builder):
    """Bind a random token to the exact state and atomically queue its launch."""
    if not member.get("popia_acknowledged") or (definition.admin_only and member.get("phone") not in config.ADMIN_NUMBERS):
        raise PermissionError("Flow owner is not authorized")
    from app.whatsapp import current_reply_key
    reply_key = current_reply_key()
    dedupe_key = f"flow-launch:{definition.key}:{reply_key}" if reply_key else None
    if dedupe_key:
        cur.execute("SELECT id FROM job_queue WHERE dedupe_key = %s", (dedupe_key,))
        existing = cur.fetchone()
        if existing:
            return existing["id"]
    state = member.get("profile_state") or ""
    if not state.startswith(definition.state_prefix):
        raise ValueError("Unexpected Flow conversation state")
    token = secrets.token_urlsafe(32)
    cur.execute("""INSERT INTO whatsapp_flow_sessions
        (token_hash, member_id, flow_key, expected_state, expires_at)
        VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP + INTERVAL '30 minutes')""",
        (_hash(token), member["id"], definition.key, state))
    return enqueue_job(JOB_WHATSAPP_SEND, {"payload": payload_builder(token), "flow_session_hash": _hash(token)},
                       dedupe_key=dedupe_key or f"flow-launch:{_hash(token)}", cursor=cur)


def launch_admin_calendar(sender, member_name, draft_token, flow_id):
    if sender not in config.ADMIN_NUMBERS:
        return False
    with get_cursor() as cur:
        cur.execute("SELECT * FROM members WHERE phone = %s FOR UPDATE", (sender,))
        member = cur.fetchone()
        if not member or not member["popia_acknowledged"]:
            return False
        state = member.get("profile_state") or ""
        if not state.startswith("ADMIN_ADD_TT|"):
            return False
        draft = json.loads(state.split("|", 1)[1])
        if draft.get("step") != "date" or draft.get("token") != draft_token:
            return False
        job_id = enqueue_flow_launch(cur, member, REGISTRY["admin_tt_date"], lambda token: static_flow(
            sender, f"Add missed TT: {member_name}\nChoose a date, or type YYYY-MM-DD here. Type CANCEL anytime.",
            flow_id=flow_id, token=token, cta="Choose TT date", screen="TT_DATE",
            data={"max_date": datetime.now(ZoneInfo("Africa/Johannesburg")).date().isoformat()}))
    from app.whatsapp import collect_reply_job
    collect_reply_job(job_id)
    return True


def complete_flow(sender, data):
    if not config.WHATSAPP_FLOWS_ENABLED:
        return "disabled", None
    token = data.get("flow_token") if isinstance(data, dict) else None
    if not isinstance(token, str) or not 16 <= len(token) <= 256:
        return "invalid", None
    with get_cursor() as cur:
        # Match privacy service lock order: member first, then child records.
        cur.execute("SELECT * FROM members WHERE phone = %s FOR UPDATE", (sender,))
        member = cur.fetchone()
        if not member or not member["popia_acknowledged"]:
            return "unauthorized", None
        cur.execute("SELECT * FROM whatsapp_flow_sessions WHERE token_hash = %s AND member_id = %s FOR UPDATE",
                    (_hash(token), member["id"]))
        session = cur.fetchone()
        if not session:
            return "stale", None
        definition = REGISTRY.get(session["flow_key"])
        if not definition or (definition.admin_only and sender not in config.ADMIN_NUMBERS):
            return "unauthorized", None
        if session["consumed_at"] is not None:
            return "duplicate", None
        if session["expires_at"] <= datetime.now(timezone.utc):
            return "expired", None
        if member.get("profile_state") != session["expected_state"]:
            return "stale", None
        try:
            validated = definition.validate(data, member)
        except (ValueError, TypeError, KeyError):
            return "invalid", None
        job_id = definition.complete(cur, member, validated, session["token_hash"])
        cur.execute("UPDATE whatsapp_flow_sessions SET consumed_at = CURRENT_TIMESTAMP WHERE token_hash = %s",
                    (session["token_hash"],))
    return "completed", job_id


def _validate_calendar(data, member):
    draft = json.loads(member["profile_state"].split("|", 1)[1])
    if draft.get("step") != "date" or not isinstance(data.get("event_date"), str):
        raise ValueError("Unexpected calendar response")
    draft.update(date=validate_event_date(data["event_date"]).isoformat(), step="mode")
    return draft


def _complete_calendar(cur, member, draft, token_hash):
    cur.execute("UPDATE members SET profile_state = %s WHERE id = %s",
                ("ADMIN_ADD_TT|" + json.dumps(draft, ensure_ascii=False), member["id"]))
    return enqueue_job(JOB_WHATSAPP_SEND, {"payload": reply_buttons(
        member["phone"], "Choose the result type for this TT date.",
        [("admin_add_run", "Run"), ("admin_add_workout", "Workout")])},
        dedupe_key=f"flow-complete:{token_hash}", cursor=cur)


def queue_calendar_fallback(job_id):
    """Recover an undeliverable calendar while its member session is current.

    Never use this for templates or an expired/abandoned conversation. The
    session's 30-minute lifetime keeps this reply within its initiation window.
    """
    with get_cursor() as cur:
        cur.execute("SELECT payload FROM job_queue WHERE id = %s AND job_type = 'whatsapp_send'", (job_id,))
        row = cur.fetchone()
        if not row:
            return
        payload = row["payload"].get("payload", {})
        interactive = payload.get("interactive", {})
        if interactive.get("type") != "flow":
            return
        token = interactive.get("action", {}).get("parameters", {}).get("flow_token")
        if not isinstance(token, str):
            return
        # Take the member lock before inserting a queue row, matching erasure.
        cur.execute("SELECT id FROM members WHERE phone = %s FOR SHARE", (payload.get("to"),))
        if not cur.fetchone():
            return
        cur.execute("""SELECT m.phone FROM whatsapp_flow_sessions s JOIN members m ON m.id = s.member_id
            WHERE s.token_hash = %s AND s.flow_key = 'admin_tt_date'
              AND s.consumed_at IS NULL AND s.expires_at > CURRENT_TIMESTAMP
              AND m.popia_acknowledged = TRUE AND m.profile_state = s.expected_state
              AND m.phone = %s
              AND NOT EXISTS (SELECT 1 FROM whatsapp_delivery_status d WHERE d.job_id = %s AND d.status_rank >= 3)""", (_hash(token), payload.get("to"), job_id))
        member = cur.fetchone()
        if member and member["phone"] in config.ADMIN_NUMBERS:
            enqueue_job(JOB_WHATSAPP_SEND, {"flow_session_hash": _hash(token), "payload": {
                "messaging_product": "whatsapp", "to": member["phone"], "type": "text",
                "text": {"body": "The calendar could not be delivered. Send the TT date as YYYY-MM-DD or DD/MM/YYYY, or type CANCEL."},
            }}, dedupe_key=f"flow-fallback:{job_id}", cursor=cur)


@contextmanager
def flow_delivery_guard(token_hash, recipient):
    """Drop delayed launches/fallbacks after expiry, cancellation or erasure."""
    with get_cursor(commit=False) as cur:
        cur.execute("""SELECT s.flow_key FROM whatsapp_flow_sessions s
            JOIN members m ON m.id = s.member_id
            WHERE s.token_hash = %s AND m.phone = %s AND m.popia_acknowledged = TRUE
              AND s.expected_state = m.profile_state AND s.consumed_at IS NULL
              AND s.expires_at > CURRENT_TIMESTAMP FOR SHARE OF m""", (token_hash, recipient))
        session = cur.fetchone()
        definition = REGISTRY.get(session["flow_key"]) if session else None
        yield bool(definition and (not definition.admin_only or recipient in config.ADMIN_NUMBERS))


register_static_flow(StaticFlow("admin_tt_date", "ADMIN_ADD_TT|", True, _validate_calendar, _complete_calendar))
