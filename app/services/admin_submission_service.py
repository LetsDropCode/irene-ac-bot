"""Admin entry of a missing TT, with attendance and an atomic audit record."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app import config
from app.db import get_cursor
from app.services.admin_service import _record_admin_correction
from app.services.validation import is_valid_time, time_to_seconds


def validate_event_date(value: str) -> date:
    event_date = date.fromisoformat(value)
    if event_date > datetime.now(ZoneInfo("Africa/Johannesburg")).date():
        raise ValueError("Choose today or a past TT date.")
    return event_date


def get_member_for_admin_submission(member_id: int):
    with get_cursor(commit=False) as cur:
        cur.execute("SELECT id, first_name, last_name, popia_acknowledged FROM members WHERE id = %s", (member_id,))
        return cur.fetchone()


def save_admin_submission(sender: str, member_id: int, event_date: str, mode: str,
                          time_text: str, distance: str | None = None):
    if sender not in config.ADMIN_NUMBERS:
        raise PermissionError("Only administrators can add a missed TT.")
    selected_date = validate_event_date(event_date)
    note = (time_text or "").strip()
    if mode == "RUN":
        if distance not in {"4", "6", "8"} or not is_valid_time(note) or time_to_seconds(note) <= 0:
            raise ValueError("Choose 4, 6 or 8 km and a valid non-zero time.")
        seconds = time_to_seconds(note)
    elif mode == "WORKOUT" and note and len(note) <= 500 and distance is None:
        seconds = 0
    else:
        raise ValueError("Enter a workout of 1–500 characters.")

    with get_cursor() as cur:
        cur.execute("SELECT id FROM members WHERE phone = %s", (sender,))
        admin = cur.fetchone()
        if not admin:
            raise PermissionError("Set up your own member profile before adding a TT.")
        # Serialize admin saves with new member check-ins. Row locks also
        # protect an existing draft from a simultaneous member confirmation.
        cur.execute("SELECT id, popia_acknowledged FROM members WHERE id = %s FOR UPDATE", (member_id,))
        member = cur.fetchone()
        if not member or not member["popia_acknowledged"]:
            raise ValueError("The member must have an active consented profile.")
        cur.execute("""
            SELECT * FROM submissions
            WHERE member_id = %s AND event_date = %s AND status != 'CANCELLED'
            ORDER BY id FOR UPDATE
        """, (member_id, selected_date))
        existing = cur.fetchall()
        if any(row["status"] == "COMPLETE" for row in existing):
            return {"status": "exists"}
        if len(existing) > 1 or any(row["activity"] != "TT" for row in existing):
            raise ValueError("This date has conflicting submissions. Review the member history first.")
        old = existing[0] if existing else {}
        if old:
            cur.execute("""
                UPDATE submissions SET mode = %s, distance_text = %s,
                    time_text = %s, seconds = %s, status = 'COMPLETE',
                    confirmed = TRUE, tt_code_verified = TRUE
                WHERE id = %s RETURNING *
            """, (mode, distance, note, seconds, old["id"]))
        else:
            cur.execute("""
                INSERT INTO submissions
                    (member_id, activity, event_date, mode, distance_text,
                     time_text, seconds, status, confirmed, tt_code_verified)
                VALUES (%s, 'TT', %s, %s, %s, %s, %s, 'COMPLETE', TRUE, TRUE)
                RETURNING *
            """, (member_id, selected_date, mode, distance, note, seconds))
        row = cur.fetchone()
        _record_admin_correction(cur, {
            **row,
            "old_distance_text": old.get("distance_text"),
            "old_time_text": old.get("time_text"),
            "old_seconds": old.get("seconds"),
        }, admin["id"], "admin_missing_tt_submission")
        cur.execute("""
            INSERT INTO attendance (member_id, event, event_date, source)
            VALUES (%s, 'TT', %s, 'whatsapp_admin')
            ON CONFLICT (member_id, event, event_date) DO NOTHING
        """, (member_id, selected_date))
        return {"status": "saved", "submission": row}
