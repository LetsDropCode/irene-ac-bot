# app/webhook.py

import os
from fastapi import APIRouter, Request

from app.db import get_db
from app.whatsapp import send_whatsapp_message

from app.services.event_detector import get_active_event
from app.services.admin_code_service import generate_code
from app.services.submission_parser import parse_submission

router = APIRouter()

ADMIN_NUMBERS = {
    "27722135094",  # Lindsay
}


@router.post("/webhook")
async def webhook(request: Request):
    payload = await request.json()

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})

            # Ignore delivery / read receipts
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

                    if text_upper == "RUNNER":
                        reply = "🏃 You’re set up as a *RUNNER*."
                    elif text_upper == "WALKER":
                        reply = "🚶 You’re set up as a *WALKER*."
                    else:
                        reply = (
                            "🏃‍♂️🚶 You’re set up as *BOTH*.\n\n"
                            "On the day, I’ll ask whether you’re running or walking."
                        )

                    send_whatsapp_message(from_number, reply)
                else:
                    send_whatsapp_message(
                        from_number,
                        "Please reply with one of:\n🏃 RUNNER\n🚶 WALKER\n🏃‍♂️🚶 BOTH"
                    )

                cur.close()
                conn.close()
                return {"status": "participation_set"}

            # --------------------------------------------------
            # ADMIN: ADD CODE (ANY TIME)
            # --------------------------------------------------
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
                send_whatsapp_message(
                    from_number,
                    "⏱️ No active event right now."
                )
                cur.close()
                conn.close()
                return {"status": "no_event"}

            cur.execute(
                """
                SELECT submissions_open
                FROM event_config
                WHERE event = %s
                LIMIT 1;
                """,
                (event,)
            )
            row = cur.fetchone()

            if not row or not row["submissions_open"]:
                send_whatsapp_message(
                    from_number,
                    "⛔ Submissions are currently closed."
                )
                cur.close()
                conn.close()
                return {"status": "closed"}

            # --------------------------------------------------
            # PARSE + STORE SUBMISSION
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

            cur.execute(
                """
                INSERT INTO submissions
                (member_id, activity, distance_text, time_text, seconds, mode)
                VALUES (%s, %s, %s, %s, %s, %s);
                """,
                (
                    member["id"],
                    parsed["activity"],
                    parsed.get("distance"),
                    parsed["time"],
                    parsed["seconds"],
                    parsed["mode"],
                )
            )
            conn.commit()

            send_whatsapp_message(
                from_number,
                "✅ Submission received. Lekker run/walk 👏"
            )

            cur.close()
            conn.close()
            return {"status": "submitted"}

    return {"status": "ok"}