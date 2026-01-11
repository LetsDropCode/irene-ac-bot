from datetime import datetime, time
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Request

from app.db import get_db
from app.whatsapp import send_whatsapp_message, send_whatsapp_buttons
from app.services.openai_service import coach_reply
from app.services.submission_parser import parse_time_only
from app.services.submission_service import (
    store_submission,
    confirm_submission,
)

router = APIRouter()

TZ = ZoneInfo("Africa/Johannesburg")
TT_START = time(16, 30)
TT_END = time(22, 30)

DISTANCE_BUTTONS = [
    {"id": "DIST_4", "title": "4 km"},
    {"id": "DIST_6", "title": "6 km"},
    {"id": "DIST_8", "title": "8 km"},
]

EDIT_CONFIRM_BUTTONS = [
    {"id": "EDIT_TIME", "title": "✏️ Edit time"},
    {"id": "CONFIRM_TT", "title": "✅ Confirm"},
]


def in_tt_window() -> bool:
    now = datetime.now(TZ).time()
    return TT_START <= now <= TT_END


@router.post("/webhook")
async def webhook(request: Request):
    payload = await request.json()

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            if "messages" not in value:
                return {"status": "ignored"}

            msg = value["messages"][0]
            from_number = msg.get("from")

            text = msg.get("text", {}).get("body", "").strip()
            button_id = (
                msg.get("interactive", {})
                .get("button_reply", {})
                .get("id")
            )

            conn = get_db()
            cur = conn.cursor()

            # ==================================================
            # MEMBER LOOKUP / CREATE
            # ==================================================
            cur.execute("SELECT * FROM members WHERE phone = %s;", (from_number,))
            member = cur.fetchone()

            if not member:
                cur.execute(
                    """
                    INSERT INTO members (phone, first_name, last_name, participation_type)
                    VALUES (%s, NULL, NULL, 'RUNNER')
                    RETURNING *;
                    """,
                    (from_number,),
                )
                member = cur.fetchone()
                conn.commit()

                send_whatsapp_message(
                    from_number,
                    coach_reply(
                        "Welcome the member and politely ask for their first name and surname."
                    ),
                )
                cur.close()
                conn.close()
                return {"status": "ask_name"}

            # ==================================================
            # NAME & SURNAME CAPTURE
            # ==================================================
            if not member["first_name"] or not member["last_name"]:
                parts = text.split()
                if len(parts) >= 2:
                    cur.execute(
                        """
                        UPDATE members
                        SET first_name = %s,
                            last_name = %s
                        WHERE id = %s;
                        """,
                        (parts[0], " ".join(parts[1:]), member["id"]),
                    )
                    conn.commit()

                    send_whatsapp_message(
                        from_number,
                        coach_reply(
                            "Confirm registration and explain how to submit a TT."
                        ),
                    )

                    send_whatsapp_buttons(
                        from_number,
                        "How far did you run tonight?",
                        DISTANCE_BUTTONS,
                    )

                    cur.close()
                    conn.close()
                    return {"status": "name_saved"}

                send_whatsapp_message(
                    from_number,
                    "Please reply with *First name and Surname* 🙂",
                )
                cur.close()
                conn.close()
                return {"status": "await_name"}

            # ==================================================
            # VIEW PROGRESS
            # ==================================================
            if text.upper() in {"MY PROGRESS", "PROGRESS"}:
                cur.execute(
                    """
                    SELECT distance_text, time_text, created_at
                    FROM submissions
                    WHERE member_id = %s
                    ORDER BY created_at DESC
                    LIMIT 5;
                    """,
                    (member["id"],),
                )
                rows = cur.fetchall()

                if not rows:
                    send_whatsapp_message(
                        from_number,
                        "No TT history yet — let’s change that 💪",
                    )
                else:
                    history = "\n".join(
                        f"{r['created_at'].date()} — {r['distance_text']} in {r['time_text']}"
                        for r in rows
                    )
                    send_whatsapp_message(
                        from_number,
                        f"📊 *Your recent TT results:*\n\n{history}",
                    )

                cur.close()
                conn.close()
                return {"status": "progress"}

            # ==================================================
            # DISTANCE BUTTONS
            # ==================================================
            if button_id in {"DIST_4", "DIST_6", "DIST_8"}:
                distance = button_id.replace("DIST_", "") + "km"

                cur.execute(
                    """
                    UPDATE members
                    SET pending_distance = %s
                    WHERE id = %s;
                    """,
                    (distance, member["id"]),
                )
                conn.commit()

                send_whatsapp_message(
                    from_number,
                    coach_reply("Ask the runner for their time in a friendly coach tone."),
                )

                cur.close()
                conn.close()
                return {"status": "await_time"}

            # ==================================================
            # EDIT / CONFIRM BUTTONS
            # ==================================================
            if button_id == "EDIT_TIME":
                send_whatsapp_message(
                    from_number,
                    coach_reply("No stress — send your corrected time."),
                )
                cur.close()
                conn.close()
                return {"status": "edit_time"}

            if button_id == "CONFIRM_TT":
                confirm_submission(member["id"])

                send_whatsapp_message(
                    from_number,
                    coach_reply(
                        "All locked in ✅ Great effort tonight — recover well 👊"
                    ),
                )

                cur.close()
                conn.close()
                return {"status": "confirmed"}

            # ==================================================
            # TT WINDOW ENFORCEMENT
            # ==================================================
            if not in_tt_window():
                send_whatsapp_message(
                    from_number,
                    "⏱️ TT submissions are open from *16:30 to 22:30* only.",
                )
                cur.close()
                conn.close()
                return {"status": "closed"}

            # ==================================================
            # TIME SUBMISSION
            # ==================================================
            parsed = parse_time_only(text)
            if not parsed:
                send_whatsapp_message(
                    from_number,
                    "Please send your *time only* (e.g. 27:41).",
                )
                cur.close()
                conn.close()
                return {"status": "bad_time"}

            distance = member.get("pending_distance")
            if not distance:
                send_whatsapp_buttons(
                    from_number,
                    "Please select your distance first:",
                    DISTANCE_BUTTONS,
                )
                cur.close()
                conn.close()
                return {"status": "need_distance"}

            action = store_submission(
                member_id=member["id"],
                activity="TT",
                distance_text=distance,
                time_text=parsed["time"],
                seconds=parsed["seconds"],
            )

            if action == "locked":
                send_whatsapp_message(
                    from_number,
                    "🔒 Your TT is already confirmed and locked.",
                )
                cur.close()
                conn.close()
                return {"status": "locked"}

            send_whatsapp_buttons(
                from_number,
                coach_reply(
                    f"{distance} in {parsed['time']} 💪\n\n"
                    "Want to confirm or edit?"
                ),
                EDIT_CONFIRM_BUTTONS,
            )

            cur.close()
            conn.close()
            return {"status": action}

    return {"status": "ok"}