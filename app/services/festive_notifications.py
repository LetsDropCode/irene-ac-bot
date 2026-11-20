"""Durable, consent-aware notifications using the existing scheduled job runner.

Cloud API does not promise client-key exactly-once delivery. A persisted SENDING
claim is never automatically resent after a crash/timeout: uncertain delivery
requires operator reconciliation. Queue retries therefore cannot double-send.
"""

import os
from datetime import datetime, time, timedelta

import requests

from app.config import ADMIN_NUMBERS, PHONE_NUMBER_ID, WHATSAPP_TOKEN
from app.db import get_cursor
from app.services import festive_service as domain
from app.services.festive_config import enabled, flag
from app.services.job_queue_service import enqueue_job
from app.services.proactive_template_service import proactive_template_payload


def record(cur, row, recipient, kind, scheduled):
    key = f"festive:{row['id']}:{kind}:{recipient}"
    cur.execute(
        """INSERT INTO festive_run_notifications(run_slot_id,recipient_member_id,notification_type,idempotency_key,scheduled_for)
        VALUES (%s,%s,%s,%s,%s) ON CONFLICT (idempotency_key) DO UPDATE
        SET scheduled_for=EXCLUDED.scheduled_for
        WHERE festive_run_notifications.status IN ('PENDING','BLOCKED_TEMPLATE')""",
        (row["id"], recipient, kind, key, scheduled),
    )


def schedule(now=None):
    if not enabled():
        return {"queued": 0}
    now = now or domain.now()
    count = 0
    with get_cursor() as cur:
        rows = domain.calendar(cur)
        for row in rows:
            if row["status"] in {"OPEN", "CANCELLED", "COMPLETED"}:
                continue
            cur.execute(
                "SELECT draft,approval_status FROM festive_run_details WHERE run_slot_id=%s",
                (row["id"],),
            )
            detail = cur.fetchone() or {}
            details = row.get("published") or detail.get("draft") or {}
            # No invented run start time: missing-time host/admin deadlines are
            # relative to the start of the local run DATE, explicitly documented.
            start = datetime.combine(
                row["run_date"],
                time.fromisoformat(details.get("start_time") or "00:00"),
                domain.TZ,
            )
            if start <= now:
                continue
            if detail.get("approval_status") != "APPROVED":
                cur.execute(
                    "SELECT member_id FROM festive_run_hosts WHERE run_slot_id=%s AND status='ACTIVE' AND reminder_opt_in",
                    (row["id"],),
                )
                for host in cur.fetchall():
                    record(
                        cur,
                        row,
                        host["member_id"],
                        "HOST_72",
                        start - timedelta(hours=72),
                    )
                cur.execute(
                    "SELECT id FROM members WHERE phone=ANY(%s) AND popia_acknowledged AND reminders_opt_in",
                    (list(ADMIN_NUMBERS),),
                )
                for admin in cur.fetchall():
                    record(
                        cur, row, admin["id"], "ADMIN_48", start - timedelta(hours=48)
                    )
            if row["status"] == "PUBLISHED":
                cur.execute(
                    "SELECT member_id FROM festive_run_rsvps WHERE run_slot_id=%s AND status='ACTIVE' AND reminder_opt_in",
                    (row["id"],),
                )
                for rsvp in cur.fetchall():
                    record(
                        cur,
                        row,
                        rsvp["member_id"],
                        "RUN_24",
                        start - timedelta(hours=24),
                    )
        cur.execute(
            "SELECT id,idempotency_key,scheduled_for FROM festive_run_notifications WHERE status IN ('PENDING','BLOCKED_TEMPLATE') AND scheduled_for<=%s",
            (now,),
        )
        for notification in cur.fetchall():
            # Missing templates leave a visible blocked row; no job retry loop.
            if not os.getenv("FESTIVE_NOTIFICATION_TEMPLATE", "").strip():
                cur.execute(
                    "UPDATE festive_run_notifications SET status='BLOCKED_TEMPLATE',error_details='Approved template not configured' WHERE id=%s",
                    (notification["id"],),
                )
                continue
            enqueue_job(
                "festive_notification",
                {"notification_id": notification["id"]},
                dedupe_key=notification["idempotency_key"]
                + ":at:"
                + notification["scheduled_for"].isoformat(),
                cursor=cur,
            )
            count += 1
    return {"queued": count}


