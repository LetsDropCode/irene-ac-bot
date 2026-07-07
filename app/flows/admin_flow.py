from datetime import date

from app.services.admin_service import (
    correct_runner_pb,
    correct_runner_time,
    correct_runner_time_on_date,
    correct_submission_by_id,
    correct_submission_time_by_id,
    get_member_submission_history,
    get_submission_for_admin,
    search_members_for_admin,
)
from app.services.member_service import clear_profile_state, set_profile_state
from app.services.validation import is_valid_time, time_to_seconds
from app.whatsapp import (
    send_admin_confirm_correction_buttons,
    send_admin_edit_field_buttons,
    send_admin_member_center_buttons,
    send_text,
)


def _format_member_lookup(rows, query: str) -> str:
    if not rows:
        return (
            f"🔎 No member found for “{query}”.\n\n"
            "Try FIND plus a first name, surname or phone number."
        )

    msg = f"🔎 *Member lookup: {query}*\n"

    for index, row in enumerate(rows, start=1):
        checked_in = "yes" if row.get("tt_code_verified") else "no"
        status = row.get("today_status") or "none"
        result = "No result today"
        if row.get("today_status") == "COMPLETE":
            distance = row.get("distance_text") or "?"
            result = f"{distance}km — {row.get('time_text')}"
        elif row.get("today_status") == "PENDING":
            result = "Pending result"

        hidden = "yes" if row.get("leaderboard_opt_out") else "no"
        msg += (
            "\n"
            f"{index}. {row['first_name']} {row['last_name']}\n"
            f"Member ID: {row['id']}\n"
            f"Phone: {row['phone']}\n"
            f"Type: {row.get('participation_type') or 'not set'}\n"
            f"Checked in: {checked_in}\n"
            f"Today: {status} · {result}\n"
            f"Hidden from leaderboard: {hidden}\n"
        )

    msg += "\nReply with a number to open that member, or type ADMIN for tools."
    return msg.strip()


def send_member_lookup(sender: str, query: str, admin_member: dict = None):
    rows = search_members_for_admin(query)
    send_text(sender, _format_member_lookup(rows, query))
    if admin_member and rows:
        set_profile_state(admin_member["id"], f"ADMIN_MEMBER_SEARCH|{query}")
    return len(rows)


def _format_member_center(row: dict) -> str:
    checked_in = "yes" if row.get("tt_code_verified") else "no"
    status = row.get("today_status") or "none"
    if row.get("today_status") == "COMPLETE":
        result = _format_result_value(row.get("distance_text"), row.get("time_text"))
    elif row.get("today_status") == "PENDING":
        result = "Pending result"
    else:
        result = "No result today"

    hidden = "yes" if row.get("leaderboard_opt_out") else "no"
    return (
        "*Member command center*\n\n"
        f"{row['first_name']} {row['last_name']}\n"
        f"Member ID: {row['id']}\n"
        f"Phone: {row['phone']}\n"
        f"Type: {row.get('participation_type') or 'not set'}\n"
        f"Checked in today: {checked_in}\n"
        f"Today: {status} · {result}\n"
        f"Hidden from leaderboard: {hidden}\n\n"
        "Choose the next admin action."
    )


def _send_member_center(sender: str, admin_member: dict, row: dict):
    set_profile_state(admin_member["id"], f"ADMIN_MEMBER|{row['id']}")
    body = _format_member_center(row)
    if not send_admin_member_center_buttons(sender, body):
        send_text(
            sender,
            f"{body}\n\nReply HISTORY, CORRECT, or ADMIN.",
        )


def _select_member_from_search(sender: str, admin_member: dict, query: str, text: str):
    rows = search_members_for_admin(query)
    if not text or not text.isdigit():
        send_text(sender, "Reply with the member number from the list, or CANCEL.")
        return {"status": "admin_member_search_await_selection"}

    index = int(text) - 1
    if index < 0 or index >= len(rows):
        send_text(sender, "That number is not in the member list. Reply with a listed number.")
        return {"status": "admin_member_search_bad_selection"}

    selected = rows[index]
    _send_member_center(sender, admin_member, selected)
    return {"status": "admin_member_selected", "member_id": selected["id"]}


