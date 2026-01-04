# app/webhook.py
from fastapi import APIRouter, Request
from app.config import VERIFY_TOKEN
from app.whatsapp import send_whatsapp_message

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
    print("📩 Incoming WhatsApp payload:", payload)

    try:
        entry = payload["entry"][0]
        change = entry["changes"][0]
        value = change["value"]

        messages = value.get("messages")
        if not messages:
            return {"status": "ignored"}

        message = messages[0]

        if message.get("type") != "text":
            return {"status": "non_text"}

        from_number = message["from"]
        text = message["text"]["body"]

        print(f"📨 Message from {from_number}: {text}")

        send_whatsapp_message(
            to=from_number,
            text="✅ Irene AC Bot is live! Phase 1 active 🏃‍♂️"
        )

    except Exception as e:
        print("❌ Webhook error:", repr(e))

    return {"status": "ok"}