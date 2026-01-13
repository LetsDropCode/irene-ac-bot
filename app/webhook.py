from fastapi import APIRouter, Request

from app.whatsapp import (
    send_text,
    send_distance_buttons,
    send_confirm_buttons,
    send_participation_buttons,
)

from app.services.member_service import (
    get_member,
    create_member,
    save_member_name,
    save_participation_type,
)

from app.services.submission_service import (
    get_or_create_submission,
    verify_tt_code,
    save_distance,
    save_time,
    confirm_submission,
)

from app.services.validation import (
    is_valid_time,
    is_valid_tt_code,
)

from app.services.submission_gate import ensure_tt_open
from app.services.openai_service import coach_reply

router = APIRouter()


# ─────────────────────────────────────────────
# WhatsApp payload extractor (SAFE)
# ─────────────────────────────────────────────
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

    except (KeyError, IndexError, TypeError):
        return None, None, None


@router.post("/webhook")
async def webhook(request: Request):
    payload = await request.json()
    sender, text, button = extract_whatsapp_message(payload)

    if not sender:
        return {"status": "ignored"}

    # ─────────────────────────────────────────────
    # 🔒 GLOBAL TT GATE
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
    # 🧾 NAME CAPTURE (ONCE)
    # ─────────────────────────────────────────────
    if not member.get("first_name") or not member.get("last_name"):
        if not text or len(text.split()) < 2:
            send_text(
                sender,
                "👋 Welcome!\n\n"
                "Please send your *first name and surname*.\n"
                "_Example: Sipho Dlamini_"
            )
            return {"status": "await_name"}

        parts = text.split()
        save_member_name(
            member["id"],
            parts[0],
            " ".join(parts[1:])
        )

        send_text(
            sender,
            coach_reply(
                "Thank the member and ask how they usually participate."
            )
        )
        send_participation_buttons(sender)
        return {"status": "name_saved"}

    # ─────────────────────────────────────────────
    # 🏃 PARTICIPATION TYPE (BACKFILL SAFE)
    # ─────────────────────────────────────────────
    if not member.get("participation_type"):
        if not button:
            send_participation_buttons(sender)
            return {"status": "await_participation"}

        ptype = button.get("id")
        if ptype not in {"RUNNER", "WALKER", "BOTH"}:
            send_participation_buttons(sender)
            return {"status": "bad_participation"}

        save_participation_type(member["id"], ptype)

        send_text(
            sender,
            coach_reply(
                "Acknowledge their choice and ask for tonight’s TT code."
            )
        )
        return {"status": "participation_saved"}

    # ─────────────────────────────────────────────
    # 📋 DAILY SUBMISSION
    # ─────────────────────────────────────────────
    submission = get_or_create_submission(member["id"])

    # ─────────────────────────────────────────────
    # 0️⃣ TT CODE
    # ─────────────────────────────────────────────
    if not submission["tt_code_verified"]:
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
                    "Politely explain that the TT code is invalid."
                )
            )
            return {"status": "bad_code"}

        verify_tt_code(submission["id"], text.upper())

        send_text(
            sender,
            coach_reply(
                "Code verified — ask them to select a distance."
            )
        )
        send_distance_buttons(sender)
        return {"status": "code_verified"}

    # ─────────────────────────────────────────────
    # 1️⃣ DISTANCE BUTTONS
    # ─────────────────────────────────────────────
    if button and button.get("id") in {"4km", "6km", "8km"}:
        save_distance(submission["id"], button["id"].replace("km", ""))
        send_text(
            sender,
            coach_reply(
                "Ask the runner to send their time."
            )
        )
        return {"status": "distance_saved"}

    # ─────────────────────────────────────────────
    # 2️⃣ TIME CAPTURE
    # ─────────────────────────────────────────────
    if submission["distance_text"] and not submission["time_text"]:
        if not text or not is_valid_time(text):
            send_text(
                sender,
                "⏱ Please send time only:\n"
                "• 27:41\n"
                "• 01:27:41"
            )
            return {"status": "bad_time"}

        # Convert to seconds safely
        parts = list(map(int, text.split(":")))
        seconds = parts[-1] + parts[-2] * 60
        if len(parts) == 3:
            seconds += parts[0] * 3600

        save_time(submission["id"], text, seconds)

        send_confirm_buttons(
            sender,
            submission["distance_text"],
            text,
        )
        return {"status": "confirm"}

    # ─────────────────────────────────────────────
    # 3️⃣ CONFIRM / COMPLETE
    # ─────────────────────────────────────────────
    if button and button.get("id") == "confirm":
        confirm_submission(submission["id"])
        send_text(
            sender,
            coach_reply(
                "Congratulate the runner for completing their TT."
            )
        )
        return {"status": "complete"}

    # ─────────────────────────────────────────────
    # FALLBACK
    # ─────────────────────────────────────────────
    send_text(
        sender,
        coach_reply(
            "Let them know their TT is already submitted."
        )
    )
    return {"status": "done"}