def start_admin_correct_flow(sender: str, admin_member: dict):
    if admin_member:
        set_profile_state(admin_member["id"], "ADMIN_FIND_FOR_CORRECT")
    send_text(sender, "Send the member name or phone number to correct, e.g. Lindsay or 2772...")
    return {"status": "admin_correct_find_prompt"}


def send_admin_correct_search(sender: str, admin_member: dict, query: str):
    rows = search_members_for_admin(query)
    send_text(sender, _format_member_lookup(rows, query))
    if admin_member and rows:
        set_profile_state(admin_member["id"], f"ADMIN_MEMBER_SEARCH_FOR_CORRECT|{query}")
    return len(rows)


def _format_submission_history(rows, identifier: str) -> str:
    if not rows:
        return (
            f"No submissions found for {identifier}.\n\n"
            "Use FIND <name> to confirm the member ID or phone."
        )

    first = rows[0]
    msg = (
        f"*Submission history: {first['first_name']} {first['last_name']}*\n"
        f"Member ID: {first['member_id']}\n\n"
    )

    for index, row in enumerate(rows, start=1):
        date_text = row.get("event_date") or "unknown date"
        if row.get("distance_text"):
            result = f"{row['distance_text']}km — {row.get('time_text') or 'no time'}"
        else:
            result = row.get("time_text") or "Workout logged"

        status = row.get("status") or "UNKNOWN"
        msg += f"{index}. {date_text}: {result} ({status})\n"

    msg += "\nReply with a number to select a submission to edit."
    return msg.strip()


def send_submission_history(sender: str, identifier: str):
    rows = get_member_submission_history(identifier)
    send_text(sender, _format_submission_history(rows, identifier))
    return len(rows)


def _admin_state_parts(state: str):
    return (state or "").split("|")


def _format_selected_submission(row: dict) -> str:
    date_text = row.get("event_date") or "unknown date"
    distance = row.get("distance_text") or "?"
    time_text = row.get("time_text") or "none"
    return (
        "*Selected submission*\n\n"
        f"{row['first_name']} {row['last_name']}\n"
        f"Date: {date_text}\n"
        f"Distance: {distance}km\n"
        f"Time: {time_text}\n\n"
        "Reply TIME, DISTANCE, or BOTH. Reply CANCEL to stop."
    )


def _format_result_value(distance, time_text) -> str:
    if distance:
        return f"{distance}km — {time_text}"

    return time_text or "none"


def _format_pending_correction(row: dict, distance: str, time_text: str) -> str:
    date_text = row.get("event_date") or "unknown date"
    old_value = _format_result_value(row.get("distance_text"), row.get("time_text"))
    new_value = _format_result_value(distance, time_text)
    return (
        "*Confirm correction*\n\n"
        f"{row['first_name']} {row['last_name']}\n"
        f"Date: {date_text}\n"
        f"Change: {old_value}\n"
        f"To: {new_value}\n\n"
        "Save this change?"
    )


def _send_admin_edit_field_options(sender: str, row: dict):
    body = _format_selected_submission(row)
    if not send_admin_edit_field_buttons(sender, body):
        send_text(sender, body)


def _send_admin_correction_confirmation(sender: str, row: dict, distance: str, time_text: str):
    body = _format_pending_correction(row, distance, time_text)
    if not send_admin_confirm_correction_buttons(sender, body):
        send_text(sender, f"{body}\n\nReply YES or NO.")


