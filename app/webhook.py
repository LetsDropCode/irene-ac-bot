# app/webhook.py

import os
from datetime import datetime
from fastapi import APIRouter, Request

from app.db import get_db
from app.whatsapp import send_whatsapp_message

# Services
from app.services.admin_code_service import generate_code 
from app.services.event_detector import get_active_event
from app.services.event_code_validator import store_event_code
from app.services.submission_handler import handle_submission

router = APIRouter()

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

# ⚠️ Replace with real admin numbers
ADMIN_NUMBERS = {
    "27722135094",  # Lindsay
}


# --------------------------------------------------
# Helpers
# --------------------------------------------------

def is_admin(phone: str) -> bool:
    return phone in ADMIN_NUMBERS


def normalise_text(text: str) -> str:
    return text.strip().upper()


# --------------------------------------------------
# Webhook
# --------------------------------------------------

@router.post("/webhook")
async def webhook(request: Request):
    payload = await request.json()

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})

            # ---------------------------------------------
            # Ignore delivery / read receipts
            # ---------------------------------------------
            if "messages" not in value:
                return {"status": "ignored"}

            message = value["messages"][0]
            from_number = message.get("from")
            raw_text = message.get("text", {}).get("body", "")

            if not from_number or not raw_text:
                return {"status": "invalid"}

            text = normalise_text(raw_text)

            print(f"📨 Message from {from_number}: {text}")

            # =================================================
            # 1️⃣ ADMIN COMMANDS (FIRST – NEVER MOVE THIS)
            # =================================================

            if text == "ADD CODE":
                if not is_admin(from_number):
                    send_whatsapp_message(
                        from_number,
                        "⛔ You are not authorised to add event codes."
                    )
                    return {"status": "unauthorised"}

                event = get_active_event()

                if not event:
                    send_whatsapp_message(
                        from_number,
                        "❌ No active event detected today."
                    )
                    return {"status": "no_event"}

                code = generate_code(event)
                store_event_code(event, code)

                send_whatsapp_message(
                    from_number,
                    f"🔐 *{event} CODE GENERATED*\n\n"
                    f"Code: *{code}*\n\n"
                    "Share this with participants."
                )
                return {"status": "admin_code_created"}

            # =================================================
            # 2️⃣ MEMBER LOOKUP / CREATE
            # =================================================

            conn = get_db()
            cur = conn.cursor()

            cur.execute(
                "SELECT * FROM members WHERE phone = %s;",
                (from_number,)
            )
            member = cur.fetchone()

            if not member:
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

                send_whatsapp_message(
                    from_number,
                    "👋 Welcome to the *Irene AC Bot*!\n\n"
                    "How do you usually participate?\n\n"
                    "Reply with:\n"
                    "🏃 RUNNER\n"
                    "🚶 WALKER\n"
                    "🏃‍♂️🚶 BOTH"
                )
                cur.close()
                conn.close()
                return {"status": "awaiting_participation"}

            # =================================================
            # 3️⃣ PARTICIPATION TYPE SETUP
            # =================================================

            if member["participation_type"] is None:
                if text not in {"RUNNER", "WALKER", "BOTH"}:
                    send_whatsapp_message(
                        from_number,
                        "Please reply with one of:\n\n"
                        "🏃 RUNNER\n"
                        "🚶 WALKER\n"
                        "🏃‍♂️🚶 BOTH"
                    )
                    cur.close()
                    conn.close()
                    return {"status": "awaiting_valid_participation"}

                cur.execute(
                    """
                    UPDATE members
                    SET participation_type = %s
                    WHERE id = %s;
                    """,
                    (text, member["id"])
                )
                conn.commit()

                if text == "RUNNER":
                    reply = (
                        "🏃 You're set up as a *RUNNER*.\n\n"
                        "On run days, submit *time + distance + code*."
                    )
                elif text == "WALKER":
                    reply = (
                        "🚶 You're set up as a *WALKER*.\n\n"
                        "On walk days, submit *time only*."
                    )
                else:
                    reply = (
                        "🏃‍♂️🚶 You're set up as *BOTH*.\n\n"
                        "On the day, I’ll ask if you're running or walking."
                    )

                send_whatsapp_message(from_number, reply)
                cur.close()
                conn.close()
                return {"status": "participation_set"}

            # =================================================
            # 4️⃣ SUBMISSION HANDLING
            # =================================================

            result = handle_submission(
                member=member,
                message=text,
                phone=from_number
            )

            if result:
                send_whatsapp_message(from_number, result)
                cur.close()
                conn.close()
                return {"status": "submission_processed"}

            # =================================================
            # 5️⃣ FALLBACK
            # =================================================

            send_whatsapp_message(
                from_number,
                "✅ You’re registered.\n\n"
                "Send your run or walk submission when ready."
            )

            cur.close()
            conn.close()

    return {"status": "ok"}