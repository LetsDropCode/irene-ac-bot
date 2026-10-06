import importlib
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any

from psycopg2.extras import Json

from app.db import get_cursor

logger = logging.getLogger(__name__)

JOB_POST_CONFIRM_MESSAGES = "post_confirm_messages"
JOB_WHATSAPP_SEND = "whatsapp_send"
JOB_INCOMPLETE_REMINDER = "incomplete_submission_reminder"
JOB_ATTENDANCE_MILESTONE = "attendance_milestone"
# All current job handlers are bounded network calls. A five-minute lease is
# deliberately generous, while still allowing a worker crash to self-heal.
STALE_RUNNING_AFTER_SECONDS = int(os.getenv("JOB_STALE_RUNNING_AFTER_SECONDS", "300"))


def _json_payload(payload: dict[str, Any]):
    return Json(payload, dumps=lambda value: json.dumps(value, default=str))


def _insert_job(cur, job_type: str, payload: dict[str, Any], run_after, max_attempts: int, dedupe_key: str | None):
    cur.execute("""
            INSERT INTO job_queue (job_type, payload, run_after, max_attempts, dedupe_key)
            VALUES (%s, %s, COALESCE(%s, CURRENT_TIMESTAMP), %s, %s)
            ON CONFLICT (dedupe_key) DO UPDATE
            SET dedupe_key = job_queue.dedupe_key
            RETURNING id
        """, (job_type, _json_payload(payload), run_after, max_attempts, dedupe_key))
    row = cur.fetchone()
    if not row:
        raise RuntimeError("Job queue insert returned no id")
    return row["id"]


def enqueue_job(job_type: str, payload: dict[str, Any], run_after: datetime | None = None, max_attempts: int = 3, dedupe_key: str | None = None, cursor=None):
    if cursor is not None:
        return _insert_job(cursor, job_type, payload, run_after, max_attempts, dedupe_key)
    with get_cursor() as cur:
        return _insert_job(cur, job_type, payload, run_after, max_attempts, dedupe_key)


def enqueue_post_confirm_messages(sender: str, member: dict, submission: dict, previous_best, cursor=None):
    """Queue only the fields needed for the member follow-up.

    The job is durable, so avoid storing the complete member/profile or
    submission records.  In particular, no raw member dictionary can flow to
    the coaching integration.
    """
    return enqueue_job(
        JOB_POST_CONFIRM_MESSAGES,
        {
            "sender": sender,
            "member_id": member["id"],
            "first_name": member.get("first_name") or "Runner",
            "submission": {
                "id": submission.get("id"),
                "event_date": submission.get("event_date"),
                "distance_text": submission.get("distance_text"),
                "time_text": submission.get("time_text"),
                "seconds": submission.get("seconds"),
            },
            "previous_best": previous_best,
        },
        dedupe_key=f"followup:{submission['id']}",
        cursor=cursor,
    )


def enqueue_whatsapp_send(payload: dict[str, Any], dedupe_key: str | None = None):
    return enqueue_job(JOB_WHATSAPP_SEND, {"payload": payload}, dedupe_key=dedupe_key)


def enqueue_whatsapp_text(to: str, text: str, dedupe_key: str | None = None):
    return enqueue_whatsapp_send({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {
            "body": text,
        },
    }, dedupe_key=dedupe_key)


def run_due_jobs(limit: int = 10):
    recover_stale_running_jobs()
    processed = 0
    for _ in range(limit):
        job = _claim_next_job()
        if not job:
            break
        _run_job(job)
        processed += 1
    return processed


