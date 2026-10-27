"""Guided, date-specific missed TT entry; drafts live in the admin's state."""

import json
from datetime import datetime
from uuid import uuid4

from app.services.admin_service import search_members_for_admin
from app.services.admin_submission_service import (
    get_member_for_admin_submission, save_admin_submission, validate_event_date,
)
from app.services.member_service import clear_profile_state, set_profile_state
from app.services.validation import is_valid_time, time_to_seconds
from app.whatsapp import send_text, send_admin_submission_buttons, send_admin_date_calendar

PREFIX = "ADMIN_ADD_TT|"
COMMANDS = {"ADMIN SUBMIT", "ADD TT", "ADD MISSED TT"}


def _store(admin, draft):
    set_profile_state(admin["id"], PREFIX + json.dumps(draft, ensure_ascii=False))


def _prompt_date(sender, draft):
    if not send_admin_date_calendar(sender, draft["name"], draft["token"]):
        send_text(sender, f"*Add missed TT: {draft['name']}*\n\nSend the TT date as YYYY-MM-DD or DD/MM/YYYY. Choose today or a past date.\nType CANCEL anytime.")


def _select(sender, admin, draft, member_id):
    member = get_member_for_admin_submission(member_id)
    if not member or not member.get("popia_acknowledged"):
        send_text(sender, "The member must have an active consented profile. Choose another member or CANCEL.")
        return {"status": "admin_add_member_unavailable"}
    draft.update(member_id=member_id, name=f"{member['first_name']} {member['last_name']}"[:100], step="date")
    _store(admin, draft)
    _prompt_date(sender, draft)
    return {"status": "admin_add_date"}


def _review(sender, draft):
    result = f"{draft['distance']} km — {draft['note']}" if draft["mode"] == "RUN" else draft["note"]
    send_admin_submission_buttons(sender,
        f"*Confirm missed TT*\n\nMember: {draft['name']} (ID {draft['member_id']})\n"
        f"Date: {draft['date']}\nType: {'Run' if draft['mode'] == 'RUN' else 'Workout'}\n{result}\n\n"
        "Confirm to save this result and attendance for this date, or cancel.",
        [(f"admin_add_confirm:{draft['token']}", "Confirm"), (f"admin_add_cancel:{draft['token']}", "Cancel")])