def eligible(cur, notification, member, row):
    if (
        not member
        or not member["popia_acknowledged"]
        or member.get("popia_withdrawn_at")
        or not enabled(member["phone"])
    ):
        return False
    kind = notification["notification_type"]
    if row["run_date"] < domain.now().date():
        return False
    if kind == "RUN_24" and row.get("published"):
        start = datetime.combine(
            row["run_date"],
            time.fromisoformat(row["published"]["start_time"]),
            domain.TZ,
        )
        if start <= domain.now():
            return False
    if kind == "ADMIN_48":
        return (
            member["phone"] in ADMIN_NUMBERS
            and member["reminders_opt_in"]
            and row.get("approval_status") != "APPROVED"
            and row["status"] not in {"CANCELLED", "COMPLETED", "OPEN"}
        )
    if kind == "HOST_72":
        cur.execute(
            "SELECT 1 FROM festive_run_hosts WHERE run_slot_id=%s AND member_id=%s AND status='ACTIVE' AND reminder_opt_in",
            (row["id"], member["id"]),
        )
        return (
            bool(cur.fetchone())
            and row.get("approval_status") != "APPROVED"
            and row["status"] not in {"CANCELLED", "COMPLETED"}
        )
    cur.execute(
        "SELECT 1 FROM festive_run_rsvps WHERE run_slot_id=%s AND member_id=%s AND status='ACTIVE' AND reminder_opt_in",
        (row["id"], member["id"]),
    )
    if not cur.fetchone():
        return False
    return row["status"] == ("CANCELLED" if kind == "CANCELLED" else "PUBLISHED")


def deliver(payload):
    if not enabled():
        return
    notification_id = payload["notification_id"]
    # Commit claim BEFORE any network call. Later retries cannot repeat it.
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM festive_run_notifications WHERE id=%s FOR UPDATE",
            (notification_id,),
        )
        n = cur.fetchone()
        if not n or n["status"] not in {"PENDING", "BLOCKED_TEMPLATE"}:
            return
        if n["scheduled_for"] > domain.now():
            return
        cur.execute(
            "SELECT * FROM members WHERE id=%s FOR SHARE", (n["recipient_member_id"],)
        )
        m = cur.fetchone()
        row = next(
            (r for r in domain.calendar(cur) if r["id"] == n["run_slot_id"]), None
        )
        if not row or not eligible(cur, n, m, row):
            cur.execute(
                "UPDATE festive_run_notifications SET status='SUPPRESSED' WHERE id=%s",
                (notification_id,),
            )
            return
        if not os.getenv("FESTIVE_NOTIFICATION_TEMPLATE", "").strip():
            cur.execute(
                "UPDATE festive_run_notifications SET status='BLOCKED_TEMPLATE' WHERE id=%s",
                (notification_id,),
            )
            return
        summary = {
            "HOST_72": "Please finalise your hosting details with MY HOSTS.",
            "ADMIN_48": "This run needs admin review. Send FESTIVE ADMIN.",
            "RUN_24": "Your opted-in run reminder. Send MY RUNS for directions.",
            "CHANGED": "Approved run details have changed. Please review MY RUNS.",
            "CANCELLED": "This run is cancelled. Please do not attend.",
        }[n["notification_type"]]
        if n["notification_type"] in {"RUN_24", "CHANGED"} and row.get("published"):
            d = row["published"]
            summary += f" {d['start_time']} at {d['meeting_point']}. Distances: {', '.join(d['distances'])}."
        body = proactive_template_payload(
            m["phone"], "FESTIVE_NOTIFICATION_TEMPLATE", [str(row["run_date"]), summary]
        )
        body["template"]["components"].append(
            {
                "type": "button",
                "sub_type": "quick_reply",
                "index": "0",
                "parameters": [{"type": "payload", "payload": "festive:calendar:0"}],
            }
        )
        if flag("FESTIVE_UAT_MODE", "true"):
            cur.execute(
                "UPDATE festive_run_notifications SET status='SIMULATED',sent_at=now() WHERE id=%s",
                (notification_id,),
            )
            return
        cur.execute(
            "UPDATE festive_run_notifications SET status='SENDING' WHERE id=%s",
            (notification_id,),
        )
    status, message_id = "UNCERTAIN", None
    try:
        # Recheck consent under a share lock during transmission as existing TT
        # broadcasts do. A withdrawal cannot commit during the send.
        with get_cursor(commit=False) as cur:
            cur.execute("SELECT * FROM members WHERE id=%s FOR SHARE", (m["id"],))
            m = cur.fetchone()
            cur.execute(
                "SELECT * FROM festive_run_slots WHERE id=%s FOR SHARE", (row["id"],)
            )
            locked_row = cur.fetchone()
            locked_row["approval_status"] = row.get("approval_status")
            locked_row["published"] = row.get("published")
            cur.execute(
                "SELECT * FROM festive_run_rsvps WHERE run_slot_id=%s AND member_id=%s FOR SHARE",
                (row["id"], n["recipient_member_id"]),
            )
            if locked_row["revision"] != row["revision"] or not eligible(
                cur, n, m, locked_row
            ):
                status = "SUPPRESSED"
            else:
                response = requests.post(
                    f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages",
                    json=body,
                    headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
                    timeout=(2, 5),
                )
                if response.ok:
                    message_id = response.json().get("messages", [{}])[0].get("id")
                    status = "SENT" if message_id else "UNCERTAIN"
    except (requests.RequestException, ValueError, IndexError):
        pass
    with get_cursor() as cur:
        cur.execute(
            "UPDATE festive_run_notifications SET status=%s,provider_message_id=%s,sent_at=CASE WHEN %s='SENT' THEN now() END,error_details=%s WHERE id=%s",
            (
                status,
                message_id,
                status,
                "Manual delivery reconciliation required"
                if status == "UNCERTAIN"
                else None,
                notification_id,
            ),
        )