def recover_stale_running_jobs(
    stale_after_seconds: int = STALE_RUNNING_AFTER_SECONDS,
    limit: int = 100,
):
    """Return jobs abandoned by a crashed worker to a runnable terminal path.

    A job that exhausted its attempts becomes FAILED so the existing admin
    retry route can handle it; otherwise it is put back into PENDING. This is
    performed before every normal job run, rather than relying on an operator
    to notice a RUNNING count.
    """
    with get_cursor() as cur:
        cur.execute("""
            WITH stale_jobs AS (
                SELECT id
                FROM job_queue
                WHERE status = 'RUNNING'
                  AND (
                      locked_at IS NULL
                      OR locked_at <= CURRENT_TIMESTAMP
                          - (%s * INTERVAL '1 second')
                  )
                ORDER BY locked_at ASC NULLS FIRST, id ASC
                LIMIT %s
                FOR UPDATE SKIP LOCKED
            )
            UPDATE job_queue q
            SET status = CASE
                    WHEN q.attempts >= q.max_attempts THEN 'FAILED'
                    ELSE 'PENDING'
                END,
                run_after = CURRENT_TIMESTAMP,
                locked_at = NULL,
                last_error = COALESCE(
                    q.last_error,
                    'Recovered after worker lease expired'
                ),
                updated_at = CURRENT_TIMESTAMP
            FROM stale_jobs
            WHERE q.id = stale_jobs.id
            RETURNING q.id
        """, (stale_after_seconds, limit))
        return len(cur.fetchall())


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


def get_failed_jobs(limit: int = 5):
    with get_cursor(commit=False) as cur:
        cur.execute("""
            SELECT id, job_type, attempts, max_attempts, last_error, updated_at
            FROM job_queue
            WHERE status = 'FAILED'
            ORDER BY updated_at DESC, id DESC
            LIMIT %s
        """, (limit,))
        return cur.fetchall()


def retry_failed_jobs(limit: int = 10):
    with get_cursor() as cur:
        cur.execute("""
            WITH jobs_to_retry AS (
                SELECT id
                FROM job_queue
                WHERE status = 'FAILED'
                ORDER BY updated_at ASC, id ASC
                LIMIT %s
                FOR UPDATE SKIP LOCKED
            )
            UPDATE job_queue q
            SET status = 'PENDING',
                attempts = 0,
                run_after = CURRENT_TIMESTAMP,
                locked_at = NULL,
                last_error = NULL,
                updated_at = CURRENT_TIMESTAMP
            FROM jobs_to_retry
            WHERE q.id = jobs_to_retry.id
            RETURNING q.id
        """, (limit,))
        retried = len(cur.fetchall())

    if retried:
        logger.info("Manual retry reset %s failed job(s) to PENDING", retried)
    return retried


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
        if job["job_type"] == JOB_POST_CONFIRM_MESSAGES:
            from app.whatsapp import queue_inbound_replies
            with queue_inbound_replies(f"job:{job['id']}"):
                _dispatch_job(job["job_type"], job["payload"])
        elif (
            job["job_type"] == JOB_WHATSAPP_SEND
            and (job.get("dedupe_key") or "").startswith("leaderboard:")
        ):
            # Hold a share lock through the send. A concurrent withdrawal
            # cannot commit while an old broadcast is still being delivered.
            recipient = job["payload"]["payload"]["to"]
            with get_cursor(commit=False) as cur:
                cur.execute("""
                    SELECT id FROM members
                    WHERE phone = %s AND popia_acknowledged = TRUE
                    FOR SHARE
                """, (recipient,))
                if cur.fetchone():
                    _dispatch_job(job["job_type"], job["payload"])
        else:
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
    if job_type == JOB_INCOMPLETE_REMINDER:
        from app.services.incomplete_reminder_service import send_incomplete_submission_reminder
        send_incomplete_submission_reminder(payload)
        return

    if job_type == JOB_ATTENDANCE_MILESTONE:
        from app.services.engagement_service import send_attendance_milestone
        send_attendance_milestone(payload)
        return

    if job_type == JOB_POST_CONFIRM_MESSAGES:
        webhook = importlib.import_module("app.webhook")
        with get_cursor(commit=False) as cur:
            cur.execute("""
                SELECT id FROM members
                WHERE id = %s AND popia_acknowledged = TRUE
                FOR SHARE
            """, (payload["member_id"],))
            if cur.fetchone():
                webhook.send_post_confirm_messages(
                    payload["sender"],
                    payload["member_id"],
                    payload.get("first_name") or "Runner",
                    payload["submission"],
                    payload.get("previous_best"),
                )
        return

    if job_type == JOB_WHATSAPP_SEND:
        whatsapp = importlib.import_module("app.whatsapp")
        if not whatsapp._send_direct(payload["payload"]):
            raise RuntimeError("WhatsApp send returned false")
        return

    raise ValueError(f"Unknown job type: {job_type}")
