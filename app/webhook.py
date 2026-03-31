from email.mime import text

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
    release_pending_submissions,
)

from app.services.attendance_service import mark_attendance
from app.services.validation import is_valid_time, is_valid_tt_code
from app.services.submission_gate import ensure_tt_open
from app.services.pb_service import is_personal_best
from app.services.leaderboard_service import get_tonight_leaderboard
from app.services.leaderboard_formatter import format_leaderboard
from app.services.tt_status_service import get_tt_status

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

    if text:
        text = text.strip().upper()

    # ─────────────────────────────────────
    # GLOBAL ADMIN COMMANDS (OVERRIDE ALL)
    # ─────────────────────────────────────
    if text and is_admin(sender):

        if text in {"TT CODE", "GET TT CODE", "CODE"}:
            code = generate_tt_code("TT")
            send_text(sender, f"🔐 Tonight’s TT Code\n\n*{code}*")
            return {"status": "admin_code"}

        if text == "LEADERBOARD":
            rows = get_tonight_leaderboard()
            send_text(sender, format_leaderboard(rows))
            return {"status": "leaderboard"}

        if text == "TT STATUS":
            send_text(sender, get_tt_status())
            return {"status": "status"}
    # ───────── MEMBER ─────────
    member = get_member(sender)
    if not member:
        member = create_member(sender)

    # ───────── OPT OUT ─────────
    if text in {"STOP", "OPT OUT"}:
        opt_out_leaderboard(sender)
        send_text(sender, "✅ You’ve opted out.")
        return {"status": "opt_out"}

    # ───────── POPIA ─────────
    if not member.get("popia_acknowledged"):

        if text == "OK":
            acknowledge_popia(sender)
            send_text(sender, "✅ Send your *first and last name*.")
            return {"status": "popia_ack"}

        send_text(sender, "ℹ️ Reply OK to continue or STOP to opt out.")
        return {"status": "popia"}

    # ───────── PROFILE ─────────
    if text == "PROFILE":
        from app.services.profile_service import get_user_profile
        from app.services.profile_formatter import format_profile

        data = get_user_profile(member["id"])
        send_text(sender, format_profile(member, data))
        return {"status": "profile"}
    
    if (
        not member.get("first_name")
        or not member.get("last_name")
        or member["first_name"] == "Unknown"
    ):

        if not text or len(text.split()) < 2:
            send_text(sender, "👋 Send *first and last name*.")
            return {"status": "await_name"}

        parts = text.split()
        save_member_name(member["id"], parts[0], " ".join(parts[1:]))

        send_text(sender, "✅ Profile updated.")
        send_participation_buttons(sender)
        return {"status": "profile_done"}

    # ───────── TT GATE ─────────
    allowed, reason = ensure_tt_open()
    if not allowed:
        send_text(sender, reason)
        return {"status": "closed"}

    # ───────── PARTICIPATION ─────────
    if not member.get("participation_type"):

        if not button:
            send_participation_buttons(sender)
            return {"status": "await_type"}

        ptype = button.get("id")
        save_participation_type(member["id"], ptype)

        send_text(sender, "👍 Send tonight’s TT code.")
        return {"status": "ptype"}

    # ───────── SUBMISSION ─────────
    submission = get_or_create_submission(member["id"])

    if not submission:
        send_text(sender, "⚠️ Please send TT code again.")
        return {"status": "error"}

    if submission["status"] == "COMPLETE":
        send_text(sender, "✅ Your TT is already recorded.")
        return {"status": "locked"}

    # ───────── TT CODE ─────────
    if not submission["tt_code_verified"]:

        if not text:
            send_text(sender, "🔑 Please send tonight's TT code.")
            return {"status": "await_code"}

        # First validate format ONLY (optional)
        if not is_valid_tt_code(text):
            send_text(sender, "❌ Invalid format.")
            return {"status": "bad_format"}

        # Now verify against actual stored code
        submission = verify_tt_code(submission["id"], text)

        if not submission or not submission.get("tt_code_verified"):
            send_text(sender, "❌ Invalid TT code.")
            return {"status": "bad_code"}

        # Only now proceed
        release_pending_submissions(member["id"])
        submission = get_or_create_submission(member["id"])

        mark_attendance(member["id"])
        send_text(sender, "✅ Checked in!")

        if member["participation_type"] == "WALKER":
            send_text(sender, "🚶 Describe your workout.")
            return {"status": "walk"}

        send_distance_buttons(sender)
        return {"status": "code_ok"}

    # ───────── WALKER ─────────
    if member["participation_type"] == "WALKER":

        if text and not submission["time_text"]:
            submission = save_time(submission["id"], text, 0)
            submission = confirm_submission(submission["id"])

            send_text(sender, "🚶 Workout logged! Well done.")
            return {"status": "walker_done"}

    # ───────── BUTTONS ─────────
    if button:

        btn = button.get("id", "").lower().strip()

        # DISTANCE
        if btn in {"4km", "6km", "8km"}:
            submission = save_distance(
                submission["id"],
                btn.replace("km", "")
            )

            send_text(sender, "⏱ Send your time.")
            return {"status": "distance"}

        # CONFIRM
        if btn == "confirm":

            is_pb = False
            if submission.get("seconds"):
                is_pb = is_personal_best(
                    member["id"],
                    submission["distance_text"],
                    submission["seconds"]
                )

            submission = confirm_submission(submission["id"])

            send_text(sender, "🔥 TT recorded!")

            if is_pb:
                send_text(sender, "🚀 NEW PERSONAL BEST! Massive run! 🔥")

            rows = get_tonight_leaderboard()
            send_text(sender, format_leaderboard(rows))

            for r in rows:
                if (
                    r.get("member_id") == member["id"]
                    and r["distance_text"] == submission["distance_text"]
                ):
                    send_text(
                        sender,
                        f"🏆 You are position {r['position']} in the {r['distance_text']}!"
                    )
                    break

            return {"status": "done"}

        # EDIT
        if btn == "edit":
            send_distance_buttons(sender)
            return {"status": "edit"}

    # ───────── TIME ─────────
    if (
        submission["status"] == "PENDING"
        and submission["distance_text"]
        and not submission["time_text"]
    ):

        if not text or not is_valid_time(text):
            send_text(sender, "⏱ Format: 27:41 or 01:27:41")
            return {"status": "bad_time"}

        parts = list(map(int, text.split(":")))
        seconds = parts[-1] + parts[-2] * 60
        if len(parts) == 3:
            seconds += parts[0] * 3600

        submission = save_time(submission["id"], text, seconds)

        send_confirm_buttons(
            sender,
            submission["distance_text"],
            text
        )

        return {"status": "confirm"}

    return {"status": "noop"}