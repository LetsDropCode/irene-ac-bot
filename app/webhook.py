# app/webhook.py

from fastapi import APIRouter, Request
from app.config import VERIFY_TOKEN, ADMIN_NUMBERS
from app.whatsapp import send_whatsapp_message
from app.members import get_member_by_phone, create_member
from app.services.submission_parser import parse_submission
from app.services.validation import validate_submission
from app.services.submission_store import save_submission

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

        # ==================================================
        # ADMIN: DAILY EVENT CODES
        # ==================================================
        if from_number in ADMIN_NUMBERS and text.upper() == "ADMIN CODES":
            from app.services.admin_codes import generate_admin_code_message
            reply = generate_admin_code_message()
            send_whatsapp_message(from_number, reply)
            return {"status": "admin_codes_sent"}

        # ==================================================
        # MEMBER REGISTRATION
        # ==================================================
        member = get_member_by_phone(from_number)

        if not member:
            if " " not in text:
                send_whatsapp_message(
                    to=from_number,
                    text=(
                        "👋 Welcome to *Irene Athletics Club*!\n\n"
                        "Please reply with your *Name and Surname*.\n"
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
                    "You can submit once runs are open 🏃‍♂️"
                )
            )
            return {"status": "member_created"}

        # ==================================================
        # ADMIN: LEADERBOARD COMMAND
        # ==================================================
        if from_number in ADMIN_NUMBERS and text.upper().startswith("LEADERBOARD"):
            parts = text.upper().split()

            if len(parts) != 3:
                send_whatsapp_message(
                    to=from_number,
                    text="❌ Format: LEADERBOARD TT 6km"
                )
                return {"status": "bad_command"}

            _, event, distance = parts

            from app.services.leaderboard import get_weekly_leaderboard
            from app.services.leaderboard_formatter import format_leaderboard

            rows = get_weekly_leaderboard(event, distance)
            message = format_leaderboard(event, distance, rows)

            send_whatsapp_message(to=from_number, text=message)
            return {"status": "leaderboard_sent"}

        # ==================================================
        # RUN SUBMISSION FLOW
        # ==================================================
        parsed = parse_submission(text)

        is_valid, error_message, event = validate_submission(parsed)

        if not is_valid:
            send_whatsapp_message(to=from_number, text=error_message)
            return {"status": "rejected"}

        # --------------------------------------------------
        # Save submission (with duplicate protection)
        # --------------------------------------------------
        result = save_submission(
            member_id=member["id"],
            event=event,
            distance=parsed["distance"],
            time_text=parsed["time"]
        )

        if result == "DUPLICATE":
            send_whatsapp_message(
                to=from_number,
                text=(
                    "❌ *Submission already received*\n\n"
                    f"You’ve already submitted for *{event}* today.\n"
                    "Only one submission per event is allowed 🏁"
                )
            )
            return {"status": "duplicate"}

        pb_text = "🔥 *NEW PERSONAL BEST!* 🔥\n\n" if result else ""

        send_whatsapp_message(
            to=from_number,
            text=(
                f"{pb_text}"
                "✅ *Submission received!*\n\n"
                f"Event: *{event}*\n"
                f"Distance: *{parsed['distance']}*\n"
                f"Time: *{parsed['time']}*\n\n"
                "🏁 Well done!"
            )
        )

        print("✅ Submission saved:", parsed)

    except Exception as e:
        print("❌ Webhook error:", repr(e))

    return {"status": "received"}