def _format_typed_correction_confirmation(scope: str, identifier: str, event_date: str, distance: str, time_text: str) -> str:
    scope_text = {
        "TODAY": "Tonight's result",
        "DATE": f"Result on {event_date}",
        "PB": "Overall PB result",
    }.get(scope, "Result")

    date_line = f"\nDate: {event_date}" if scope == "DATE" else ""
    return (
        "*Confirm correction*\n\n"
        f"{scope_text}\n"
        f"Member: {identifier}{date_line}\n"
        f"New value: {distance}km — {time_text}\n\n"
        "Save this change?"
    )


def _send_typed_correction_confirmation(sender: str, scope: str, identifier: str, event_date: str, distance: str, time_text: str):
    body = _format_typed_correction_confirmation(scope, identifier, event_date, distance, time_text)
    if not send_admin_confirm_correction_buttons(sender, body):
        send_text(sender, f"{body}\n\nReply YES or NO.")


def _send_typed_correction_not_found(sender: str, scope: str):
    if scope == "DATE":
        send_text(
            sender,
            (
                "I couldn’t find a submission for that member on that date.\n\n"
                "Use HISTORY <member id> to check their submitted dates."
            ),
        )
        return {"status": "admin_correct_date_not_found"}

    if scope == "PB":
        send_text(
            sender,
            (
                "I couldn’t find a season PB result for that member and distance.\n\n"
                "Use FIND <name> to confirm the member ID or phone."
            ),
        )
        return {"status": "admin_correct_pb_not_found"}

    send_text(
        sender,
        (
            "I couldn’t find a checked-in TT submission for that member tonight.\n\n"
            "Use FIND <name> to confirm the member ID or phone."
        ),
    )
    return {"status": "admin_correct_not_found"}


def _save_typed_correction(scope: str, identifier: str, event_date: str, distance: str, time_text: str, admin_member_id: int):
    seconds = time_to_seconds(time_text)
    if scope == "DATE":
        return correct_runner_time_on_date(
            identifier,
            event_date,
            distance,
            time_text,
            seconds,
            admin_member_id,
        )

    if scope == "PB":
        return correct_runner_pb(
            identifier,
            distance,
            time_text,
            seconds,
            admin_member_id,
        )

    return correct_runner_time(
        identifier,
        distance,
        time_text,
        seconds,
        admin_member_id,
    )


