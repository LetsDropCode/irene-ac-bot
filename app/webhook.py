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
# SAFE AI SEND (NO EMPTY / NO GHOST MESSAGES)
# ─────────────────────────────────────────────
def send_ai(sender: str, prompt: str) -> None:
    try:
        reply = coach_reply(prompt)
        if reply and reply.strip():
            send_text(sender, reply)
    except Exception:
        # Never allow AI to break the webhook
        pass


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


# ─────────────────────────────────────────────
# MAIN WEBHOOK
# ─────────────────────────────────────────────
@router.post("/webhook")
async def webhook(request: Request):
    payload = await request.json()
    sender, text, button = extract_whatsapp_message(payload)

    # ─────────────────────────────────────────────
    # IGNORE NON-USER EVENTS (Meta retries, receipts)
    # ─────────────────────────────────────────────
    if not sender or (not text and not button):
        return {"status": "ignored_event"}

    # ─────────────────────────────────────────────
    # GLOBAL TT GATE
    # ─────────────────────────────────────────────
    allowed, reason = ensure_tt_open()
    if not allowed:
        send_text(sender, reason)
        return {"status": "tt_closed"}

    # ─────────────────────────────────────────────
    # MEMBER LOOKUP / CREATE
    # ─────────────────────────────────────────────
    member = get_member(sender)
    if not member:
        member = create_member(sender)

# ─────────────────────────────────────────────
# FRIENDLY GREETING (SAFE, NON-DESTRUCTIVE)
# ─────────────────────────────────────────────
    if text and text.lower() in {"hi", "hello", "hey"}:
        send_text(
            sender,
            "👋 Hi! If you're submitting a Time Trial, please send tonight’s *TT code*.\n\n"
            "If you’re all done, you’re good to go 👍"
        )
        return {"status": "greeted"}

    # ─────────────────────────────────────────────
    # NAME CAPTURE (ONCE)
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

        send_ai(
            sender,
            "Thank the member and ask how they usually participate."
        )
        send_participation_buttons(sender)
        return {"status": "name_saved"}

    # ─────────────────────────────────────────────
    # PARTICIPATION TYPE (RUNNER / WALKER / BOTH)
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

        send_ai(
            sender,
            "Great! Please send tonight’s TT code."
        )
        return {"status": "participation_saved"}

    # ─────────────────────────────────────────────
    # DAILY SUBMISSION
    # ─────────────────────────────────────────────
    submission = get_or_create_submission(member["id"])

    # ─────────────────────────────────────────────
    # TT CODE
    # ─────────────────────────────────────────────
    if not submission["tt_code_verified"]:
        if not text:
            send_ai(sender, "Please send tonight’s TT code.")
            return {"status": "await_code"}

        if not is_valid_tt_code(text):
            send_ai(sender, "That TT code is not valid.")
            return {"status": "bad_code"}

        verify_tt_code(submission["id"], text.upper())
        send_distance_buttons(sender)
        return {"status": "code_verified"}

    # ─────────────────────────────────────────────
    # DISTANCE
    # ─────────────────────────────────────────────
    if button and button.get("id") in {"4km", "6km", "8km"}:
        save_distance(
            submission["id"],
            button["id"].replace("km", "")
        )
        send_ai(sender, "Please send your time.")
        return {"status": "distance_saved"}

    # ─────────────────────────────────────────────
    # TIME
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

        parts = list(map(int, text.split(":")))
        seconds = parts[-1] + parts[-2] * 60
        if len(parts) == 3:
            seconds += parts[0] * 3600

        save_time(submission["id"], text, seconds)
        send_confirm_buttons(
            sender,
            submission["distance_text"],
            text
        )
        return {"status": "confirm"}

    # ─────────────────────────────────────────────
    # CONFIRM
    # ─────────────────────────────────────────────
    if button and button.get("id") == "confirm":
        confirm_submission(submission["id"])
        send_ai(
            sender,
            "🔥 Well done! Your TT has been recorded."
        )
        return {"status": "complete"}

    # ─────────────────────────────────────────────
    # SILENT FALLBACK (NO SPAM)
    # ─────────────────────────────────────────────
    return {"status": "noop"}