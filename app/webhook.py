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

    print("📥 Incoming WhatsApp payload:")
    print(payload)

    try:
        entry = payload["entry"][0]
        change = entry["changes"][0]
        value = change["value"]

        messages = value.get("messages")
        if not messages:
            return {"status": "no_message"}

        message = messages[0]
        sender = message["from"]
        text = message["text"]["body"]

        print("👤 Sender:", sender)
        print("💬 Text:", text)

        # 🔁 TEMP RESPONSE FOR TESTING
        send_whatsapp_message(
            to=sender,
            message=f"✅ Bot received: {text}"
        )

    except Exception as e:
        print("❌ Error handling webhook:", str(e))

    return {"status": "received"}