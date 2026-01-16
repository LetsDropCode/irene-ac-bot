from fastapi import APIRouter, Request

from app.whatsapp import (
    send_text,
    send_distance_buttons,
    send_confirm_buttons,
    send_participation_buttons,
)

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
    "27722135094",  # Lindsay
    "27738870757",  # Jacqueline
    "27829370733",  # Wynand
    "27818513864",  # Johan
    "27828827067",  # Janine
}


def is_admin(sender: str) -> bool:
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
    # 0) IGNORE NON-USER EVENTS
    # ─────────────────────────────────────────────
    if not sender or (not text and not button):
        return {"status": "ignored_event"}

    # ─────────────────────────────────────────────
    # 1) ADMIN: REQUEST TONIGHT'S TT CODE (HARD EXIT)
    # ─────────────────────────────────────────────
    if text and is_admin(sender):
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
    # 2) GLOBAL TT GATE
    # ─────────────────────────────────────────────
    allowed, reason = ensure_tt_open()
    if not allowed:
        send_text(sender, reason)
        return {"status": "tt_closed"}

    # ─────────────────────────────────────────────
    # 3) MEMBER LOOKUP / CREATE
    # ─────────────────────────────────────────────
    member = get_member(sender)
    if not member:
        member = create_member(sender)

    # ─────────────────────────────────────────────
    # 4) POPIA / OPT OUT (HIGHEST PRIORITY USER COMMAND)
    # ─────────────────────────────────────────────
    if text and text.strip().upper() in {"STOP", "OPT OUT"}:
        opt_out_leaderboard(sender)
        send_text(
            sender,
            "✅ You’ve opted out of leaderboards.\n\n"
            "Your attendance will still be recorded for safety and admin."
        )
        return {"status": "leaderboard_opt_out"}

    # ─────────────────────────────────────────────
    # 5) POPIA ACKNOWLEDGEMENT (PRIVACY-FIRST)
    # ─────────────────────────────────────────────
    if not member.get("popia_acknowledged"):

        # If they replied OK → store it then continue
        if text and text.strip().upper() == "OK":
            acknowledge_popia(sender)
            send_text(
                sender,
                "✅ Thanks!\n\n"
                "👋 Please send your *first name and surname*.\n"
                "_Example: Sipho Dlamini_"
            )
            return {"status": "popia_acknowledged"}

        # Otherwise show POPIA notice and stop
        send_text(
            sender,
            "ℹ️ *POPIA Notice*\n\n"
            "• Attendance is recorded for safety & admin\n"
            "• Results may appear on leaderboards\n\n"
            "Reply *OK* to continue or *STOP* to opt out of leaderboards."
        )
        return {"status": "popia_notice"}

    # ─────────────────────────────────────────────
    # 6) NAME CAPTURE / RECOVERY FLOW (ONE CLEAN BLOCK)
    # ─────────────────────────────────────────────
    if not member.get("first_name") or not member.get("last_name"):

        if not text:
            send_text(
                sender,
                "👋 Welcome!\n\n"
                "Please send your *first name and surname*.\n"
                "_Example: Sipho Dlamini_"
            )
            return {"status": "await_name"}

        if len(text.split()) < 2:
            send_text(
                sender,
                "🙂 Almost there!\n\n"
                "Please send your *first name and surname*.\n"
                "_Example: Sipho Dlamini_"
            )
            return {"status": "await_name"}

        parts = text.split()
        first_name = parts[0]
        last_name = " ".join(parts[1:])

        save_member_name(member["id"], first_name, last_name)

        msg = coach_reply(
            "Thank the member and ask how they usually participate."
        ) or "✅ Thanks! How do you usually participate?"
        send_text(sender, msg)

        send_participation_buttons(sender)
        return {"status": "name_saved"}

    # ─────────────────────────────────────────────
    # 7) PARTICIPATION TYPE
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
        ) or "✅ Great! Please send *tonight’s TT code only*.\nExample: *7460*"
        send_text(sender, msg)
        return {"status": "participation_saved"}

    # ─────────────────────────────────────────────
    # 8) DAILY SUBMISSION
    # ─────────────────────────────────────────────
    submission = get_or_create_submission(member["id"])

    # ─────────────────────────────────────────────
    # 8.1) TT CODE
    # ─────────────────────────────────────────────
    if not submission["tt_code_verified"]:

        if not text:
            send_text(
                sender,
                "🔑 Please send *tonight’s TT code only*.\n"
                "Example: *7460*"
            )
            return {"status": "await_code"}

        if not is_valid_tt_code(text):
            send_text(sender, "❌ That TT code is not valid.")
            return {"status": "bad_code"}

        verify_tt_code(submission["id"], text.upper())
        send_distance_buttons(sender)
        return {"status": "code_verified"}

    # ─────────────────────────────────────────────
    # 8.2) DISTANCE (BUTTON)
    # ─────────────────────────────────────────────
    if button and button.get("id") in {"4km", "6km", "8km"}:
        save_distance(submission["id"], button["id"].replace("km", ""))
        send_text(sender, "⏱ Please send your time.")
        return {"status": "distance_saved"}

    # ─────────────────────────────────────────────
    # 8.3) TIME (TEXT)
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
    # 8.4) CONFIRM OR EDIT
    # ─────────────────────────────────────────────
    if button and button.get("id") == "confirm":
        confirm_submission(submission["id"])
        send_text(sender, "🔥 Well done! Your TT has been recorded.")
        return {"status": "complete"}

    if button and button.get("id") == "edit":
        # Simple edit behaviour: re-ask distance.
        # (Optional improvement: clear previous time/distance in DB here.)
        send_text(sender, "✏️ No stress — let’s update it.\nSelect your TT distance again:")
        send_distance_buttons(sender)
        return {"status": "edit_restart"}

    # ─────────────────────────────────────────────
    # 9) SILENT FALLBACK
    # ─────────────────────────────────────────────
    return {"status": "noop"}