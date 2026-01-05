# app/webhook.py
from fastapi import APIRouter, Request
from app.config import VERIFY_TOKEN, ADMIN_NUMBERS
from app.whatsapp import send_whatsapp_message
from app.members import get_member_by_phone, create_member
from app.services.submission_parser import parse_submission
from app.services.validation import validate_submission
from app.services.submission_store import save_submission

router = APIRouter()


@router.get("/webhook")
async def verify_webhook(request: Request):
    params = request.query_params
    if (
        params.get("hub.mode") == "subscribe"
        and params.get("hub.verify_token") == VERIFY_TOKEN
    ):
        return int(params.get("hub.challenge"))
    return {"error": "Verification failed"}


@router.post("/webhook")
async def receive_webhook(request: Request):
    payload = await request.json()
    print("📩 Incoming payload:", payload)

    try:
        message = payload["entry"][0]["changes"][0]["value"]["messages"][0]
        from_number = message["from"]
        text = message.get("text", {}).get("body", "").strip()

        print(f"📨 Message from {from_number}: {text}")

        # ---------------- ADMIN CODES ----------------
        if from_number in ADMIN_NUMBERS and text.upper() == "ADMIN CODES":
            from app.services.admin_codes import generate_admin_code_message
            reply = generate_admin_code_message()
            send_whatsapp_message(from_number, reply)
            return {"status": "admin_codes_sent"}

        # ---------------- REGISTRATION ----------------
        member = get_member_by_phone(from_number)

        if not member:
            if " " not in text:
                send_whatsapp_message(
                    from_number,
                    "👋 Welcome to *Irene Athletics Club*!\n\n"
                    "Please reply with your *Name and Surname*.\n"
                    "Example:\n*John Smith*"
                )
                return {"status": "awaiting_registration"}

            first_name, last_name = text.split(" ", 1)
            create_member(from_number, first_name, last_name)

            send_whatsapp_message(
                from_number,
                f"✅ Thanks {first_name}! You’re now registered.\n\n"
                "You can submit once runs are open 🏃‍♂️"
            )
            return {"status": "member_created"}

        # ---------------- SUBMISSION ----------------
        parsed = parse_submission(text)
        is_valid, reply, event = validate_submission(parsed)

        if not is_valid:
            send_whatsapp_message(from_number, reply)
            return {"status": "rejected"}

        save_submission(
            phone=from_number,
            activity=event,
            distance_text=parsed["distance"],
            time_text=parsed["time"]
        )

        send_whatsapp_message(
            from_number,
            "✅ *Submission received!*\n\n"
            f"Event: *{event}*\n"
            f"Distance: *{parsed['distance']}*\n"
            f"Time: *{parsed['time']}*"
        )

    except Exception as e:
        print("❌ Webhook error:", repr(e))

    return {"status": "received"}