def handle_admin_submission(sender, admin, raw_text, button, authorized):
    text = (raw_text or "").strip()
    command = text.upper()
    button_id = (button or {}).get("id", "")
    state = (admin or {}).get("profile_state") or ""
    relevant = command in COMMANDS or button_id.startswith("admin_add_") or state.startswith(PREFIX)
    if not relevant:
        return None
    if not authorized:
        send_text(sender, "Only admins can add a TT on behalf of a member.")
        return {"status": "admin_add_forbidden"}
    if not admin:
        send_text(sender, "Complete your own member profile before adding a missed TT.")
        return {"status": "admin_add_profile_required"}
    if command in COMMANDS or button_id == "admin_add_tt":
        draft = {"step": "search", "token": uuid4().hex}
        if state.startswith("ADMIN_MEMBER|"):
            return _select(sender, admin, draft, int(state.split("|")[1]))
        _store(admin, draft)
        send_text(sender, "*Add missed TT*\n\nSend the member's name or phone number. Type CANCEL anytime.")
        return {"status": "admin_add_search"}
    if not state.startswith(PREFIX):
        send_text(sender, "That add-TT session has ended. Type ADMIN SUBMIT to start again.")
        return {"status": "admin_add_expired"}
    draft = json.loads(state[len(PREFIX):])
    if button_id == "admin_add_calendar":
        if draft["step"] != "date" or button.get("flow_token") != draft["token"]:
            send_text(sender, "That calendar belongs to an earlier entry. Use the latest calendar, or type CANCEL.")
            return {"status": "admin_add_stale_calendar"}
        value = button.get("event_date")
        text = value if isinstance(value, str) else ""
    if command in {"CANCEL", "CANCEL EDIT"} or button_id == f"admin_add_cancel:{draft['token']}":
        clear_profile_state(admin["id"])
        send_text(sender, "Missed TT entry cancelled. No result was changed.")
        return {"status": "admin_add_cancelled"}
    if button_id and button_id not in {
        "admin_add_run", "admin_add_workout", "admin_add_calendar", f"admin_add_confirm:{draft['token']}"
    }:
        send_text(sender, "Use the latest prompts for this entry, or type CANCEL.")
        return {"status": "admin_add_stale_button"}
    step = draft["step"]
    if step == "search":
        rows = search_members_for_admin(text) if text else []
        if not rows:
            send_text(sender, "No members found. Send another name or phone number, or CANCEL.")
            return {"status": "admin_add_search_empty"}
        draft.update(step="member", candidates=[row["id"] for row in rows])
        _store(admin, draft)
        send_text(sender, "Choose the member by replying with a number:\n\n" + "\n".join(
            f"{i}. {row['first_name']} {row['last_name']} (ID {row['id']}, {row['phone']})"
            for i, row in enumerate(rows, 1)))
        return {"status": "admin_add_choose_member"}
    if step == "member":
        if not text.isdigit() or not 1 <= int(text) <= len(draft["candidates"]):
            send_text(sender, "Reply with a member number from the list, or CANCEL.")
            return {"status": "admin_add_bad_member"}
        return _select(sender, admin, draft, draft["candidates"][int(text) - 1])
    if step == "date":
        if command == "CALENDAR":
            _prompt_date(sender, draft)
            return {"status": "admin_add_date"}
        try:
            value = datetime.strptime(text, "%d/%m/%Y" if "/" in text else "%Y-%m-%d").date().isoformat()
            validate_event_date(value)
        except ValueError:
            send_text(sender, "Send a valid date, today or earlier, as YYYY-MM-DD or DD/MM/YYYY.")
            return {"status": "admin_add_bad_date"}
        draft.update(date=value, step="mode")
        _store(admin, draft)
        send_admin_submission_buttons(sender, "Choose the result type for this TT date.",
                                      [("admin_add_run", "Run"), ("admin_add_workout", "Workout")])
        return {"status": "admin_add_mode"}
    if step == "mode":
        choice = button_id or command
        if choice not in {"admin_add_run", "admin_add_workout", "RUN", "WORKOUT"}:
            send_text(sender, "Choose Run or Workout, or type CANCEL.")
            return {"status": "admin_add_bad_mode"}
        draft.update(mode="RUN" if choice in {"admin_add_run", "RUN"} else "WORKOUT")
        draft["step"] = "distance" if draft["mode"] == "RUN" else "workout"
        _store(admin, draft)
        send_text(sender, "Send the distance: 4, 6 or 8 km." if draft["mode"] == "RUN" else "Type the workout in free text (up to 500 characters).")
        return {"status": "admin_add_" + draft["step"]}
    if step == "distance":
        distance = command.removesuffix("KM").strip()
        if distance not in {"4", "6", "8"}:
            send_text(sender, "Choose 4, 6 or 8 km.")
            return {"status": "admin_add_bad_distance"}
        draft.update(distance=distance, step="time")
        _store(admin, draft)
        send_text(sender, "Send the finish time, e.g. 27:41 or 01:27:41.")
        return {"status": "admin_add_time"}
    if step in {"time", "workout"}:
        valid = (is_valid_time(text) and time_to_seconds(text) > 0) if step == "time" else bool(text) and len(text) <= 500
        if not valid:
            send_text(sender, "Send a valid non-zero time, e.g. 27:41." if step == "time" else "Send a workout of 1–500 characters.")
            return {"status": "admin_add_bad_result"}
        draft.update(note=text, step="confirm")
        _store(admin, draft)
        _review(sender, draft)
        return {"status": "admin_add_review"}
    if step == "confirm":
        if button_id != f"admin_add_confirm:{draft['token']}":
            _review(sender, draft)
            return {"status": "admin_add_review"}
        try:
            result = save_admin_submission(sender, draft["member_id"], draft["date"], draft["mode"], draft["note"], draft.get("distance"))
        except (ValueError, PermissionError) as exc:
            clear_profile_state(admin["id"])
            send_text(sender, str(exc) + " Type ADMIN SUBMIT to start again.")
            return {"status": "admin_add_rejected"}
        clear_profile_state(admin["id"])
        if result["status"] == "exists":
            send_text(sender, f"A completed TT already exists for {draft['name']} on {draft['date']}. Use Find member → Correct result to change it.")
            return {"status": "admin_add_exists"}
        send_text(sender, f"✅ TT saved for {draft['name']} on {draft['date']}. Attendance recorded for that date. Type ADMIN for tools.")
        return {"status": "admin_add_saved", "submission_id": result["submission"]["id"]}
    clear_profile_state(admin["id"])
    send_text(sender, "That session expired. Type ADMIN SUBMIT to start again.")
    return {"status": "admin_add_expired"}
