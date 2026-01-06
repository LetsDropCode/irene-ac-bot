# app/webhook.py

import os
from fastapi import APIRouter, Request

from app.db import get_db
from app.whatsapp import send_whatsapp_message

from app.services.event_detector import get_active_event
from app.services.admin_code_service import generate_code
from app.services.submission_parser import parse_submission
from app.services.submission_handler import store_submission


router = APIRouter()

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

# ⚠️ Replace with real admin numbers
ADMIN_NUMBERS = {
    "27722135094",  # Lindsay
}


@router.post("/webhook")
async def webhook(request: Request):
    payload = await request.json()

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})

            # -----------------------------------
            # Ignore delivery / read receipts
            # -----------------------------------
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

            # -----------------------------------
            # Load / create member
            # -----------------------------------
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
                    "👋 Welcome to the Irene AC bot!\n\n"
                    "How do you usually participate?\n\n"
                    "🏃 RUNNER\n"
                    "🚶 WALKER\n"
                    "🏃‍♂️🚶 BOTH"
                )
                cur.close()
                conn.close()
                return {"status": "awaiting_participation"}

            # -----------------------------------
            # Participation setup
            # -----------------------------------
            if member["participation_type"] is None:
                if text_upper in {"RUNNER", "WALKER", "BOTH"}:
                    cur.execute(
                        "UPDATE members SET participation_type = %s WHERE id = %s;",
                        (text_upper, member["id"])
                    )
                    conn.commit()

                    if text_upper == "RUNNER":
                        reply = "🏃 You’re set as a *RUNNER*."
                    elif text_upper == "WALKER":
                        reply = "🚶 You’re set as a *WALKER*."
                    else:
                        reply = "🏃‍♂️🚶 You’re set as *BOTH*."

                    send_whatsapp_message(from_number, reply)
                else:
                    send_whatsapp_message(
                        from_number,
                        "Please reply with:\n🏃 RUNNER\n🚶 WALKER\n🏃‍♂️🚶 BOTH"
                    )

                cur.close()
                conn.close()
                return {"status": "participation_set"}

            # -----------------------------------
            # ADMIN: ADD CODE (allowed ANY time)
            # -----------------------------------
            if text_upper == "ADD CODE":
                if from_number not in ADMIN_NUMBERS:
                    send_whatsapp_message(
                        from_number,
                        "⛔ You are not authorised to add event codes."
                    )
                    cur.close()
                    conn.close()
                    return {"status": "unauthorised"}

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
                    f"🔐 {event} CODE FOR TODAY\n\n{code}"
                )

                cur.close()
                conn.close()
                return {"status": "code_created"}

            # -----------------------------------
            # Submission window enforcement
            # -----------------------------------
            cur.execute(
                """
                SELECT submissions_open
                FROM event_config
                WHERE event = %s
                LIMIT 1;
                """,
                (get_active_event(),)
            )
            row = cur.fetchone()

            if not row or not row["submissions_open"]:
                send_whatsapp_message(
                    from_number,
                    "⏱️ Submissions are currently closed."
                )
                cur.close()
                conn.close()
                return {"status": "closed"}

            # -----------------------------------
            # Parse submission
            # -----------------------------------
            parsed = parse_submission(text)

            if not parsed:
                send_whatsapp_message(
                    from_number,
                    "❌ Could not read submission.\n\n"
                    "Example:\n"
                    "5km 25:30 CODE123\n"
                    "25:30 CODE123 (walkers)"
                )
                cur.close()
                conn.close()
                return {"status": "parse_failed"}

            store_submission(
                member_id=member["id"],
                activity=parsed["activity"],
                distance_text=parsed.get("distance"),
                time_text=parsed["time"],
                seconds=parsed["seconds"],
                mode=parsed["mode"]
            )

            send_whatsapp_message(
                from_number,
                "✅ Submission received. Well done!"
            )

            cur.close()
            conn.close()
            return {"status": "submitted"}

    return {"status": "ok"}