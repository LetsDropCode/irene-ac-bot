from fastapi import APIRouter, Request

from app.whatsapp import (
    send_text,
    send_distance_buttons,
    send_confirm_buttons,
    send_participation_buttons,
)

from app.config import ADMIN_NUMBERS
from app.services.event_code_service import generate_tt_code

from app.services.member_service import (
    get_member,
    create_member,
    save_member_name,
    save_participation_type,
    acknowledge_popia,
    opt_out_leaderboard,
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

ADMIN_NUMBERS = {
    "27722125094", #Lindsay
    "27738870757", #Jacqueline
    "27829370733", #Wynand
    "27818513864", #Johan
    "27828827067", #Janine
}

def is_admin(sender:str)->bool:
    return sender in ADMIN_NUMBERS

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

    # ─────────────────────────────────────────────
    # IGNORE NON-USER EVENTS
    # ─────────────────────────────────────────────
    if not sender or (not text and not button):
        return {"status": "ignored_event"}

    # ─────────────────────────────────────────────
    # 🔐 ADMIN: REQUEST TONIGHT'S TT CODE
    # ─────────────────────────────────────────────
    if text and sender in ADMIN_NUMBERS:
        cmd = text.strip().upper()
        if cmd in {"TT CODE", "GET TT CODE", "CODE"}:
            code = generate_tt_code("TT")
            send_text(
                sender,
                "🔐 *Tonight’s TT Code*\n\n"
                f"*{code}*\n\n"
                "_Valid for today only_"
            )
            return {"status": "admin_tt_code"}

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
    # 🛑 POPIA (LEADERBOARD OPT-OUT ONLY)
    # ─────────────────────────────────────────────
    if text and text.upper() in {"STOP", "OPT OUT"}:
        opt_out_leaderboard(sender)
        send_text(
            sender,
            "✅ You’ve opted out of leaderboards.\n\n"
            "Your attendance will still be recorded for safety and admin."
        )
        return {"status": "leaderboard_opt_out"}

    if not member.get("popia_acknowledged"):
        send_text(
            sender,
            "ℹ️ *POPIA Notice*\n\n"
            "• Attendance is recorded for safety & admin\n"
            "• Results may appear on leaderboards\n\n"
            "Reply *OK* to continue or *STOP* to opt out of leaderboards."
        )
        if text and text.upper() == "OK":
            acknowledge_popia(sender)
        return {"status": "popia_notice"}

    # ─────────────────────────────────────────────
    # 🧾 NAME CAPTURE
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
        save_member_name(member["id"], parts[0], " ".join(parts[1:]))

        msg = coach_reply(
            "Thank the member and ask how they usually participate."
        ) or "Thanks! How do you usually participate?"
        send_text(sender, msg)
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

        msg = coach_reply(
            "Acknowledge their choice and ask for tonight’s TT code."
        ) or "Great! Please send tonight’s TT code."
        send_text(sender, msg)
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
            send_text(sender, "Please send tonight’s TT code.")
            return {"status": "await_code"}

        if not is_valid_tt_code(text):
            send_text(sender, "❌ That TT code is not valid.")
            return {"status": "bad_code"}

        verify_tt_code(submission["id"], text.upper())
        send_distance_buttons(sender)
        return {"status": "code_verified"}

    # ─────────────────────────────────────────────
    # 1️⃣ DISTANCE
    # ─────────────────────────────────────────────
    if button and button.get("id") in {"4km", "6km", "8km"}:
        save_distance(submission["id"], button["id"].replace("km", ""))
        send_text(sender, "⏱ Please send your time.")
        return {"status": "distance_saved"}

    # ─────────────────────────────────────────────
    # 2️⃣ TIME
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
        send_confirm_buttons(sender, submission["distance_text"], text)
        return {"status": "confirm"}

    # ─────────────────────────────────────────────
    # 3️⃣ CONFIRM
    # ─────────────────────────────────────────────
    if button and button.get("id") == "confirm":
        confirm_submission(submission["id"])
        send_text(sender, "🔥 Well done! Your TT has been recorded.")
        return {"status": "complete"}

    # ─────────────────────────────────────────────
    # SILENT FALLBACK (NO LOOPING)
    # ─────────────────────────────────────────────
    return {"status": "noop"}