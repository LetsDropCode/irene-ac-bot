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
    "27722135094",  # Lindsay
    "27738870757",  # Jacqueline
    "27829370733",  # Wynand
    "27818513864",  # Johan
}


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

            if not from_number or not text:
                return {"status": "invalid"}

            text_upper = (
                text.upper()
                .replace("SUBMISSION", "SUBMISSIONS")
                .replace("ADD CODES", "ADD CODE")
            )

            conn = get_db()
            cur = conn.cursor()

            # --------------------------------------------------
            # MEMBER LOOKUP / CREATE
            # --------------------------------------------------
            cur.execute("SELECT * FROM members WHERE phone = %s;", (from_number,))
            member = cur.fetchone()

            if not member:
                cur.execute(
                    """
                    INSERT INTO members (phone, first_name, last_name, participation_type)
                    VALUES (%s, 'Unknown', NULL, NULL)
                    RETURNING *;
                    """,
                    (from_number,),
                )
                member = cur.fetchone()
                conn.commit()

                send_whatsapp_message(
                    from_number,
                    "👋 Welcome to the Irene AC WhatsApp bot!\n\n"
                    "How do you usually participate?\n\n"
                    "🏃 RUNNER\n"
                    "🚶 WALKER\n"
                    "🏃‍♂️🚶 BOTH",
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
                        (text_upper, member["id"]),
                    )
                    conn.commit()

                    send_whatsapp_message(
                        from_number,
                        "🙌 One last thing before we continue.\n"
                        "Please reply with your *first name and surname*.\n\n"
                        "Example:\nJohn Smith",
                    )
                else:
                    send_whatsapp_message(
                        from_number,
                        "Please reply with:\n🏃 RUNNER\n🚶 WALKER\n🏃‍♂️🚶 BOTH",
                    )

                cur.close()
                conn.close()
                return {"status": "participation_set"}

            # --------------------------------------------------
            # NAME CAPTURE (ONCE ONLY, ADMINS SKIP)
            # --------------------------------------------------
            if (
                from_number not in ADMIN_NUMBERS
                and (member["first_name"] is None or member["first_name"] == "Unknown")
            ):
                parts = text.strip().split()
                if len(parts) >= 2:
                    first_name = parts[0].title()
                    last_name = " ".join(parts[1:]).title()

                    cur.execute(
                        """
                        UPDATE members
                        SET first_name = %s,
                            last_name = %s
                        WHERE id = %s;
                        """,
                        (first_name, last_name, member["id"]),
                    )
                    conn.commit()

                    send_whatsapp_message(
                        from_number,
                        f"✅ Thanks {first_name}! You’re all set.",
                    )
                    cur.close()
                    conn.close()
                    return {"status": "name_saved"}

                send_whatsapp_message(
                    from_number,
                    "🙏 Please reply with your *first name and surname*.\n\n"
                    "Example:\nJohn Smith",
                )
                cur.close()
                conn.close()
                return {"status": "awaiting_name"}

            # --------------------------------------------------
            # ADMIN: ADD CODE (TODAY ONLY)
            # --------------------------------------------------
            if text_upper == "ADD CODE":
                if from_number not in ADMIN_NUMBERS:
                    send_whatsapp_message(from_number, "⛔ Not authorised.")
                    cur.close()
                    conn.close()
                    return {"status": "unauthorised"}

                cur.execute(
                    """
                    SELECT event
                    FROM event_config
                    WHERE day_of_week = EXTRACT(DOW FROM CURRENT_DATE)::int
                      AND active = TRUE
                    LIMIT 1;
                    """
                )
                row = cur.fetchone()

                if not row:
                    send_whatsapp_message(
                        from_number, "⚠️ No event scheduled for today."
                    )
                    cur.close()
                    conn.close()
                    return {"status": "no_event_today"}

                event = row["event"]
                code = generate_code()

                cur.execute(
                    """
                    INSERT INTO event_codes (event, code, event_date)
                    VALUES (%s, %s, CURRENT_DATE);
                    """,
                    (event, code),
                )
                conn.commit()

                send_whatsapp_message(
                    from_number,
                    f"🔐 *{event} CODE FOR TODAY*\n\n{code}",
                )
                cur.close()
                conn.close()
                return {"status": "code_created"}

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
                    send_whatsapp_message(from_number, "⚠️ No active event.")
                    cur.close()
                    conn.close()
                    return {"status": "no_active_event"}

                open_flag = text_upper == "OPEN SUBMISSIONS"

                set_submission_state(event, open_flag)

                send_whatsapp_message(
                    from_number,
                    f"{'🟢' if open_flag else '🔴'} *{event} submissions are "
                    f"{'OPEN' if open_flag else 'CLOSED'}*",
                )
                cur.close()
                conn.close()
                return {"status": "submission_gate_updated"}

            # --------------------------------------------------
            # USER SUBMISSION
            # --------------------------------------------------
            cur.execute(
                """
                SELECT event
                FROM event_config
                WHERE day_of_week = EXTRACT(DOW FROM CURRENT_DATE)::int
                  AND active = TRUE
                LIMIT 1;
                """
            )
            row = cur.fetchone()

            if not row:
                send_whatsapp_message(from_number, "⚠️ No event scheduled for today.")
                cur.close()
                conn.close()
                return {"status": "no_event_today"}

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

            send_whatsapp_message(
                from_number, "✅ Submission received. Lekker run/walk 👏"
            )

            cur.close()
            conn.close()
            return {"status": "submitted"}

    return {"status": "ok"}