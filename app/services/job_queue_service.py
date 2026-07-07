import importlib
import json
import logging
from datetime import datetime, timedelta
from typing import Any

from psycopg2.extras import Json

from app.db import get_cursor

logger = logging.getLogger(__name__)

JOB_POST_CONFIRM_MESSAGES = "post_confirm_messages"
JOB_WHATSAPP_SEND = "whatsapp_send"


def _json_payload(payload: dict[str, Any]):
    return Json(payload, dumps=lambda value: json.dumps(value, default=str))


def enqueue_job(job_type: str, payload: dict[str, Any], run_after: datetime | None = None, max_attempts: int = 3):
    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO job_queue (job_type, payload, run_after, max_attempts)
            VALUES (%s, %s, COALESCE(%s, CURRENT_TIMESTAMP), %s)
            RETURNING id
        """, (job_type, _json_payload(payload), run_after, max_attempts))
        row = cur.fetchone()
        return row["id"] if row else None


def enqueue_post_confirm_messages(sender: str, member: dict, submission: dict, previous_best):
    return enqueue_job(
        JOB_POST_CONFIRM_MESSAGES,
        {
            "sender": sender,
            "member": member,
            "submission": submission,
            "previous_best": previous_best,
        },
    )


def enqueue_whatsapp_send(payload: dict[str, Any]):
    return enqueue_job(JOB_WHATSAPP_SEND, {"payload": payload})


def enqueue_whatsapp_text(to: str, text: str):
    return enqueue_whatsapp_send({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {
            "body": text,
        },
    })


def run_due_jobs(limit: int = 10):
    processed = 0
    for _ in range(limit):
        job = _claim_next_job()
        if not job:
            break
        _run_job(job)
        processed += 1
    return processed


def get_queue_health():
    with get_cursor(commit=False) as cur:
        cur.execute("""
            SELECT
                COUNT(*) FILTER (WHERE status = 'PENDING') AS pending_jobs,
                COUNT(*) FILTER (WHERE status = 'RUNNING') AS running_jobs,
                COUNT(*) FILTER (WHERE status = 'FAILED') AS failed_jobs,
                COUNT(*) FILTER (WHERE status = 'DONE') AS done_jobs,
                COALESCE(
                    EXTRACT(
                        EPOCH FROM (
                            CURRENT_TIMESTAMP
                            - MIN(run_after) FILTER (WHERE status = 'PENDING')
                        )
                    )::integer,
                    0
                ) AS oldest_pending_seconds
            FROM job_queue
        """)
        row = cur.fetchone() or {}

    return {
        "pending_jobs": row.get("pending_jobs") or 0,
        "running_jobs": row.get("running_jobs") or 0,
        "failed_jobs": row.get("failed_jobs") or 0,
        "done_jobs": row.get("done_jobs") or 0,
        "oldest_pending_seconds": row.get("oldest_pending_seconds") or 0,
    }


def _claim_next_job():
    with get_cursor() as cur:
        cur.execute("""
            WITH next_job AS (
                SELECT id
                FROM job_queue
                WHERE status = 'PENDING'
                  AND run_after <= CURRENT_TIMESTAMP
                  AND attempts < max_attempts
                ORDER BY run_after ASC, id ASC
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            UPDATE job_queue q
            SET status = 'RUNNING',
                locked_at = CURRENT_TIMESTAMP,
                attempts = attempts + 1,
                updated_at = CURRENT_TIMESTAMP
            FROM next_job
            WHERE q.id = next_job.id
            RETURNING q.*
        """)
        return cur.fetchone()


def _run_job(job: dict):
    try:
        _dispatch_job(job["job_type"], job["payload"])
    except Exception as exc:
        logger.exception("Job failed: id=%s type=%s", job.get("id"), job.get("job_type"))
        _mark_job_failed(job, exc)
        return

    with get_cursor() as cur:
        cur.execute("""
            UPDATE job_queue
            SET status = 'DONE',
                updated_at = CURRENT_TIMESTAMP,
                last_error = NULL
            WHERE id = %s
        """, (job["id"],))


def _mark_job_failed(job: dict, exc: Exception):
    next_status = "FAILED" if job["attempts"] >= job["max_attempts"] else "PENDING"
    run_after = datetime.utcnow() + timedelta(minutes=min(job["attempts"], 5))

    with get_cursor() as cur:
        cur.execute("""
            UPDATE job_queue
            SET status = %s,
                run_after = %s,
                last_error = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (next_status, run_after, str(exc), job["id"]))


def _dispatch_job(job_type: str, payload: dict):
    if job_type == JOB_POST_CONFIRM_MESSAGES:
        webhook = importlib.import_module("app.webhook")
        webhook.send_post_confirm_messages(
            payload["sender"],
            payload["member"],
            payload["submission"],
            payload.get("previous_best"),
        )
        return

    if job_type == JOB_WHATSAPP_SEND:
        whatsapp = importlib.import_module("app.whatsapp")
        if not whatsapp._send(payload["payload"]):
            raise RuntimeError("WhatsApp send returned false")
        return

    raise ValueError(f"Unknown job type: {job_type}")