def handle_admin_edit_state(sender: str, admin_member: dict, raw_text: str, text: str):
    state = admin_member.get("profile_state") if admin_member else None
    if not state or not state.startswith("ADMIN_"):
        return None

    if text in {"CANCEL", "CANCEL EDIT"}:
        clear_profile_state(admin_member["id"])
        send_text(sender, "Edit cancelled.")
        return {"status": "admin_edit_cancelled"}

    parts = _admin_state_parts(state)
    state_name = parts[0]

    if state_name in {"ADMIN_MEMBER_SEARCH", "ADMIN_MEMBER_SEARCH_FOR_CORRECT"}:
        query = parts[1]
        return _select_member_from_search(sender, admin_member, query, text)

    if state_name == "ADMIN_FIND_FOR_CORRECT":
        if not raw_text:
            send_text(sender, "Send a member name or phone number, or CANCEL.")
            return {"status": "admin_correct_find_await_query"}

        count = send_admin_correct_search(sender, admin_member, raw_text.strip())
        return {"status": "admin_correct_find_results", "count": count}

    if state_name == "ADMIN_MEMBER":
        member_id = parts[1]
        if text == "HISTORY":
            count = send_submission_history(sender, member_id)
            if count:
                set_profile_state(admin_member["id"], f"ADMIN_HISTORY|{member_id}")
            return {"status": "submission_history", "count": count}

        if text in {"CORRECT", "CORRECT RESULT"}:
            count = send_submission_history(sender, member_id)
            if count:
                set_profile_state(admin_member["id"], f"ADMIN_HISTORY|{member_id}")
            return {"status": "admin_correct_history", "count": count}

        send_text(sender, "Choose History, Correct result, or Admin tools.")
        return {"status": "admin_member_await_action"}

    if state_name == "ADMIN_CONFIRM_TYPED":
        scope = parts[1]
        identifier = parts[2]
        event_date = parts[3]
        distance = parts[4]
        time_text = parts[5]

        if text in {"NO", "N"}:
            clear_profile_state(admin_member["id"])
            send_text(sender, "Correction cancelled.")
            return {"status": "admin_correction_cancelled"}

        if text not in {"YES", "Y"}:
            _send_typed_correction_confirmation(sender, scope, identifier, event_date, distance, time_text)
            return {"status": "admin_correction_await_confirm"}

        row = _save_typed_correction(
            scope,
            identifier,
            None if event_date == "-" else event_date,
            distance,
            time_text,
            admin_member["id"],
        )
        if not row:
            clear_profile_state(admin_member["id"])
            return _send_typed_correction_not_found(sender, scope)

        clear_profile_state(admin_member["id"])
        scope_label = "Dated result" if scope == "DATE" else "PB" if scope == "PB" else "Result"
        send_text(sender, _format_correction_result(row, scope_label))
        status = "admin_date_corrected" if scope == "DATE" else "admin_pb_corrected" if scope == "PB" else "admin_corrected"
        return {"status": status, "submission_id": row["id"]}

    if state_name == "ADMIN_HISTORY":
        if not text or not text.isdigit():
            send_text(sender, "Reply with the submission number, e.g. 1, or CANCEL.")
            return {"status": "admin_history_await_selection"}

        identifier = parts[1]
        rows = get_member_submission_history(identifier)
        index = int(text) - 1
        if index < 0 or index >= len(rows):
            send_text(sender, "That number is not in the history list. Reply with a listed number.")
            return {"status": "admin_history_bad_selection"}

        selected = rows[index]
        submission_id = selected["submission_id"]
        set_profile_state(admin_member["id"], f"ADMIN_SELECTED|{submission_id}")
        _send_admin_edit_field_options(sender, selected)
        return {"status": "admin_history_selected", "submission_id": submission_id}

    if state_name == "ADMIN_SELECTED":
        submission_id = int(parts[1])
        row = get_submission_for_admin(submission_id)
        if not row:
            clear_profile_state(admin_member["id"])
            send_text(sender, "I could not find that submission anymore. Start again with HISTORY.")
            return {"status": "admin_selected_missing"}

        if text == "TIME":
            set_profile_state(admin_member["id"], f"ADMIN_EDIT_TIME|{submission_id}")
            send_text(sender, "Send the corrected time, e.g. 27:41.")
            return {"status": "admin_edit_time_prompt"}

        if text == "DISTANCE":
            set_profile_state(admin_member["id"], f"ADMIN_EDIT_DISTANCE|{submission_id}")
            send_text(sender, "Send the corrected distance: 4, 6 or 8.")
            return {"status": "admin_edit_distance_prompt"}

        if text == "BOTH":
            set_profile_state(admin_member["id"], f"ADMIN_EDIT_BOTH|{submission_id}")
            send_text(sender, "Send the corrected distance and time, e.g. 6 42:00.")
            return {"status": "admin_edit_both_prompt"}

        _send_admin_edit_field_options(sender, row)
        return {"status": "admin_selected_await_field"}

    if state_name == "ADMIN_EDIT_TIME":
        submission_id = int(parts[1])
        row = get_submission_for_admin(submission_id)
        if not row:
            clear_profile_state(admin_member["id"])
            send_text(sender, "I could not find that submission anymore. Start again with HISTORY.")
            return {"status": "admin_edit_missing"}

        if not is_valid_time(text):
            send_text(sender, "Time format must be 27:41 or 01:27:41.")
            return {"status": "admin_edit_bad_time"}

        set_profile_state(admin_member["id"], f"ADMIN_CONFIRM_TIME|{submission_id}|{text}")
        _send_admin_correction_confirmation(sender, row, row.get("distance_text"), text)
        return {"status": "admin_correction_confirmation", "submission_id": submission_id}

    if state_name == "ADMIN_CONFIRM_TIME":
        submission_id = int(parts[1])
        time_text = parts[2]

        if text in {"NO", "N"}:
            clear_profile_state(admin_member["id"])
            send_text(sender, "Correction cancelled.")
            return {"status": "admin_correction_cancelled"}

        if text not in {"YES", "Y"}:
            row = get_submission_for_admin(submission_id)
            if row:
                _send_admin_correction_confirmation(sender, row, row.get("distance_text"), time_text)
            else:
                send_text(sender, "Reply YES to save, or NO to cancel.")
            return {"status": "admin_correction_await_confirm"}

        updated = correct_submission_time_by_id(
            submission_id,
            time_text,
            time_to_seconds(time_text),
            admin_member["id"],
        )
        clear_profile_state(admin_member["id"])
        send_text(sender, _format_correction_result(updated, "Submission"))
        return {"status": "admin_submission_corrected", "submission_id": submission_id}

    if state_name == "ADMIN_EDIT_DISTANCE":
        submission_id = int(parts[1])
        row = get_submission_for_admin(submission_id)
        if not row:
            clear_profile_state(admin_member["id"])
            send_text(sender, "I could not find that submission anymore. Start again with HISTORY.")
            return {"status": "admin_edit_missing"}

        distance = text.lower().replace("km", "")
        if distance not in {"4", "6", "8"}:
            send_text(sender, "Distance must be 4, 6 or 8 km.")
            return {"status": "admin_edit_bad_distance"}

        time_text = row.get("time_text")
        if not time_text or not is_valid_time(time_text):
            send_text(sender, "This submission needs a valid time too. Select it again and reply BOTH.")
            set_profile_state(admin_member["id"], f"ADMIN_SELECTED|{submission_id}")
            return {"status": "admin_edit_missing_time"}

        set_profile_state(admin_member["id"], f"ADMIN_CONFIRM|{submission_id}|{distance}|{time_text}")
        _send_admin_correction_confirmation(sender, row, distance, time_text)
        return {"status": "admin_correction_confirmation", "submission_id": submission_id}

    if state_name == "ADMIN_EDIT_BOTH":
        submission_id = int(parts[1])
        parts = (raw_text or "").split()
        if len(parts) != 2:
            send_text(sender, "Send distance and time, e.g. 6 42:00.")
            return {"status": "admin_edit_both_bad_format"}

        distance = parts[0].lower().replace("km", "")
        time_text = parts[1]
        if distance not in {"4", "6", "8"}:
            send_text(sender, "Distance must be 4, 6 or 8 km.")
            return {"status": "admin_edit_bad_distance"}
        if not is_valid_time(time_text):
            send_text(sender, "Time format must be 27:41 or 01:27:41.")
            return {"status": "admin_edit_bad_time"}

        row = get_submission_for_admin(submission_id)
        if not row:
            clear_profile_state(admin_member["id"])
            send_text(sender, "I could not find that submission anymore. Start again with HISTORY.")
            return {"status": "admin_edit_missing"}

        set_profile_state(admin_member["id"], f"ADMIN_CONFIRM|{submission_id}|{distance}|{time_text}")
        _send_admin_correction_confirmation(sender, row, distance, time_text)
        return {"status": "admin_correction_confirmation", "submission_id": submission_id}

    if state_name == "ADMIN_CONFIRM":
        submission_id = int(parts[1])
        distance = parts[2]
        time_text = parts[3]

        if text in {"NO", "N"}:
            clear_profile_state(admin_member["id"])
            send_text(sender, "Correction cancelled.")
            return {"status": "admin_correction_cancelled"}

        if text not in {"YES", "Y"}:
            row = get_submission_for_admin(submission_id)
            if row:
                _send_admin_correction_confirmation(sender, row, distance, time_text)
            else:
                send_text(sender, "Reply YES to save, or NO to cancel.")
            return {"status": "admin_correction_await_confirm"}

        updated = correct_submission_by_id(
            submission_id,
            distance,
            time_text,
            time_to_seconds(time_text),
            admin_member["id"],
        )
        clear_profile_state(admin_member["id"])
        send_text(sender, _format_correction_result(updated, "Submission"))
        return {"status": "admin_submission_corrected", "submission_id": submission_id}

    clear_profile_state(admin_member["id"])
    send_text(sender, "That edit session expired. Start again with HISTORY.")
    return {"status": "admin_edit_unknown_state"}


