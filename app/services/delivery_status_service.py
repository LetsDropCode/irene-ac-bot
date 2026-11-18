"""Correlate signed status events without retaining recipient or error text."""

import re

from app.db import get_cursor

RANK = {"accepted": 0, "sent": 1, "failed": 2, "delivered": 3, "read": 4}


def _upsert(cur, job_id, message_id, status, timestamp=None, code=None):
    # INSERT SELECT avoids resurrecting diagnostics after a privacy erasure.
    cur.execute("""
        INSERT INTO whatsapp_delivery_status
            (message_id, job_id, status, status_rank, event_timestamp, error_code)
        SELECT %s, id, %s, %s, %s, %s FROM job_queue
        WHERE id = %s AND job_type = 'whatsapp_send'
          AND created_at >= CURRENT_TIMESTAMP - INTERVAL '30 days'
        ON CONFLICT (message_id) DO UPDATE SET
            status = EXCLUDED.status, status_rank = EXCLUDED.status_rank,
            event_timestamp = EXCLUDED.event_timestamp, error_code = EXCLUDED.error_code
        WHERE whatsapp_delivery_status.status_rank < EXCLUDED.status_rank
          AND whatsapp_delivery_status.job_id = EXCLUDED.job_id
        RETURNING status
    """, (message_id, status, RANK[status], timestamp, code, job_id))


def record_acceptance(job_id, message_id):
    if not isinstance(message_id, str) or not 1 <= len(message_id) <= 512:
        return
    with get_cursor() as cur:
        _upsert(cur, job_id, message_id, "accepted")


def record_status(event):
    if not isinstance(event, dict) or not isinstance(event.get("status"), str) or event.get("status") not in {"sent", "delivered", "read", "failed"}:
        return False
    message_id = event.get("id")
    if not isinstance(message_id, str) or not 1 <= len(message_id) <= 512:
        return False
    try:
        timestamp = int(event["timestamp"])
        if not 0 <= timestamp <= 253402300799:
            return False
    except (KeyError, TypeError, ValueError):
        return False
    errors = event.get("errors") or []
    code = errors[0].get("code") if isinstance(errors, list) and errors and isinstance(errors[0], dict) else None
    code = code if type(code) is int and 0 <= code <= 2147483647 else None
    with get_cursor() as cur:
        cur.execute("SELECT job_id FROM whatsapp_delivery_status WHERE message_id = %s", (message_id,))
        known = cur.fetchone()
        job_id = known["job_id"] if known else None
        if job_id is None:
            callback = event.get("biz_opaque_callback_data")
            match = re.fullmatch(r"job:([1-9][0-9]{0,9})", callback) if isinstance(callback, str) else None
            if not match:
                return False
            job_id = int(match[1])
            # Early callbacks can arrive before the API response. Check the
            # recipient against the existing queued message without storing it.
            cur.execute("""SELECT id FROM job_queue WHERE id = %s AND job_type = 'whatsapp_send'
                           AND created_at >= CURRENT_TIMESTAMP - INTERVAL '30 days'
                           AND payload->'payload'->>'to' = %s""", (job_id, event.get("recipient_id")))
            if not cur.fetchone():
                return False
        _upsert(cur, job_id, message_id, event["status"], timestamp, code)
        cur.fetchone()
    if event["status"] == "failed":
        from app.services.flow_session_service import queue_calendar_fallback
        queue_calendar_fallback(job_id)
    return True


def prune_native_diagnostics():
    """Run daily via the existing job worker, including after flags are off."""
    with get_cursor() as cur:
        cur.execute("DELETE FROM whatsapp_delivery_status WHERE created_at < CURRENT_TIMESTAMP - INTERVAL '30 days'")
        cur.execute("DELETE FROM whatsapp_flow_sessions WHERE expires_at < CURRENT_TIMESTAMP - INTERVAL '1 day'")
