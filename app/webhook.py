# app/webhook.py

import os
import re
import requests
from datetime import datetime
from fastapi import APIRouter, Request

from app.db import get_db
from app.services.admin_code_service import generate_code
from app.services.event_detector import get_active_event

router = APIRouter()

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

# --------------------------------------------------
# Helpers
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
    print("📤 WhatsApp:", response.status_code)


def parse_time_to_seconds(time_text: str) -> int | None:
    """
    Accepts MM:SS or HH:MM:SS
    """
    parts = time_text.split(":")
    try:
        parts = [int(p) for p in parts]
    except ValueError:
        return None

    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]

    return None


# --------------------------------------------------
# Webhook
# --------------------------------------------------

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

            text_upper = text.upper()
            print(f"📨 {from_number}: {text}")

            conn = get_db()
            cur = conn.cursor()

            # ---------------------------------------------
            # Load or create member
            # ---------------------------------------------
            cur.execute(
                "SELECT * FROM members WHERE phone = %s;",
                (from_number,)
            )
            member = cur.fetchone()

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

                send_whatsapp_message(
                    from_number,
                    (
                        "👋 Welcome to the Irene AC WhatsApp bot!\n\n"
                        "How do you usually participate?\n\n"
                        "Reply with:\n"
                        "🏃 RUNNER\n"
                        "🚶 WALKER\n"
                        "🏃‍♂️🚶 BOTH"
                    )
                )
                cur.close()
                conn.close()
                return {"status": "awaiting_participation"}

            # ---------------------------------------------
            # Participation selection
            # ---------------------------------------------
            if member["participation_type"] is None:
                if text_upper in ("RUNNER", "WALKER", "BOTH"):
                    cur.execute(
                        "UPDATE members SET participation_type = %s WHERE id = %s;",
                        (text_upper, member["id"])
                    )
                    conn.commit()

                    if text_upper == "RUNNER":
                        reply = "🏃 You’re set as a RUNNER. Submit time + distance on run days."
                    elif text_upper == "WALKER":
                        reply = "🚶 You’re set as a WALKER. Submit your *time only*."
                    else:
                        reply = (
                            "🏃‍♂️🚶 You’re set as BOTH.\n\n"
                            "On the day I’ll ask whether you’re running or walking."
                        )

                    send_whatsapp_message(from_number, reply)
                    cur.close()
                    conn.close()
                    return {"status": "participation_set"}

                send_whatsapp_message(
                    from_number,
                    "Please reply with RUNNER, WALKER, or BOTH to continue."
                )
                cur.close()
                conn.close()
                return {"status": "awaiting_participation"}

            # ---------------------------------------------
            # Admin: ADD CODE
            # ---------------------------------------------
            if text_upper == "ADD CODE":
                event = get_active_event()
                if not event:
                    send_whatsapp_message(
                        from_number,
                        "⚠️ No active event right now."
                    )
                    cur.close()
                    conn.close()
                    return {"status": "no_event"}

                code = generate_code()

                cur.execute(
                    """
                    INSERT INTO event_codes (event, code, event_date)
                    VALUES (%s, %s, CURRENT_DATE);
                    """,
                    (event, code)
                )
                conn.commit()

                send_whatsapp_message(
                    from_number,
                    f"🔐 Code for *{event}*: {code}"
                )
                cur.close()
                conn.close()
                return {"status": "code_created"}

            # ---------------------------------------------
            # Submission handling
            # ---------------------------------------------
            event = get_active_event()
            if not event:
                send_whatsapp_message(
                    from_number,
                    "⏱ Submissions are currently closed."
                )
                cur.close()
                conn.close()
                return {"status": "closed"}

            # Extract time
            time_match = re.search(r"\b\d{1,2}:\d{2}(?::\d{2})?\b", text)
            if not time_match:
                send_whatsapp_message(
                    from_number,
                    "❌ Please include a valid time (MM:SS or HH:MM:SS)."
                )
                cur.close()
                conn.close()
                return {"status": "invalid_time"}

            time_text = time_match.group()
            seconds = parse_time_to_seconds(time_text)
            if seconds is None:
                send_whatsapp_message(from_number, "❌ Invalid time format.")
                cur.close()
                conn.close()
                return {"status": "invalid_time"}

            # Determine RUN vs WALK
            mode = "RUN"
            if member["participation_type"] == "WALKER":
                mode = "WALK"
            elif member["participation_type"] == "BOTH":
                if "WALK" in text_upper:
                    mode = "WALK"

            distance_text = None
            if mode == "RUN":
                dist_match = re.search(r"\b\d+(\.\d+)?\s?K(M)?\b", text_upper)
                if not dist_match:
                    send_whatsapp_message(
                        from_number,
                        "❌ Runners must include distance (e.g. 5km)."
                    )
                    cur.close()
                    conn.close()
                    return {"status": "missing_distance"}
                distance_text = dist_match.group()

            # Validate code for runners
            if mode == "RUN":
                cur.execute(
                    """
                    SELECT 1 FROM event_codes
                    WHERE event = %s AND code = %s AND event_date = CURRENT_DATE;
                    """,
                    (event, text_upper)
                )
                if not cur.fetchone():
                    send_whatsapp_message(
                        from_number,
                        "❌ Invalid or missing event code."
                    )
                    cur.close()
                    conn.close()
                    return {"status": "invalid_code"}

            # Store submission
            cur.execute(
                """
                INSERT INTO submissions
                (member_id, activity, distance_text, time_text, seconds, mode)
                VALUES (%s, %s, %s, %s, %s, %s);
                """,
                (
                    member["id"],
                    event,
                    distance_text,
                    time_text,
                    seconds,
                    mode
                )
            )
            conn.commit()

            send_whatsapp_message(
                from_number,
                f"✅ {mode} submission recorded for {event}!"
            )

            cur.close()
            conn.close()
            return {"status": "submitted"}

    return {"status": "ok"}