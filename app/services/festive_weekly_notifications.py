"""Opt-in captain notices. Templates only; ambiguous sends never auto-repeat."""

import os

import requests

from app.config import PHONE_NUMBER_ID, WHATSAPP_TOKEN
from app.db import get_cursor
from app.services import festive_service as domain
from app.services import festive_weekly_service as weekly
from app.services.festive_config import flag
from app.services.job_queue_service import enqueue_job
from app.services.proactive_template_service import proactive_template_payload


def template_ready():
    return bool(os.getenv("FESTIVE_WEEKLY_NOTIFICATION_TEMPLATE", "").strip()) and flag(
        "FESTIVE_WEEKLY_TEMPLATE_APPROVED"
    )


def subscribe(actor, opt_in):
    with get_cursor() as cur:
        domain.member(cur, actor, admin=True)
        cur.execute(
            """INSERT INTO festive_weekly_subscriptions(member_id,opt_in) VALUES (%s,%s)
            ON CONFLICT(member_id) DO UPDATE SET opt_in=EXCLUDED.opt_in,updated_at=now()""",
            (actor, opt_in),
        )


def queue_notices(cur, edition):
    if (
        not flag("FESTIVE_WEEKLY_ADMIN_NOTIFICATION_ENABLED")
        or edition["status"] == "POSTED"
    ):
        return
    cur.execute(
        """SELECT m.id FROM members m JOIN festive_weekly_subscriptions s ON s.member_id=m.id
        WHERE s.opt_in AND m.phone=ANY(%s) AND m.popia_acknowledged AND m.popia_withdrawn_at IS NULL""",
        (list(domain.ADMIN_NUMBERS),),
    )
    for member in cur.fetchall():
        cur.execute(
            """INSERT INTO festive_weekly_notices(edition_id,recipient_member_id)
            VALUES (%s,%s) ON CONFLICT DO NOTHING""",
            (edition["id"], member["id"]),
        )
    cur.execute(
        "SELECT * FROM festive_weekly_notices WHERE edition_id=%s AND status IN ('PENDING','BLOCKED_TEMPLATE')",
        (edition["id"],),
    )
    for notice in cur.fetchall():
        if not template_ready():
            cur.execute(
                "UPDATE festive_weekly_notices SET status='BLOCKED_TEMPLATE',last_error='Approved weekly template is not configured' WHERE id=%s",
                (notice["id"],),
            )
            continue
        enqueue_job(
            "festive_weekly_notice",
            {"notice_id": notice["id"]},
            dedupe_key=f"festive:weekly:notice:{notice['id']}",
            cursor=cur,
        )


def _eligible(cur, notice):
    cur.execute(
        """SELECT m.*,s.opt_in FROM members m JOIN festive_weekly_subscriptions s ON s.member_id=m.id
        WHERE m.id=%s FOR SHARE OF m,s""",
        (notice["recipient_member_id"],),
    )
    member = cur.fetchone()
    cur.execute(
        "SELECT * FROM festive_weekly_editions WHERE id=%s FOR SHARE",
        (notice["edition_id"],),
    )
    edition = cur.fetchone()
    today = weekly.local_now().date()
    if (
        not member
        or not member["opt_in"]
        or not member["popia_acknowledged"]
        or member.get("popia_withdrawn_at")
        or member["phone"] not in domain.ADMIN_NUMBERS
        or not weekly.active(member["phone"])
        or not edition
        or edition["status"] != "READY_FOR_REVIEW"
        or not edition["week_start"] <= today <= edition["week_end"]
    ):
        return None, None
    return member, edition


def deliver(payload):
    if not weekly.active() or not flag("FESTIVE_WEEKLY_ADMIN_NOTIFICATION_ENABLED"):
        return
    # Persist claim before network I/O. A crash here leaves SENDING, requiring
    # reconciliation rather than a duplicate proactive notification.
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM festive_weekly_notices WHERE id=%s FOR UPDATE",
            (payload["notice_id"],),
        )
        notice = cur.fetchone()
        if not notice or notice["status"] not in {"PENDING", "BLOCKED_TEMPLATE"}:
            return
        member, edition = _eligible(cur, notice)
        if not member:
            cur.execute(
                "UPDATE festive_weekly_notices SET status='SUPPRESSED' WHERE id=%s",
                (notice["id"],),
            )
            return
        if not template_ready():
            cur.execute(
                "UPDATE festive_weekly_notices SET status='BLOCKED_TEMPLATE',last_error='Approved weekly template is not configured' WHERE id=%s",
                (notice["id"],),
            )
            return
        if flag("FESTIVE_UAT_MODE", "true"):
            cur.execute(
                "UPDATE festive_weekly_notices SET status='SIMULATED' WHERE id=%s",
                (notice["id"],),
            )
            return
        cur.execute(
            "UPDATE festive_weekly_notices SET status='SENDING',attempted_at=now(),last_error=NULL WHERE id=%s",
            (notice["id"],),
        )
    status, message_id, error = (
        "UNCERTAIN",
        None,
        "Manual provider reconciliation required; do not resend automatically",
    )
    try:
        with get_cursor(commit=False) as cur:
            member, edition = _eligible(cur, notice)
            if (
                not member
                or not template_ready()
                or not flag("FESTIVE_WEEKLY_ADMIN_NOTIFICATION_ENABLED")
            ):
                status, error = "SUPPRESSED", None
            else:
                body = proactive_template_payload(
                    member["phone"],
                    "FESTIVE_WEEKLY_NOTIFICATION_TEMPLATE",
                    [str(edition["week_start"]), str(edition["revision"])],
                )
                response = requests.post(
                    f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages",
                    json=body,
                    headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
                    timeout=(2, 5),
                )
                if response.ok:
                    message_id = response.json().get("messages", [{}])[0].get("id")
                    if message_id:
                        status, error = "ACCEPTED", None
                elif response.status_code < 500:
                    status, error = (
                        "FAILED",
                        f"Provider rejected request (HTTP {response.status_code}); review template and account configuration",
                    )
    except (
        requests.RequestException,
        ValueError,
        IndexError,
        TypeError,
        AttributeError,
    ):
        pass
    with get_cursor() as cur:
        cur.execute(
            "UPDATE festive_weekly_notices SET status=%s,provider_message_id=%s,last_error=%s WHERE id=%s",
            (status, message_id, error, notice["id"]),
        )
