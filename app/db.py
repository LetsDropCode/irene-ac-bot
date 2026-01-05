# app/webhook.py

import os
from fastapi import APIRouter, Request
from app.db import get_db

router = APIRouter()

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")


@router.post("/webhook")
async def webhook(request: Request):
    payload = await request.json()

    # Loop through WhatsApp structure safely
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):

            value = change.get("value", {})

            # --------------------------------------------------
            # ✅ Ignore delivery / read status callbacks
            # --------------------------------------------------
            if "messages" not in value:
                # This is a sent / delivered / read receipt
                return {"status": "ignored"}

            message = value["messages"][0]

            from_number = message.get("from")
            text = message.get("text", {}).get("body", "").strip()

            if not from_number or not text:
                return {"status": "invalid_message"}

            print(f"📨 Message from {from_number}: {text}")

            conn = get_db()
            cur = conn.cursor()

            # --------------------------------------------------
            # 🔍 Look up or create member
            # --------------------------------------------------
            cur.execute(
                "SELECT * FROM members WHERE phone = %s;",
                (from_number,)
            )
            member = cur.fetchone()

            if not member:
                # First-time user
                cur.execute(
                    """
                    INSERT INTO members (phone, first_name, last_name, participation_type)
                    VALUES (%s, %s, %s, %s)
                    RETURNING *;
                    """,
                    (from_number, "Unknown", "Member", None)
                )
                member = cur.fetchone()
                conn.commit()

                reply = (
                    "👋 Welcome to the Irene AC WhatsApp bot!\n\n"
                    "Before we get going, how do you usually participate?\n\n"
                    "Reply with:\n"
                    "🏃 RUNNER\n"
                    "🚶 WALKER\n"
                    "🏃‍♂️🚶 BOTH"
                )

            else:
                reply = (
                    "👋 Hi again!\n\n"
                    "I’ve got you registered. Submission features are active.\n"
                    "More coming very soon 👀"
                )

            cur.close()
            conn.close()

            # --------------------------------------------------
            # 📤 Send WhatsApp reply
            # --------------------------------------------------
            send_whatsapp_message(from_number, reply)

    return {"status": "ok"}


# --------------------------------------------------
# 📤 WhatsApp Send Helper
# --------------------------------------------------
def send_whatsapp_message(to_number: str, message: str):
    import requests

    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": message},
    }

    response = requests.post(url, headers=headers, json=payload)

    print("📤 WhatsApp send response:")
    print("📤 Status:", response.status_code)
    print("📤 Body:", response.text)