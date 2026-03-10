
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
    "27722135094",
    "27738870757",
    "27829370733",
    "27818513864",
    "27828827067",
}


def is_admin(sender: str) -> bool:
    return sender in ADMIN_NUMBERS


# ─────────────────────────────────────────────
# SAFE PAYLOAD EXTRACTOR
# ─────────────────────────────────────────────
def extract_whatsapp_message(payload: dict):
    try:
        entry = payload.get("entry", [{}])[0]
        change = entry.get("changes", [{}])[0]
        value = change.get("value", {})

        messages = value.get("messages")
        if not messages:
            return None, None, None

        msg = messages[0]
        sender = msg.get("from")

        text = None
        button = None

        if msg.get("type") == "text":
            text = msg.get("text", {}).get("body", "").strip()

        elif msg.get("type") == "interactive":
            button = msg.get("interactive", {}).get("button_reply")

        print("📲 Incoming:", sender, "|", text, "|", button)
        return sender, text, button

    except Exception as e:
        print("❌ extractor error:", str(e))
        return None, None, None


@router.post("/webhook")
async def webhook(request: Request):
    payload = await request.json()
    sender, text, button = extract_whatsapp_message(payload)

    if not sender or (not text and not button):
        return {"status": "ignored"}

    # ─────────────────────────────────────────
    # ADMIN COMMANDS
    # ─────────────────────────────────────────
    if text and is_admin(sender):
        cmd = text.upper().strip()
        if cmd in {"TT CODE", "GET TT CODE", "CODE"}:
            code = generate_tt_code("TT")
            send_text(sender, f"🔐 Tonight’s TT Code:\n\n*{code}*")
            return {"status": "admin_code"}

    # ─────────────────────────────────────────
    # MEMBER LOOKUP / CREATE
    # ─────────────────────────────────────────
    member = get_member(sender)
    if not member:
        member = create_member(sender)

    # ─────────────────────────────────────────
    # POPIA OPT OUT
    # ─────────────────────────────────────────
    if text and text.upper() in {"STOP", "OPT OUT"}:
        opt_out_leaderboard(sender)
        send_text(sender, "✅ You’ve opted out of leaderboards.")
        return {"status": "opt_out"}

    # ─────────────────────────────────────────
    # POPIA ACKNOWLEDGEMENT
    # ─────────────────────────────────────────
    if not member.get("popia_acknowledged"):

        if text and text.upper() == "OK":
            acknowledge_popia(sender)
            send_text(sender, "✅ Thanks! Please send your *first and last name*.")
            return {"status": "popia_ack"}

        send_text(
            sender,
            "ℹ️ POPIA Notice\n\nReply OK to continue or STOP to opt out."
        )
        return {"status": "popia_notice"}

    # ─────────────────────────────────────────
    # PROFILE COMPLETION (CAMPAIGN + NORMAL)
    # Works ANY day (before TT gate)
    # ─────────────────────────────────────────
    if (
        not member.get("first_name")
        or not member.get("last_name")
        or member.get("first_name") == "Unknown"
        or member.get("last_name") == "Unknown"
    ):

        if not text:
            send_text(sender, "👋 Please reply with your *first and last name*.")
            return {"status": "await_name"}

        if len(text.split()) < 2:
            send_text(sender, "🙂 Please send both first and last name.")
            return {"status": "await_name_retry"}

        parts = text.split()
        first_name = parts[0]
        last_name = " ".join(parts[1:])

        save_member_name(member["id"], first_name, last_name)

        send_text(sender, "✅ Thank you! Your profile has been updated.")

        msg = coach_reply(
            "Thank them warmly and ask how they usually participate."
        ) or "How do you usually participate?"
        send_text(sender, msg)

        send_participation_buttons(sender)
        return {"status": "profile_completed"}

    # ─────────────────────────────────────────
    # TT GATE (after profile completion)
    # ─────────────────────────────────────────
    allowed, reason = ensure_tt_open()
    if not allowed:
        send_text(sender, reason)
        return {"status": "tt_closed"}

    # ─────────────────────────────────────────
    # PARTICIPATION TYPE
    # ─────────────────────────────────────────
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
            "Acknowledge their choice and ask for TT code."
        ) or "Great! Please send tonight’s TT code."
        send_text(sender, msg)
        return {"status": "ptype_saved"}

    # ─────────────────────────────────────────
    # SUBMISSION FLOW
    # ─────────────────────────────────────────
    submission = get_or_create_submission(member["id"])

    if not submission["tt_code_verified"]:

        if not text:
            send_text(sender, "🔑 Please send tonight’s TT code.")
            return {"status": "await_code"}

        if not is_valid_tt_code(text):
            send_text(sender, "❌ Invalid TT code.")
            return {"status": "bad_code"}

        verify_tt_code(submission["id"], text.upper())

    # WALKERS log workouts instead of distances
        if member["participation_type"] == "WALKER":
            send_text(sender, "🚶 Tell us about your workout today!")
            return {"status": "await_walk"}

    # RUNNERS continue normally
        send_distance_buttons(sender)
        return {"status": "code_verified"}
    
    # WALKER WORKOUT INPUT
    if member["participation_type"] == "WALKER" and submission["tt_code_verified"] and text:

        if not submission["time_text"]:
            save_time(submission["id"], text, 0)
            confirm_submission(submission["id"])

            send_text(sender, "🚶 Workout logged! Well done.")
            return {"status": "walker_logged"}    

    if member["participation_type"] != "WALKER" and button and button.get("id") in {"4km", "6km", "8km"}:
        save_distance(submission["id"], button["id"].replace("km", ""))
        send_text(sender, "⏱ Please send your time.")
        return {"status": "distance_saved"}

    if submission["distance_text"] and not submission["time_text"]:

        if not text or not is_valid_time(text):
            send_text(sender, "⏱ Send time like 27:41 or 01:27:41")
            return {"status": "bad_time"}

        parts = list(map(int, text.split(":")))
        seconds = parts[-1] + parts[-2] * 60
        if len(parts) == 3:
            seconds += parts[0] * 3600

        save_time(submission["id"], text, seconds)
        send_confirm_buttons(sender, submission["distance_text"], text)
        return {"status": "confirm"}

    if button and button.get("id") == "confirm":
        confirm_submission(submission["id"])
        send_text(sender, "🔥 Well done! Your TT has been recorded.")
        return {"status": "complete"}

    if button and button.get("id") == "edit":
        send_text(sender, "✏️ Let’s update it — choose distance again.")
        send_distance_buttons(sender)
        return {"status": "edit_restart"}

    return {"status": "noop"}