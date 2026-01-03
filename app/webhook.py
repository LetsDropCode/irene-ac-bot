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
        entry = payload["entry"][0]
        change = entry["changes"][0]
        value = change["value"]

        messages = value.get("messages")
        if not messages:
            return {"status": "no_message"}

        message = messages[0]
        from_number = message["from"]
        text = message.get("text", {}).get("body", "")

        print(f"📨 Message from {from_number}: {text}")

        # 🔁 Echo reply (test)
        send_whatsapp_message(
            to=from_number,
            text="✅ Bot is live on Railway and replying correctly!"
        )

    except Exception as e:
        print("❌ Error processing webhook:", repr(e))

    return {"status": "received"}