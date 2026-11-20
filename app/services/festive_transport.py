"""Validated Cloud API payloads, isolated UAT and a final delivery kill switch."""

from app.services.festive_config import capabilities, enabled, flag
from app.services.job_queue_service import enqueue_job


def text_payload(to, body):
    if not body or len(body) > 4096:
        raise ValueError("Text body must contain 1–4096 characters")
    return {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body},
    }


def list_payload(to, body, rows):
    if not 1 <= len(rows) <= 10 or len(body) > 4096:
        raise ValueError("A WhatsApp list supports 1–10 total rows")
    if len({r["id"] for r in rows}) != len(rows):
        raise ValueError("List IDs must be unique")
    for r in rows:
        if (
            not 1 <= len(r["id"]) <= 200
            or not 1 <= len(r["title"]) <= 24
            or len(r.get("description", "")) > 72
        ):
            raise ValueError("Invalid list row")
    return {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": body},
            "action": {
                "button": "Choose",
                "sections": [{"title": "Irene festive runs", "rows": rows}],
            },
        },
    }


def buttons_payload(to, body, choices):
    if not 1 <= len(choices) <= 3 or len(body) > 1024:
        raise ValueError("Reply buttons support 1–3 choices and a 1024 character body")
    if any(not 1 <= len(k) <= 256 or not 1 <= len(v) <= 20 for k, v in choices):
        raise ValueError("Invalid reply button")
    return {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": k, "title": v}}
                    for k, v in choices
                ]
            },
        },
    }


def flow_payload(to, kind, token):
    caps = capabilities()
    flow_id = caps["flow_ids"].get(kind)
    if not caps["flows"] or not flow_id:
        raise ValueError("A published festive Flow and endpoint readiness are required")
    return {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "flow",
            "body": {
                "text": "🎄 Irene AC Festive Run Adventures\nDifferent hosts. Different routes. One Irene family. 💚\nOpen your form. If it won't open, send FESTIVE SIMPLE or FESTIVE TEXT. CANCEL stops this session."
            },
            "action": {
                "name": "flow",
                "parameters": {
                    "flow_message_version": "3",
                    "flow_id": flow_id,
                    "flow_token": token,
                    "flow_cta": "Open festive form",
                    "flow_action": "data_exchange",
                    "mode": "published",
                },
            },
        },
    }


def location_payload(to, details):
    return {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "location",
        "location": {
            "latitude": details["latitude"],
            "longitude": details["longitude"],
            "name": details["meeting_point"],
            "address": details["location_description"],
        },
    }


def send(payload, key=None):
    if not enabled(payload["to"]):
        return False
    # Keep festive jobs separate: disabling the feature also stops already-queued replies.
    from app.whatsapp import _inbound_delivery

    state = _inbound_delivery.get()
    if state and state["message_id"]:
        key = f"festive:reply:{state['message_id']}:{state['sequence']}"
        state["sequence"] += 1
    job = enqueue_job("festive_reply", {"payload": payload}, dedupe_key=key)
    if state:
        state["job_ids"].append(job)
    return True


def deliver_reply(payload):
    message = payload["payload"]
    if not enabled(message["to"]) or flag("FESTIVE_UAT_MODE", "true"):
        return
    from app.whatsapp import _send_direct

    if not _send_direct(message):
        raise RuntimeError("Festive reply delivery failed")