def clear_admin_edit_state_if_needed(admin_member: dict):
    state = admin_member.get("profile_state") if admin_member else None
    if state and state.startswith("ADMIN_"):
        clear_profile_state(admin_member["id"])
        return True

    return False


def _format_correction_result(row: dict, scope: str = "Result") -> str:
    old_value = _format_result_value(row.get("old_distance_text"), row.get("old_time_text"))
    new_value = _format_result_value(row.get("distance_text"), row.get("time_text"))
    return (
        f"✅ *{scope} corrected*\n\n"
        f"{row['first_name']} {row['last_name']}\n"
        f"Was: {old_value}\n"
        f"Now: {new_value}\n\n"
        "Type ADMIN for tools."
    )


def correct_admin_result(sender: str, raw_text: str, admin_member_id: int = None):
    parts = (raw_text or "").split()
    if len(parts) not in {4, 5, 6}:
        send_text(
            sender,
            (
                "Send corrections as:\n"
                "CORRECT <member id or phone> <4|6|8> <time>\n"
                "CORRECT DATE <member id or phone> <yyyy-mm-dd> <4|6|8> <time>\n"
                "CORRECT PB <member id or phone> <4|6|8> <time>\n\n"
                "Example: CORRECT 42 4 27:41\n"
                "Example: CORRECT DATE 42 2026-06-09 4 27:41\n"
                "Example: CORRECT PB 42 4 27:41\n"
                "Use FIND <name> if you need the member ID."
            ),
        )
        return {"status": "admin_correct_prompt"}

    date_scope = len(parts) == 6 and parts[1].upper() in {"DATE", "ON"}
    pb_scope = len(parts) == 5 and parts[1].upper() in {"PB", "OVERALL", "RANKING"}
    if len(parts) == 6 and not date_scope:
        send_text(sender, "Use CORRECT DATE for date-specific corrections.")
        return {"status": "admin_correct_bad_scope"}
    if len(parts) == 5 and not pb_scope:
        send_text(sender, "Use CORRECT PB for PB corrections, or CORRECT DATE for a specific date.")
        return {"status": "admin_correct_bad_scope"}

    event_date = None
    if date_scope:
        _, _scope, identifier, event_date, distance, time_text = parts
        try:
            date.fromisoformat(event_date)
        except ValueError:
            send_text(sender, "Date format must be yyyy-mm-dd, e.g. 2026-06-09.")
            return {"status": "admin_correct_bad_date"}
    elif pb_scope:
        _, _scope, identifier, distance, time_text = parts
    else:
        _, identifier, distance, time_text = parts

    distance = distance.lower().replace("km", "")

    if distance not in {"4", "6", "8"}:
        send_text(sender, "Distance must be 4, 6 or 8 km.")
        return {"status": "admin_correct_bad_distance"}

    if not is_valid_time(time_text):
        send_text(sender, "Time format must be 27:41 or 01:27:41.")
        return {"status": "admin_correct_bad_time"}

    scope = "DATE" if date_scope else "PB" if pb_scope else "TODAY"
    state_date = event_date if event_date else "-"
    if admin_member_id:
        set_profile_state(
            admin_member_id,
            f"ADMIN_CONFIRM_TYPED|{scope}|{identifier}|{state_date}|{distance}|{time_text}",
        )
    _send_typed_correction_confirmation(sender, scope, identifier, state_date, distance, time_text)
    return {"status": "admin_correct_confirmation"}


