# app/webhook.py

from fastapi import APIRouter, Request

from app.whatsapp import (
    send_text,
    send_distance_buttons,
    send_confirm_buttons,
)

from app.services.member_service import (
    get_member,
    create_member,
    save_member_name,
    has_name,
)

from app.services.submission_service import (
    get_or_create_submission,
    save_distance,
    save_time,
    confirm_submission,
    is_edit_window_open,
    mark_code_verified,
)

from app.services.validation import (
    is_valid_time,
    is_valid_tt_code,
)

from app.services.submission_gate import ensure_tt_open
from app.services.openai_service import coach_reply

router = APIRouter()


def extract_whatsapp_message(payload: dict):
    try:
        entry = payload["entry"][0]
        change = entry["changes"][0]
        value = change["value"]

        messages = value.get("messages")
        if not messages:
            return None, None, None

        msg = messages[0]
        sender = msg["from"]

        text = None
        button = None

        if msg["type"] == "text":
            text = msg["text"]["body"].strip()

        if msg["type"] == "interactive":
            button = msg["interactive"]["button_reply"]

        return sender, text, button

    except Exception:
        return None, None, None


@router.post("/webhook")
async def webhook(request: Request):
    payload = await request.json()
    sender, text, button = extract_whatsapp_message(payload)

    if not sender:
        return {"status": "ignored"}

    # ─────────────────────────────────────────────
    # 🔒 TT DAY + TIME GATE
    # ─────────────────────────────────────────────
    allowed, reason = ensure_tt_open()
    if not allowed:
        send_text(sender, reason)
        return {"status": "tt_closed"}

    # ─────────────────────────────────────────────
    # 👤 MEMBER LOOKUP / CREATE
    # ─────────────────────────────────────────────
    member = get_member(sender)
    if not member:
        member = create_member(sender)

    # ─────────────────────────────────────────────
    # 🧾 NAME CAPTURE (ONCE ONLY)
    # ─────────────────────────────────────────────
    if not has_name(member):

        if not text or len(text.split()) < 2:
            send_text(
                sender,
                "👋 Before we continue, please send your *first name and surname*.\n\n"
                "_Example: Sipho Dlamini_"
            )
            return {"status": "await_name"}

        parts = text.split()
        first_name = parts[0]
        last_name = " ".join(parts[1:])

        save_member_name(sender, first_name, last_name)

        send_text(
            sender,
            coach_reply(
                "Thank the runner for confirming their name and ask them "
                "to send the TT code to continue."
            )
        )
        return {"status": "name_saved"}

    # ─────────────────────────────────────────────
    # 📋 SUBMISSION SESSION
    # ─────────────────────────────────────────────
    submission = get_or_create_submission(sender)

    # ─────────────────────────────────────────────
    # 0️⃣ TT CODE — MUST COME FIRST
    # ─────────────────────────────────────────────
    if not submission.tt_code_verified:

        if not text:
            send_text(
                sender,
                coach_reply(
                    "Welcome the runner and ask them to send tonight’s TT code."
                )
            )
            return {"status": "await_code"}

        if not is_valid_tt_code(text):
            send_text(
                sender,
                coach_reply(
                    "Politely explain that the TT code is invalid "
                    "and they should check with the run leader."
                )
            )
            return {"status": "bad_code"}

        mark_code_verified(submission, text.upper())

        send_text(
            sender,
            coach_reply(
                "Acknowledge the runner warmly and ask them to select a distance."
            )
        )
        send_distance_buttons(sender)
        return {"status": "code_verified"}

    # ─────────────────────────────────────────────
    # 1️⃣ BUTTON HANDLING
    # ─────────────────────────────────────────────
    if button:
        btn_id = button.get("id")

        if btn_id in {"4km", "6km", "8km"}:
            save_distance(submission, btn_id.replace("km", ""))
            send_text(
                sender,
                coach_reply(
                    "Ask the runner to send their time in mm:ss or hh:mm:ss."
                )
            )
            return {"status": "ask_time"}

        if btn_id == "confirm":
            confirm_submission(submission)
            send_text(
                sender,
                coach_reply(
                    f"Congratulate the runner for completing "
                    f"{submission.distance} in {submission.time}."
                )
            )
            return {"status": "confirmed"}

        if btn_id == "edit":
            if not is_edit_window_open(submission):
                send_text(
                    sender,
                    coach_reply(
                        "Explain politely that editing is closed for tonight."
                    )
                )
                return {"status": "edit_closed"}

            send_distance_buttons(sender)
            return {"status": "edit"}

    # ─────────────────────────────────────────────
    # 2️⃣ DISTANCE HARD GATE
    # ─────────────────────────────────────────────
    if not submission.distance:
        send_distance_buttons(sender)
        return {"status": "need_distance"}

    # ─────────────────────────────────────────────
    # 3️⃣ TIME CAPTURE
    # ─────────────────────────────────────────────
    if not submission.time:
        if not text or not is_valid_time(text):
            send_text(
                sender,
                "⏱ Please send *time only*:\n"
                "• 27:41\n"
                "• 01:27:41"
            )
            return {"status": "bad_time"}

        save_time(submission, text)
        send_confirm_buttons(
            sender,
            submission.distance,
            submission.time,
        )
        return {"status": "confirm"}

    # ─────────────────────────────────────────────
    # 4️⃣ FALLBACK
    # ─────────────────────────────────────────────
    send_text(
        sender,
        coach_reply(
            "Let the runner know their time trial is already submitted "
            "and they can send Edit if needed."
        )
    )
    return {"status": "done"}