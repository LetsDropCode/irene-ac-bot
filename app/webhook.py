from fastapi import APIRouter, Request
from app.config import VERIFY_TOKEN
from app.whatsapp import send_whatsapp_message
from app.members import get_member_by_phone, create_member

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

        member = get_member_by_phone(from_number)

        # 🆕 First-time user
        if not member:
            if " " not in text:
                send_whatsapp_message(
                    to=from_number,
                    text=(
                        "👋 Welcome to Irene Athletics Club!\n\n"
                        "Please reply with your *Name and Surname*.\n"
                        "Example: John Smith"
                    )
                )
                return {"status": "awaiting_name"}

            first_name, last_name = text.split(" ", 1)
            internal_id = create_member(from_number, first_name, last_name)

            send_whatsapp_message(
                to=from_number,
                text=(
                    f"✅ Thanks {first_name}!\n\n"
                    f"You are now registered.\n"
                    f"Your member ID is *{internal_id}* 🏃‍♂️"
                )
            )
            return {"status": "member_created"}

        # 👤 Existing member
        send_whatsapp_message(
            to=from_number,
            text="👋 You’re already registered. Ready for your next submission!"
        )

    except Exception as e:
        print("❌ Webhook error:", repr(e))

    return {"status": "received"}