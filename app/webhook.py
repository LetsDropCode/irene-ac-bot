# app/webhook.py
from fastapi import APIRouter, Request
from app.config import VERIFY_TOKEN
from app.whatsapp import send_whatsapp_message

router = APIRouter()   # ✅ THIS WAS MISSING / BROKEN


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
        text = message["text"]["body"].strip()

        print(f"📨 {from_number}: {text}")

        # ---- TT COMMAND ----
        if text.upper().startswith("TT"):
            parts = text.split()

            if len(parts) != 3:
                send_whatsapp_message(
                    to=from_number,
                    text=(
                        "❌ Invalid TT format.\n\n"
                        "Use:\nTT 5km 21:34"
                    )
                )
                return {"status": "bad_tt_format"}

            _, distance, time = parts

            print(f"🏁 TT SUBMISSION → {from_number} | {distance} | {time}")

            send_whatsapp_message(
                to=from_number,
                text=(
                    "✅ TT received!\n\n"
                    f"Distance: {distance}\n"
                    f"Time: {time}\n\n"
                    "Good luck! 🏃‍♂️🔥"
                )
            )
            return {"status": "tt_logged"}

        # ---- DEFAULT RESPONSE ----
        send_whatsapp_message(
            to=from_number,
            text=(
                "👋 Irene AC Bot here!\n\n"
                "To submit a Time Trial, send:\n"
                "TT 5km 21:34"
            )
        )

    except Exception as e:
        print("❌ Webhook error:", repr(e))

    return {"status": "ok"}