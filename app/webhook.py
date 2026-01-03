# app/webhook.py
from fastapi import APIRouter, Request
from app.config import VERIFY_TOKEN
from app.whatsapp import send_whatsapp_message

router = APIRouter()


@router.get("/webhook")
async def verify_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return int(challenge)

    return {"error": "Verification failed"}


@router.post("/webhook")
async def receive_webhook(request: Request):
    payload = await request.json()
    print("📩 Incoming WhatsApp payload:")
    print(payload)

    try:
        entry = payload.get("entry", [])[0]
        change = entry.get("changes", [])[0]
        value = change.get("value", {})

        # Ignore delivery/status events
        messages = value.get("messages")
        if not messages:
            print("ℹ️ No user message in this webhook")
            return {"status": "ignored"}

        message = messages[0]
        from_number = message.get("from")

        # Only handle text messages
        if message.get("type") != "text":
            print("ℹ️ Non-text message received")
            return {"status": "ignored"}

        text = message["text"]["body"]
        print(f"📨 Message from {from_number}: {text}")

        # 🔁 Reply
        send_whatsapp_message(
            to=from_number,
            text="✅ Bot is live on Railway and replying correctly!"
        )

    except Exception as e:
        print("❌ Error processing webhook:", repr(e))

    return {"status": "received"}