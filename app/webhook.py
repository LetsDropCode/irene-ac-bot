# app/webhook.py

import os
import requests
from fastapi import APIRouter, Request
from app.db import get_db

router = APIRouter()

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")


@router.post("/webhook")
async def webhook(request: Request):
    payload = await request.json()

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})

            # Ignore delivery/read receipts
            if "messages" not in value:
                return {"status": "ignored"}

            message = value["messages"][0]
            from_number = message.get("from")
            text = message.get("text", {}).get("body", "").strip()

            if not from_number or not text:
                return {"status": "invalid"}

            print(f"📨 Message from {from_number}: {text}")

            conn = get_db()
            cur = conn.cursor()

            # ---------------------------------------------
            # Find or create member
            # ---------------------------------------------
            cur.execute(
                "SELECT * FROM members WHERE phone = %s;",
                (from_number,)
            )
            member = cur.fetchone()

            # First-time user
            if not member:
                cur.execute(
                    """
                    INSERT INTO members (phone, first_name, last_name, participation_type)
                    VALUES (%s, %s, %s, NULL)
                    RETURNING *;
                    """,
                    (from_number, "Unknown", "Member")
                )
                member = cur.fetchone()
                conn.commit()

                reply = (
                    "👋 Welcome to the Irene AC WhatsApp bot!\n\n"
                    "How do you usually participate?\n\n"
                    "Reply with:\n"
                    "🏃 RUNNER\n"
                    "🚶 WALKER\n"
                    "🏃‍♂️🚶 BOTH"
                )

                cur.close()
                conn.close()
                send_whatsapp_message(from_number, reply)
                return {"status": "awaiting_participation"}

            # ---------------------------------------------
            # Participation setup
            # ---------------------------------------------
            if member["participation_type"] is None:
                choice = text.upper()

                if choice in ["RUNNER", "WALKER", "BOTH"]:
                    cur.execute(
                        """
                        UPDATE members
                        SET participation_type = %s
                        WHERE id = %s;
                        """,
                        (choice, member["id"])
                    )
                    conn.commit()

                    if choice == "RUNNER":
                        reply = "🏃 You’re set up as a *RUNNER*."
                    elif choice == "WALKER":
                        reply = "🚶 You’re set up as a *WALKER*."
                    else:
                        reply = (
                            "🏃‍♂️🚶 You’re set up as *BOTH*.\n\n"
                            "On the day, I’ll ask whether you’re running or walking."
                        )

                    cur.close()
                    conn.close()
                    send_whatsapp_message(from_number, reply)
                    return {"status": "participation_set"}

                else:
                    reply = (
                        "Please reply with one of:\n\n"
                        "🏃 RUNNER\n"
                        "🚶 WALKER\n"
                        "🏃‍♂️🚶 BOTH"
                    )

                    cur.close()
                    conn.close()
                    send_whatsapp_message(from_number, reply)
                    return {"status": "awaiting_participation"}

            # ---------------------------------------------
            # Normal flow placeholder
            # ---------------------------------------------
            reply = "✅ You’re registered. Submission features coming next."

            cur.close()
            conn.close()
            send_whatsapp_message(from_number, reply)

    return {"status": "ok"}


# --------------------------------------------------
# WhatsApp sender
# --------------------------------------------------
def send_whatsapp_message(to_number: str, message: str):
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
    print("📤 WhatsApp response:", response.status_code)