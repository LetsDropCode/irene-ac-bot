# app/webhook.py

import os
from fastapi import APIRouter, Request

from app.db import get_db
from app.whatsapp import send_whatsapp_message

from app.services.event_detector import get_active_event
from app.services.admin_code_service import generate_code
from app.services.submission_parser import parse_submission
from app.services.submission_service import store_submission

router = APIRouter()

ADMIN_NUMBERS = {
    "27722135094",  # Lindsay
    "27738870757", #Jacqueline
    "27829370733", #Wynand
    "27818513864", #Johan
}


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

            # --------------------------------------------------
            # MEMBER LOOKUP / CREATE
            # --------------------------------------------------
            cur.execute(
                "SELECT * FROM members WHERE phone = %s;",
                (from_number,)
            )
            member = cur.fetchone()

            if not member:
                cur.execute(
                    """
                    INSERT INTO members (phone, first_name, last_name, participation_type)
                    VALUES (%s, 'Unknown', 'Member', NULL)
                    RETURNING *;
                    """,
                    (from_number,)
                )
                member = cur.fetchone()
                conn.commit()

                send_whatsapp_message(
                    from_number,
                    "👋 Welcome to the Irene AC WhatsApp bot!\n\n"
                    "How do you usually participate?\n\n"
                    "🏃 RUNNER\n"
                    "🚶 WALKER\n"
                    "🏃‍♂️🚶 BOTH"
                )
                cur.close()
                conn.close()
                return {"status": "awaiting_participation"}

            # --------------------------------------------------
            # PARTICIPATION SETUP
            # --------------------------------------------------
            if member["participation_type"] is None:
                if text_upper in {"RUNNER", "WALKER", "BOTH"}:
                    cur.execute(
                        "UPDATE members SET participation_type = %s WHERE id = %s;",
                        (text_upper, member["id"])
                    )
                    conn.commit()

                    reply = (
                        "🏃 You’re set up as a *RUNNER*."
                        if text_upper == "RUNNER"
                        else "🚶 You’re set up as a *WALKER*."
                        if text_upper == "WALKER"
                        else "🏃‍♂️🚶 You’re set up as *BOTH*.\n\n"
                             "On the day, I’ll ask whether you’re running or walking."
                    )

                    send_whatsapp_message(from_number, reply)
                else:
                    send_whatsapp_message(
                        from_number,
                        "Please reply with:\n🏃 RUNNER\n🚶 WALKER\n🏃‍♂️🚶 BOTH"
                    )

                cur.close()
                conn.close()
                return {"status": "participation_set"}

            # --------------------------------------------------
            # ADMIN: ADD CODE
            # --------------------------------------------------
            if text_upper == "ADD CODE":
                if from_number not in ADMIN_NUMBERS:
                    send_whatsapp_message(from_number, "⛔ Not authorised.")
                    cur.close()
                    conn.close()
                    return {"status": "unauthorised"}

                event = get_active_event()
                if not event:
                    send_whatsapp_message(from_number, "⚠️ No active event.")
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
                    f"🔐 *{event} CODE FOR TODAY*\n\n{code}"
                )

                cur.close()
                conn.close()
                return {"status": "code_created"}

            # --------------------------------------------------
            # SUBMISSION WINDOW CHECK
            # --------------------------------------------------
            event = get_active_event()
            if not event:
                send_whatsapp_message(from_number, "⏱️ No active event.")
                cur.close()
                conn.close()
                return {"status": "no_event"}
            # --------------------------------------------------
            # ADMIN: OPEN / CLOSE SUBMISSIONS
            # --------------------------------------------------
            if text_upper in {"OPEN SUBMISSIONS", "CLOSE SUBMISSIONS"}:
                if from_number not in ADMIN_NUMBERS:
                    send_whatsapp_message(from_number, "⛔ Not authorised.")
                cur.close()
                conn.close()
                return {"status": "unauthorised"}

            event = get_active_event()

            if not event:
                send_whatsapp_message(
                from_number,
                "⚠️ No event scheduled right now."
                )
                cur.close()
                conn.close()
                return {"status": "no_event"}

            from app.services.submission_gate import set_submission_state

            if text_upper == "OPEN SUBMISSIONS":
                set_submission_state(event, 1)
                reply = f"🟢 *{event} submissions are now OPEN*"

            else:
                set_submission_state(event, 0)
                reply = f"🔴 *{event} submissions are now CLOSED*"

            send_whatsapp_message(from_number, reply)
            cur.close()
            conn.close()
            return {"status": "submission_gate_updated"}
        
        
            # --------------------------------------------------
            # PARSE SUBMISSION
            # --------------------------------------------------
            parsed = parse_submission(text)
            if not parsed:
                send_whatsapp_message(
                    from_number,
                    "❌ I couldn’t read that.\n\n"
                    "Examples:\n"
                    "5km 25:30 CODE123\n"
                    "25:30 CODE123 (walkers)"
                )
                cur.close()
                conn.close()
                return {"status": "parse_failed"}

            # --------------------------------------------------
            # STORE SUBMISSION (SERVICE)
            # --------------------------------------------------
            store_submission(
                member_id=member["id"],
                activity=parsed["activity"],
                distance_text=parsed.get("distance"),
                time_text=parsed["time"],
                seconds=parsed["seconds"],
                mode=parsed["mode"],
            )

            send_whatsapp_message(
                from_number,
                "✅ Submission received. Lekker run/walk 👏"
            )

            cur.close()
            conn.close()
            return {"status": "submitted"}

    return {"status": "ok"}