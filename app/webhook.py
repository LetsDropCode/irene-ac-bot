# app/webhook.py

from fastapi import APIRouter, Request
from app.config import VERIFY_TOKEN
from app.whatsapp import send_whatsapp_message
from app.members import get_member_by_phone, create_member
from app.services.submission_store import save_submission
from app.services.submission_parser import parse_submission
from app.services.validation import validate_submission
from app.services.leaderboard import get_weekly_leaderboard
from app.services.leaderboard_formatter import format_leaderboard
from app.config import ADMIN_NUMBERS

router = APIRouter()


# --------------------------------------------------
# Webhook verification (Meta)
# --------------------------------------------------
@router.get("/webhook")
async def verify_webhook(request: Request):
    params = request.query_params

    if (
        params.get("hub.mode") == "subscribe"
        and params.get("hub.verify_token") == VERIFY_TOKEN
    ):
        return int(params.get("hub.challenge"))

    return {"error": "Verification failed"}


# --------------------------------------------------
# Incoming WhatsApp messages
# --------------------------------------------------
@router.post("/webhook")
async def receive_webhook(request: Request):
    payload = await request.json()
    print("📩 Incoming payload:", payload)

    try:
        message = payload["entry"][0]["changes"][0]["value"]["messages"][0]
        from_number = message["from"]
        text = message.get("text", {}).get("body", "").strip()

        print(f"📨 Message from {from_number}: {text}")

        # --------------------------------------------
        # MEMBER CHECK / REGISTRATION
        # --------------------------------------------
        member = get_member_by_phone(from_number)

        if not member:
            # Expecting Name + Surname
            if " " not in text:
                send_whatsapp_message(
                    to=from_number,
                    text=(
                        "👋 Welcome to *Irene Athletics Club*!\n\n"
                        "Please reply with your *Name and Surname* to register.\n"
                        "Example:\n"
                        "*John Smith*"
                    )
                )
                return {"status": "awaiting_registration"}

            first_name, last_name = text.split(" ", 1)
            internal_id = create_member(from_number, first_name, last_name)

            send_whatsapp_message(
                to=from_number,
                text=(
                    f"✅ Thanks {first_name}!\n\n"
                    f"You’re now registered.\n"
                    f"Member ID: *{internal_id}*\n\n"
                    "You can now submit your run when submissions are open 🏃‍♂️"
                )
            )
            return {"status": "member_created"}

        # --------------------------------------------
        # ADMIN LEADERBOARD COMMAND
        # --------------------------------------------
        if from_number in ADMIN_NUMBERS and text.upper().startswith("LEADERBOARD"):
            parts = text.upper().split()

        if len(parts) != 3:
            send_whatsapp_message(
            to=from_number,
            text="❌ Format: LEADERBOARD TT 6km"
        )
            return {"status": "bad_command"}

        _, event, distance = parts

        rows = get_weekly_leaderboard(event, distance)
        message = format_leaderboard(event, distance, rows)

        send_whatsapp_message(to=from_number, text=message)
        return {"status": "leaderboard_sent"}

        # --------------------------------------------
        # SUBMISSION FLOW (REGISTERED MEMBERS)
        # --------------------------------------------
        parsed = parse_submission(text)

        is_valid, message, event = validate_submission(parsed)

        if not is_valid:
            send_whatsapp_message(to=from_number, text=message)
            return {"status": "rejected"}

        # --------------------------------------------
        # VALID SUBMISSION (Phase E will save to DB)
        # --------------------------------------------
        distance = parsed["distance"]
        time = parsed["time"]
        code = parsed["code"]

        is_pb = save_submission(
            member_id=member["id"],
            event=event,
            distance=distance,
            time_text=time
        )
        pb_text = "🔥 *NEW PERSONAL BEST!* 🔥\n\n" if is_pb else ""
        send_whatsapp_message(
            to=from_number,
            text=(
                "✅ *Submission received!*\n\n"
                f"Event: *{event}*\n"
                f"Distance: *{distance}*\n"
                f"Time: *{time}*\n"
                f"Code: *{code}*\n\n"
                "🏁 Well done!"
            )
        )

        print("✅ Valid submission:", parsed, "Event:", event)

    except Exception as e:
        print("❌ Webhook error:", repr(e))

    return {"status": "received"}