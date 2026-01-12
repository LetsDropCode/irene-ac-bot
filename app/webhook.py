from fastapi import APIRouter, Request

from app.whatsapp import (
    send_text,
    send_distance_buttons,
    send_confirm_buttons,
)

from app.services.submission_gate import ensure_tt_open
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
from app.services.openai_service import coach_reply
from app.services.time_utils import time_to_seconds

router = APIRouter()


@router.post("/webhook")
async def webhook(request: Request):
    payload = await request.json()

    message = payload.get("message", {})
    sender = message.get("from")
    text = (message.get("text") or "").strip()
    button = message.get("button_reply")

    if not sender:
        return {"status": "ignored"}

    # ─────────────────────────────────────────────
    # 🔒 HARD TT DAY + TIME GATE
    # ─────────────────────────────────────────────
    allowed, reason = ensure_tt_open()
    if not allowed:
        send_text(sender, reason)
        return {"status": "tt_closed"}

    submission = get_or_create_submission(sender)

    # ─────────────────────────────────────────────
    # 0️⃣ TT CODE — MUST COME FIRST
    # ─────────────────────────────────────────────
    if not submission.tt_code_verified:
        if not text or text.lower() in {"hi", "hello"}:
            send_text(
                sender,
                coach_reply(
                    "Welcome the runner and ask them to send the "
                    "Time Trial code to continue."
                ),
            )
            return {"status": "await_code"}

        if not is_valid_tt_code(text):
            send_text(
                sender,
                coach_reply(
                    "Politely say the TT code is invalid and they "
                    "should check with the run leader."
                ),
            )
            return {"status": "bad_code"}

        mark_code_verified(submission, text.upper())
        send_text(
            sender,
            coach_reply(
                "Acknowledge the runner warmly and ask them "
                "to select a distance."
            ),
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
                    "Ask the runner to send their time in "
                    "mm:ss or hh:mm:ss format."
                ),
            )
            return {"status": "ask_time"}

        if btn_id == "confirm":
            confirm_submission(submission)
            send_text(
                sender,
                coach_reply(
                    f"Congratulate the runner for completing "
                    f"{submission.distance} km in {submission.time}."
                ),
            )
            return {"status": "confirmed"}

        if btn_id == "edit":
            if not is_edit_window_open(submission):
                send_text(
                    sender,
                    coach_reply(
                        "Explain politely that editing is closed "
                        "for tonight’s Time Trial."
                    ),
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
        if not is_valid_time(text):
            send_text(
                sender,
                "⏱ Please send *time only*:\n"
                "• 27:41\n"
                "• 01:27:41",
            )
            return {"status": "bad_time"}

        seconds = time_to_seconds(text)
        save_time(submission, text, seconds)
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
            "Let the runner know their Time Trial is already "
            "submitted and they can send Edit if needed."
        ),
    )
    return {"status": "done"}