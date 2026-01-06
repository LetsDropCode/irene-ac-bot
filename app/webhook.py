# app/webhook.py

import os
from datetime import datetime
from fastapi import APIRouter, Request

from app.db import get_db
from app.whatsapp import send_whatsapp_message

from app.services.event_detector import get_active_event
from app.services.admin_code_service import generate_code
from app.services.submission_handler import handle_submission

router = APIRouter()

# -----------------------------------------
# CONFIG
# -----------------------------------------
ADMIN_NUMBERS = {
    "27722135094",  # <-- YOU
}

# -----------------------------------------
# HELPERS
# -----------------------------------------
def get_today_event() -> str | None:
    """Return today's event ignoring open/close times"""
    today = datetime.now().weekday()  # Monday = 0

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT event
        FROM event_config
        WHERE day_of_week = %s
          AND active = 1
        LIMIT 1;
        """,
        (today,)
    )

    row = cur.fetchone()
    cur.close()
    conn.close()

    return row["event"] if row else None


# -----------------------------------------
# WEBHOOK
# -----------------------------------------
@router.post("/webhook")
async def webhook(request: Request):
    payload = await request.json()

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):

            value = change.get("value", {})

            # Ignore WhatsApp delivery/read receipts
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

            # -----------------------------------------
            # MEMBER LOOKUP / CREATE
            # -----------------------------------------
            cur.execute("SELECT * FROM members WHERE phone = %s;", (from_number,))
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
                    "👋 Welcome to the Irene AC WhatsApp bot!\n\n"
                    "How do you usually participate?\n\n"
                    "🏃 RUNNER\n🚶 WALKER\n🏃‍♂️🚶 BOTH"
                )

                cur.close()
                conn.close()
                return {"status": "registered"}

            # -----------------------------------------
            # PARTICIPATION SETUP
            # -----------------------------------------
            if member["participation_type"] is None:
                if text_upper in {"RUNNER", "WALKER", "BOTH"}:
                    cur.execute(
                        """
                        UPDATE members
                        SET participation_type = %s
                        WHERE id = %s;
                        """,
                        (text_upper, member["id"])
                    )
                    conn.commit()

                    send_whatsapp_message(
                        from_number,
                        f"✅ You’re set up as *{text_upper}*.\n\n"
                        "You can submit during event hours."
                    )

                    cur.close()
                    conn.close()
                    return {"status": "participation_set"}

                send_whatsapp_message(
                    from_number,
                    "Please reply with one of:\n\n"
                    "🏃 RUNNER\n🚶 WALKER\n🏃‍♂️🚶 BOTH"
                )

                cur.close()
                conn.close()
                return {"status": "awaiting_participation"}

            # -----------------------------------------
            # ADMIN: ADD CODE (DAY-BASED, NOT TIME-BASED)
            # -----------------------------------------
            if text_upper == "ADD CODE":
                if from_number not in ADMIN_NUMBERS:
                    send_whatsapp_message(
                        from_number,
                        "⛔ You’re not authorised to create event codes."
                    )
                    cur.close()
                    conn.close()
                    return {"status": "unauthorised"}

                event = get_today_event()
                if not event:
                    send_whatsapp_message(
                        from_number,
                        "⚠️ No event configured for today."
                    )
                    cur.close()
                    conn.close()
                    return {"status": "no_event_today"}

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
                    f"🔐 *{event} CODE FOR TODAY*\n\n`{code}`"
                )

                cur.close()
                conn.close()
                return {"status": "code_created"}

            # -----------------------------------------
            # SUBMISSIONS (TIME-BASED)
            # -----------------------------------------
            active_event = get_active_event()
            if not active_event:
                send_whatsapp_message(
                    from_number,
                    "⏱️ Submissions are currently closed."
                )
                cur.close()
                conn.close()
                return {"status": "closed"}

            response = handle_submission(
                conn=conn,
                member=member,
                message=text,
                event=active_event
            )

            send_whatsapp_message(from_number, response)

            cur.close()
            conn.close()

    return {"status": "ok"}