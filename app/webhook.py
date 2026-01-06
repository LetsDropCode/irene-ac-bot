from fastapi import APIRouter, Request
from app.db import get_db
from app.whatsapp import send_whatsapp_message

from app.services.event_detector import get_active_event
from app.services.admin_code_service import generate_code
from app.services.submission_parser import parse_submission
from app.services.submission_service import store_submission
from app.services.submission_gate import set_submission_state

router = APIRouter()

ADMIN_NUMBERS = {
    "27722135094",
    "27738870757",
    "27829370733",
    "27818513864",
}


def get_today_event(cur):
    cur.execute(
        """
        SELECT event, submissions_open
        FROM event_config
        WHERE day_of_week = EXTRACT(DOW FROM CURRENT_DATE)::int
          AND active = 1
        LIMIT 1;
        """
    )
    return cur.fetchone()


@router.post("/webhook")
async def webhook(request: Request):
    payload = await request.json()

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            if "messages" not in value:
                return {"status": "ignored"}

            message = value["messages"][0]
            from_number = message.get("from")
            text = message.get("text", {}).get("body", "").strip()
            text_upper = text.upper().replace("SUBMISSION", "SUBMISSIONS")

            if not from_number or not text:
                return {"status": "invalid"}

            conn = get_db()
            cur = conn.cursor()

            # --------------------------------------------------
            # MEMBER
            # --------------------------------------------------
            cur.execute("SELECT * FROM members WHERE phone=%s;", (from_number,))
            member = cur.fetchone()

            if not member:
                cur.execute(
                    """
                    INSERT INTO members (phone, first_name, last_name, participation_type)
                    VALUES (%s,'Unknown','Member',NULL)
                    RETURNING *;
                    """,
                    (from_number,),
                )
                member = cur.fetchone()
                conn.commit()

                send_whatsapp_message(
                    from_number,
                    "👋 Welcome to the Irene AC bot!\n\n"
                    "How do you participate?\n"
                    "RUNNER / WALKER / BOTH",
                )
                cur.close()
                conn.close()
                return {"status": "new_member"}

            # --------------------------------------------------
            # PARTICIPATION SETUP
            # --------------------------------------------------
            if member["participation_type"] is None:
                if text_upper in {"RUNNER", "WALKER", "BOTH"}:
                    cur.execute(
                        "UPDATE members SET participation_type=%s WHERE id=%s;",
                        (text_upper, member["id"]),
                    )
                    conn.commit()
                    send_whatsapp_message(from_number, f"✅ Set as {text_upper}.")
                else:
                    send_whatsapp_message(
                        from_number,
                        "Please reply with RUNNER, WALKER or BOTH.",
                    )
                cur.close()
                conn.close()
                return {"status": "participation"}

            # --------------------------------------------------
            # ADMIN COMMANDS (TODAY-BASED)
            # --------------------------------------------------
            today = get_today_event(cur)

            if text_upper == "ADD CODE":
                if from_number not in ADMIN_NUMBERS:
                    send_whatsapp_message(from_number, "⛔ Not authorised.")
                elif not today:
                    send_whatsapp_message(from_number, "⚠️ No event scheduled for today.")
                else:
                    code = generate_code()
                    cur.execute(
                        """
                        INSERT INTO event_codes (event, code, event_date)
                        VALUES (%s,%s,CURRENT_DATE);
                        """,
                        (today["event"], code),
                    )
                    conn.commit()
                    send_whatsapp_message(
                        from_number,
                        f"🔐 *{today['event']} CODE FOR TODAY*\n\n{code}",
                    )
                cur.close()
                conn.close()
                return {"status": "add_code"}

            if text_upper in {"OPEN SUBMISSIONS", "CLOSE SUBMISSIONS"}:
                if from_number not in ADMIN_NUMBERS:
                    send_whatsapp_message(from_number, "⛔ Not authorised.")
                elif not today:
                    send_whatsapp_message(from_number, "⚠️ No event scheduled for today.")
                else:
                    open_flag = text_upper == "OPEN SUBMISSIONS"
                    set_submission_state(today["event"], int(open_flag))
                    state = "OPEN" if open_flag else "CLOSED"
                    send_whatsapp_message(
                        from_number,
                        f"{'🟢' if open_flag else '🔴'} *{today['event']} submissions are {state}*",
                    )
                cur.close()
                conn.close()
                return {"status": "admin_submission_toggle"}

            # --------------------------------------------------
            # USER SUBMISSIONS (ACTIVE + GATE)
            # --------------------------------------------------
            active_event = get_active_event()
            if not active_event:
                send_whatsapp_message(from_number, "🕒 Submissions are currently closed.")
                cur.close()
                conn.close()
                return {"status": "inactive"}

            parsed = parse_submission(text)
            if not parsed:
                send_whatsapp_message(
                    from_number,
                    "❌ I couldn’t read that.\n\n"
                    "Examples:\n"
                    "5km 25:30 CODE123\n"
                    "25:30 CODE123 (walkers)",
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
                mode=parsed["mode"],
            )

            send_whatsapp_message(from_number, "✅ Submission received. Lekker! 👏")
            cur.close()
            conn.close()
            return {"status": "submitted"}

    return {"status": "ok"}