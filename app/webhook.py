import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app.config import ADMIN_NUMBERS, ENV, WHATSAPP_APP_SECRET, WHATS_NEW_MESSAGE, WHATS_NEW_VERSION
from app.flows.admin_flow import (
    clear_admin_edit_state_if_needed,
    correct_admin_result,
    handle_admin_edit_state,
    send_member_lookup,
    send_submission_history,
    start_admin_correct_flow,
)
from app.flows.help_flow import (
    format_help_menu,
    is_help_command,
    resolve_interactive_action,
    resolve_menu_action,
)
from app.flows.submission_state import (
    AWAITING_BOTH_CHOICE,
    AWAITING_CONFIRM,
    AWAITING_DISTANCE,
    AWAITING_TIME,
    AWAITING_WORKOUT,
    resolve_pending_submission_state,
)
from app.whatsapp import (
    send_text,
    send_distance_buttons,
    send_confirm_buttons,
    send_participation_buttons,
    send_profile_buttons,
    send_both_submission_buttons,
    send_main_menu_list,
    send_leaderboard_menu_list,
    send_admin_menu_list,
    send_admin_pending_actions,
)

from app.services.event_code_service import generate_tt_code
from app.services.member_service import (
    get_member,
    create_member,
    save_member_name,
    save_participation_type,
    set_profile_state,
    clear_profile_state,
    acknowledge_popia,
    opt_out_leaderboard,
    has_seen_whats_new,
    mark_whats_new_seen,
)

from app.services.submission_service import (
    get_or_create_submission,
    get_pending_members,
    get_tonight_unprompted_checked_in_members,
    verify_tt_code,
    save_distance,
    save_time,
    confirm_submission,
    release_pending_submissions,
    reopen_submission_for_edit,
)

from app.services.attendance_service import mark_attendance
from app.services.validation import is_valid_time, is_valid_tt_code, time_to_seconds
from app.services.submission_gate import ensure_tt_open
from app.services.idempotency_service import (
    mark_inbound_message_processed,
    register_inbound_message,
)
from app.services.job_queue_service import (
    enqueue_post_confirm_messages,
    get_failed_jobs,
    get_queue_health,
    retry_failed_jobs,
    run_due_jobs,
)
from app.services.pb_service import get_previous_best
from app.services.leaderboard_service import get_runner_leaderboard
from app.services.leaderboard_service import get_overall_leaderboard
from app.services.leaderboard_service import get_member_rankings
from app.services.leaderboard_service import get_walker_feed
from app.services.leaderboard_formatter import format_overall_leaderboard
from app.services.leaderboard_formatter import format_member_rankings
from app.services.leaderboard_formatter import format_full_leaderboard
from app.services.tt_status_service import get_tt_status
from app.services.admin_service import get_admin_dashboard
from app.services.openai_service import coach_reply
from app.services.profile_service import get_user_profile
from app.services.profile_formatter import format_profile
from app.services.progress_formatter import format_progress

router = APIRouter()
logger = logging.getLogger(__name__)

IRENE_SHOP_URL = "https://store126837536.shop.netcash.co.za/products"
IRENE_LEAGUE_URL = "https://iac-league-web.onrender.com"


def is_admin(sender: str) -> bool:
    return sender in ADMIN_NUMBERS


def _mask_phone(value: str | None) -> str:
    if not value:
        return "unknown"
    if len(value) <= 4:
        return "****"
    return f"***{value[-4:]}"


def verify_webhook_signature(raw_body: bytes, signature_header: str | None) -> bool:
    if not WHATSAPP_APP_SECRET:
        return ENV == "development"

    if not signature_header or not signature_header.startswith("sha256="):
        return False

    expected = hmac.new(
        WHATSAPP_APP_SECRET.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    received = signature_header.split("=", 1)[1]
    return hmac.compare_digest(f"sha256={expected}", f"sha256={received}")


def send_help_menu(sender: str, admin: bool = False):
    if not send_main_menu_list(sender, admin):
        send_text(sender, format_help_menu(admin))


def send_leaderboards_menu(sender: str):
    if not send_leaderboard_menu_list(sender):
        send_text(
            sender,
            (
                "🏆 *Leaderboards*\n\n"
                "Reply with:\n"
                "Tonight leaderboard\n"
                "Overall PBs\n"
                "My ranking\n\n"
                "Type MENU to go back."
            ),
        )


def send_admin_tools_menu(sender: str):
    if not send_admin_menu_list(sender):
        send_text(
            sender,
            (
                "🔐 *Admin tools*\n\n"
                "Reply with:\n"
                "TT CODE\n"
                "TT STATUS\n"
                "PENDING\n"
                "CORRECT <member id or phone> <4|6|8> <time>\n"
                "RECOVER TONIGHT\n"
                "TONIGHT LEADERBOARD\n"
                "OVERALL PBs\n\n"
                "Type MENU to go back."
            ),
        )


def _format_admin_dashboard(data: dict, code: str) -> str:
    summary = data.get("summary") or {}
    pending = data.get("pending") or []
    last_submission = summary.get("last_submission_at")
    if last_submission:
        last_submission = last_submission.strftime("%H:%M")
    else:
        last_submission = "none yet"

    pending_names = "None"
    if pending:
        pending_names = ", ".join(
            f"{row['first_name']} {row['last_name']}"
            for row in pending
        )

    return (
        "📋 *Admin Dashboard*\n\n"
        f"TT code: *{code}*\n"
        f"Checked in: {summary.get('checked_in') or 0}\n"
        f"Submitted: {summary.get('submitted') or 0}\n"
        f"Pending: {summary.get('pending') or 0}\n"
        f"Runners / Walkers / Both: "
        f"{summary.get('runners') or 0} / "
        f"{summary.get('walkers') or 0} / "
        f"{summary.get('both') or 0}\n"
        f"Last submission: {last_submission}\n\n"
        f"Top pending: {pending_names}"
    )


def send_admin_dashboard(sender: str):
    code = generate_tt_code("TT")
    data = get_admin_dashboard()
    send_text(sender, _format_admin_dashboard(data, code))


def send_admin_code(sender: str):
    code = generate_tt_code("TT")
    send_text(sender, f"🔐 Tonight’s TT Code\n\n*{code}*\n\nType ADMIN for tools.")


def _format_queue_status(queue: dict) -> str:
    return (
        "🧰 *Job Queue Status*\n\n"
        f"Pending: {queue.get('pending_jobs') or 0}\n"
        f"Running: {queue.get('running_jobs') or 0}\n"
        f"Failed: {queue.get('failed_jobs') or 0}\n"
        f"Done: {queue.get('done_jobs') or 0}\n"
        f"Oldest pending: {queue.get('oldest_pending_seconds') or 0}s\n\n"
        "Commands: JOBS RUN, JOBS FAILED, JOBS RETRY"
    )


def send_jobs_status(sender: str):
    send_text(sender, _format_queue_status(get_queue_health()))


def send_failed_jobs(sender: str):
    rows = get_failed_jobs()

    if not rows:
        send_text(sender, "✅ No failed jobs.\n\nType JOBS STATUS for queue health.")
        return 0

    lines = ["⚠️ *Failed Jobs*"]
    for row in rows:
        error = (row.get("last_error") or "No error recorded").splitlines()[0]
        if len(error) > 80:
            error = f"{error[:77]}..."
        lines.append(
            f"#{row['id']} {row['job_type']} "
            f"({row['attempts']}/{row['max_attempts']}) - {error}"
        )

    lines.extend(["", "Type JOBS RETRY to retry failed jobs."])
    send_text(sender, "\n".join(lines))
    return len(rows)


def run_jobs_from_admin(sender: str):
    processed = run_due_jobs()
    queue = get_queue_health()
    send_text(
        sender,
        (
            f"✅ Job runner processed {processed} job(s).\n\n"
            f"{_format_queue_status(queue)}"
        ),
    )
    return processed


def retry_jobs_from_admin(sender: str):
    retried = retry_failed_jobs()
    send_text(
        sender,
        (
            f"🔁 Retried {retried} failed job(s).\n\n"
            "Type JOBS RUN to process them now, or JOBS STATUS to check the queue."
        ),
    )
    return retried


def send_pending_members(sender: str):
    rows = get_pending_members()

    if not rows:
        send_admin_pending_actions(
            sender,
            "✅ No pending submissions.\n\nChoose a next step:",
        )
        return 0

    msg = "⏳ *Pending Submissions*\n\n"

    for r in rows:
        msg += f"{r['first_name']} {r['last_name']} ({r['phone']})\n"

    msg += "\nChoose a next step:"
    if not send_admin_pending_actions(sender, msg):
        send_text(sender, f"{msg}\n\nType RECOVER TONIGHT to resend prompts, or ADMIN for tools.")
    return len(rows)


def recover_tonight(sender: str):
    rows = get_tonight_unprompted_checked_in_members()

    if not rows:
        send_text(sender, "✅ No checked-in users need a prompt resend.\n\nType ADMIN for tools.")
        return 0

    counts = {"WALKER": 0, "BOTH": 0, "RUNNER": 0}
    for row in rows:
        ptype = row.get("participation_type") or "RUNNER"
        send_submission_prompt(row["phone"], ptype)
        counts[ptype if ptype in counts else "RUNNER"] += 1

    send_text(
        sender,
        (
            "✅ Resent tonight’s submission prompts.\n\n"
            f"🏃 Distance: {counts['RUNNER']}\n"
            f"🚶 Workout: {counts['WALKER']}\n"
            f"🔄 Both choice: {counts['BOTH']}\n\n"
            "Type ADMIN for tools."
        ),
    )
    return len(rows)


def send_user_profile(sender: str, member: dict):
    data = get_user_profile(member["id"])
    send_profile_buttons(sender, format_profile(member, data))


def send_user_progress(sender: str, member: dict):
    data = get_user_profile(member["id"])
    send_text(sender, f"{format_progress(member, data)}\n\nType MENU to go back.")


def send_irene_shop(sender: str):
    send_text(
        sender,
        (
            "🛍️ *The Irene Shop*\n\n"
            "Browse Irene AC gear and products here:\n"
            f"{IRENE_SHOP_URL}\n\n"
            "Type MENU to go back."
        ),
    )


def send_irene_league_standings(sender: str):
    send_text(
        sender,
        (
            "🏆 *The Irene League Standings*\n\n"
            "View the latest Irene League standings here:\n"
            f"{IRENE_LEAGUE_URL}\n\n"
            "Type MENU to go back."
        ),
    )


def send_tonight_leaderboard(sender: str):
    runners = get_runner_leaderboard()
    walkers = get_walker_feed()
    send_text(sender, f"{format_full_leaderboard(runners, walkers)}\n\nType MENU to go back.")


def send_overall_leaderboard(sender: str, member_id=None):
    rows = get_overall_leaderboard(member_id)
    send_text(sender, f"{format_overall_leaderboard(rows, member_id)}\n\nType MENU to go back.")


def send_my_ranking(sender: str, member: dict):
    rows = get_member_rankings(member["id"])
    send_text(sender, format_member_rankings(member, rows))


def send_submission_prompt(sender: str, participation_type: str):
    if participation_type == "WALKER":
        send_text(sender, "🚶 Describe your workout.")
        return "walk"

    if participation_type == "BOTH":
        send_both_submission_buttons(sender)
        return "both_choice"

    send_distance_buttons(sender)
    return "distance"


def resume_submission(sender: str, member: dict, submission: dict):
    if submission["status"] == "COMPLETE":
        send_text(
            sender,
            (
                "You’ve already submitted today’s TT.\n\n"
                f"{submission['distance_text']}km — {submission['time_text']}\n\n"
                "Type FIX RESULT to change it, or MENU to go back."
            ),
        )
        return "complete"

    if not submission.get("tt_code_verified"):
        send_text(sender, "🔑 Send tonight's TT code to check in, or type MENU to go back.")
        return "await_code"

    return prompt_for_pending_submission(sender, member, submission)


def start_fix_result(sender: str, submission: dict):
    if not submission.get("tt_code_verified"):
        send_text(sender, "I don’t have a result to fix yet. Send tonight’s TT code to start.")
        return submission

    updated = reopen_submission_for_edit(submission["id"])
    send_text(sender, "No problem. Let’s fix your result from the start.")
    send_distance_buttons(sender)
    return updated


def send_whats_new_once(sender: str, member: dict):
    if has_seen_whats_new(member, WHATS_NEW_VERSION):
        return False

    send_text(sender, WHATS_NEW_MESSAGE)
    mark_whats_new_seen(member["id"], WHATS_NEW_VERSION)
    return True


def prompt_for_pending_submission(sender: str, member: dict, submission: dict):
    state = resolve_pending_submission_state(member, submission)

    if state == AWAITING_WORKOUT:
        send_text(sender, "🚶 Describe your workout.")
        return state

    if state == AWAITING_BOTH_CHOICE:
        send_both_submission_buttons(sender)
        return state

    if state == AWAITING_DISTANCE:
        send_distance_buttons(sender)
        return state

    if state == AWAITING_TIME:
        send_text(sender, "⏱ Send your time, for example 27:41 or 01:27:41.")
        return state

    if state == AWAITING_CONFIRM:
        send_confirm_buttons(
            sender,
            submission["distance_text"],
            submission["time_text"]
        )
        return state

    # Defensive fallback if new states are introduced without a prompt handler.
    send_confirm_buttons(
        sender,
        submission["distance_text"],
        submission["time_text"]
    )
    return AWAITING_CONFIRM


def _format_improvement(seconds: int) -> str:
    mins = seconds // 60
    secs = seconds % 60
    return f"{mins}:{secs:02d}"


def _find_runner_position(rows, member_id: int, distance: str):
    for row in rows:
        if row.get("member_id") == member_id and row.get("distance_text") == distance:
            return row.get("position")

    return None


def _milestone_lines(total_runs: int, previous_best, submission: dict):
    lines = []

    if total_runs == 1:
        lines.append("🎉 Milestone: first TT logged")
    elif total_runs in {5, 10, 25, 50, 100}:
        lines.append(f"🎉 Milestone: {total_runs} TTs logged")

    if previous_best is None:
        lines.append(f"🥇 Badge: first {submission['distance_text']}km result")
    elif submission["seconds"] < previous_best:
        lines.append(f"🥇 Badge: {submission['distance_text']}km PB")

    return lines


def send_post_confirm_messages(sender: str, member: dict, submission: dict, previous_best):
    first_name = member.get("first_name") or "Runner"
    profile = {"total_runs": None, "recent": []}
    pace = None

    try:
        from app.services.insight_services import seconds_to_pace

        if submission.get("seconds"):
            pace = seconds_to_pace(
                submission["seconds"],
                submission["distance_text"]
            )
    except Exception as e:
        logger.exception("Pace calculation failed: %s", e)

    try:
        profile = get_user_profile(member["id"])
    except Exception as e:
        logger.exception("Profile summary failed: %s", e)

    lines = [
        f"*{first_name}, here’s your TT recap*",
        "",
        f"{submission['distance_text']}km — {submission['time_text']}",
    ]

    if pace:
        lines.append(f"Pace: {pace}")

    if previous_best is None:
        lines.append(f"🚀 First {submission['distance_text']}km PB")
    elif submission["seconds"] < previous_best:
        diff = previous_best - submission["seconds"]
        lines.append(f"🚀 PB by {_format_improvement(diff)}")

    if profile.get("total_runs"):
        lines.append(f"Season TTs: {profile['total_runs']}")

    rows = get_runner_leaderboard()
    position = _find_runner_position(
        rows,
        member["id"],
        submission["distance_text"],
    )
    if position:
        lines.append(f"🏆 Position: {position}")

    lines.extend(
        _milestone_lines(
            profile.get("total_runs") or 0,
            previous_best,
            submission,
        )
    )

    try:
        if submission.get("seconds"):

            from app.services.insight_services import (
                detect_trend,
                detect_fatigue,
            )

            trend = detect_trend(profile["recent"])
            fatigue = detect_fatigue(profile["recent"])

            prompt = (
                f"{member['first_name']} ran {submission['distance_text']}km in {submission['time_text']} "
                f"(pace {pace}). Trend: {trend}. "
            )

            if fatigue:
                prompt += f"{fatigue}. "

            prompt += "Give short coaching feedback."

            insight = coach_reply(prompt)

            if insight:
                lines.extend(["", f"🧠 Coach: {insight}"])

    except Exception as e:
        logger.exception("Insight engine failed: %s", e)

    lines.extend(["", "Type MENU to go back."])
    send_text(sender, "\n".join(lines))


def extract_whatsapp_message(payload: dict):
    try:
        entry = payload.get("entry", [{}])[0]
        change = entry.get("changes", [{}])[0]
        value = change.get("value", {})

        messages = value.get("messages")
        if not messages:
            return None, None, None, None

        msg = messages[0]
        message_id = msg.get("id")
        sender = msg.get("from")

        text = None
        button = None

        if msg.get("type") == "text":
            text = msg.get("text", {}).get("body", "").strip()

        elif msg.get("type") == "interactive":
            interactive = msg.get("interactive", {})
            button = interactive.get("button_reply") or interactive.get("list_reply")

        message_kind = "button" if button else "text" if text else "unknown"
        button_id = button.get("id") if button else None
        logger.info(
            "Incoming WhatsApp message: id=%s from=%s kind=%s button_id=%s",
            message_id or "none",
            _mask_phone(sender),
            message_kind,
            button_id,
        )
        return message_id, sender, text, button

    except Exception as e:
        logger.exception("WhatsApp extractor error: %s", e)
        return None, None, None, None


def process_webhook_payload(payload: dict, background_tasks: BackgroundTasks):
    message_id, sender, text, button = extract_whatsapp_message(payload)

    if not sender or (not text and not button):
        return {"status": "ignored"}

    if message_id and not register_inbound_message(message_id, sender):
        logger.info(
            "Duplicate WhatsApp message ignored: id=%s from=%s",
            message_id,
            _mask_phone(sender),
        )
        return {"status": "duplicate"}

    try:
        result = _process_webhook_message(
            sender,
            text,
            button,
            background_tasks,
        )
    except Exception as exc:
        if message_id:
            mark_inbound_message_processed(message_id, "FAILED", str(exc))
        raise

    if message_id:
        mark_inbound_message_processed(message_id, "PROCESSED")
    return result


def _process_webhook_message(sender: str, text: str | None, button: dict | None, background_tasks: BackgroundTasks):
    raw_text = text.strip() if text else None
    if text:
        text = raw_text.upper()

    if is_admin(sender) and text == "MENU":
        admin_member = get_member(sender)
        clear_admin_edit_state_if_needed(admin_member)
        send_help_menu(sender, True)
        return {"status": "help"}

    if is_help_command(text):
        send_help_menu(sender, is_admin(sender))
        return {"status": "help"}

    menu_action = resolve_menu_action(text) if text else None
    if button:
        menu_action = resolve_interactive_action(button.get("id", "")) or menu_action

    if button and button.get("id", "").lower().strip() == "back_menu":
        if is_admin(sender):
            clear_admin_edit_state_if_needed(get_member(sender))
        send_help_menu(sender, is_admin(sender))
        return {"status": "menu"}

    # ───────── ADMIN ─────────
    if is_admin(sender):
        admin_member = get_member(sender)
        admin_state_text = text
        admin_state_raw_text = raw_text

        if button:
            admin_button_id = button.get("id", "").lower().strip()
            admin_button_text = {
                "admin_edit_time": "TIME",
                "admin_edit_distance": "DISTANCE",
                "admin_edit_both": "BOTH",
                "admin_confirm_correction": "YES",
                "admin_cancel_correction": "NO",
                "admin_member_history": "HISTORY",
                "admin_member_correct": "CORRECT",
            }.get(admin_button_id)
            if admin_button_text:
                admin_state_text = admin_button_text
                admin_state_raw_text = admin_button_text

        if text and text.startswith("CORRECT "):
            return correct_admin_result(
                sender,
                raw_text,
                admin_member["id"] if admin_member else None,
            )

        if text and any(text.startswith(prefix) for prefix in ("FIND ", "LOOKUP ", "SEARCH ")):
            query = raw_text.split(" ", 1)[1].strip()
            count = send_member_lookup(sender, query, admin_member)
            return {"status": "member_lookup", "count": count}

        if text and any(text.startswith(prefix) for prefix in ("HISTORY ", "TIMES ")):
            identifier = raw_text.split(" ", 1)[1].strip()
            count = send_submission_history(sender, identifier)
            if admin_member and count:
                set_profile_state(admin_member["id"], f"ADMIN_HISTORY|{identifier}")
            return {"status": "submission_history", "count": count}

        if menu_action == "ADMIN_MENU":
            clear_admin_edit_state_if_needed(admin_member)
            send_admin_dashboard(sender)
            send_admin_tools_menu(sender)
            return {"status": "admin_menu"}

        state_result = handle_admin_edit_state(
            sender,
            admin_member,
            admin_state_raw_text,
            admin_state_text,
        )
        if state_result:
            return state_result

        if menu_action == "ADMIN_FIND":
            send_text(
                sender,
                (
                    "Send FIND plus a name or phone number, e.g. FIND Lindsay.\n"
                    "Then reply with the number to open that member."
                ),
            )
            return {"status": "member_lookup_prompt"}

        if menu_action == "ADMIN_HISTORY":
            send_text(sender, "Send HISTORY plus a member ID or phone number, e.g. HISTORY 42.")
            return {"status": "submission_history_prompt"}

        if menu_action == "ADMIN_TT_CODE":
            send_admin_code(sender)
            return {"status": "admin_code"}

        if menu_action == "ADMIN_TT_STATUS":
            send_text(sender, f"{get_tt_status()}\n\nType ADMIN for tools.")
            return {"status": "status"}

        if menu_action == "ADMIN_JOBS_STATUS":
            send_jobs_status(sender)
            return {"status": "jobs_status"}

        if menu_action == "ADMIN_JOBS_RUN":
            processed = run_jobs_from_admin(sender)
            return {"status": "jobs_run", "processed": processed}

        if menu_action == "ADMIN_JOBS_FAILED":
            count = send_failed_jobs(sender)
            return {"status": "jobs_failed", "count": count}

        if menu_action == "ADMIN_JOBS_RETRY":
            retried = retry_jobs_from_admin(sender)
            return {"status": "jobs_retry", "retried": retried}

        if menu_action == "ADMIN_PENDING":
            count = send_pending_members(sender)
            return {"status": "pending_list" if count else "no_pending"}

        if menu_action == "ADMIN_CORRECT":
            return start_admin_correct_flow(sender, admin_member)

        if menu_action == "ADMIN_RECOVER_TONIGHT":
            count = recover_tonight(sender)
            return {"status": "recover_tonight" if count else "recover_none", "count": count}


    # ───────── MEMBER ─────────
    member = get_member(sender)
    if not member:
        member = create_member(sender)

    # ───────── OPT OUT ─────────
    if text in {"STOP", "OPT OUT"} or menu_action == "OPT_OUT":
        opt_out_leaderboard(sender)
        send_text(sender, "✅ You’ve opted out.")
        return {"status": "opt_out"}

    # ───────── POPIA ─────────
    if not member.get("popia_acknowledged"):

        if text == "OK":
            acknowledge_popia(sender)
            send_text(sender, "✅ Send your *first and last name*.")
            return {"status": "popia_ack"}

        send_text(sender, "ℹ️ Reply OK to continue or STOP to opt out.")
        return {"status": "popia"}

    # ───────── PROFILE ─────────
    profile_state = member.get("profile_state")

    if profile_state and text in {"CANCEL", "CANCEL PROFILE"}:
        clear_profile_state(member["id"])
        send_text(sender, "✅ Profile update cancelled.")
        return {"status": "profile_cancelled"}

    if button:
        profile_btn = button.get("id", "").lower().strip()

        if profile_btn == "edit_name":
            set_profile_state(member["id"], "EDIT_NAME")
            send_text(sender, "Send your first and last name.")
            return {"status": "profile_edit_name"}

        if profile_btn == "edit_type":
            set_profile_state(member["id"], "EDIT_PARTICIPATION")
            send_participation_buttons(sender)
            return {"status": "profile_edit_type"}

    if profile_state == "EDIT_NAME":
        if not raw_text or len(raw_text.split()) < 2:
            send_text(sender, "Please send your first and last name.")
            return {"status": "profile_await_name"}

        parts = raw_text.split()
        save_member_name(member["id"], parts[0], " ".join(parts[1:]))
        clear_profile_state(member["id"]) 
        send_text(sender, "✅ Name updated.")
        return {"status": "profile_name_updated"}

    if profile_state == "EDIT_PARTICIPATION":
        if not button:
            send_participation_buttons(sender)
            return {"status": "profile_await_type"}

        ptype = button.get("id")
        if ptype not in {"RUNNER", "WALKER", "BOTH"}:
            send_participation_buttons(sender)
            return {"status": "profile_bad_type"}

        save_participation_type(member["id"], ptype)
        clear_profile_state(member["id"])
        send_text(sender, f"✅ Participation updated to {ptype.title()}.")
        return {"status": "profile_type_updated"}

    if menu_action in {"PROFILE", "EDIT_PROFILE"}:
        send_user_profile(sender, member)
        return {"status": "profile"}

    if menu_action == "PROGRESS":
        send_user_progress(sender, member)
        return {"status": "progress"}

    if menu_action == "LEADERBOARDS":
        send_leaderboards_menu(sender)
        return {"status": "leaderboards_menu"}

    if menu_action == "TONIGHT_LEADERBOARD":
        send_tonight_leaderboard(sender)
        return {"status": "leaderboard"}

    if menu_action == "OVERALL_LEADERBOARD":
        send_overall_leaderboard(sender, member["id"])
        return {"status": "overall_leaderboard"}

    if menu_action == "MY_RANKING":
        send_my_ranking(sender, member)
        return {"status": "my_ranking"}

    if menu_action == "SHOP":
        send_irene_shop(sender)
        return {"status": "shop"}

    if menu_action == "LEAGUE_STANDINGS":
        send_irene_league_standings(sender)
        return {"status": "league_standings"}

    if text in {"SEASON", "SEASON PB", "SEASON PBS"}:
        send_text(sender, "Season PBs has been replaced by Overall PBs.")
        send_leaderboards_menu(sender)
        return {"status": "leaderboards_menu"}

    if (
        not member.get("first_name")
        or not member.get("last_name")
        or member["first_name"] == "Unknown"
    ):
        if not raw_text or len(raw_text.split()) < 2:
            send_text(sender, "👋 Send *first and last name*.")
            return {"status": "await_name"}

        parts = raw_text.split()
        save_member_name(member["id"], parts[0], " ".join(parts[1:]))

        send_text(sender, "✅ Profile updated.")
        send_participation_buttons(sender)
        return {"status": "profile_done"}

    # ───────── SUBMISSION ─────────
    submission = get_or_create_submission(member["id"])

    if not submission:
        send_text(sender, "⚠️ Please send TT code again.")
        return {"status": "error"}

    if menu_action == "RESUME":
        prompt_status = resume_submission(sender, member, submission)
        return {"status": f"resume_{prompt_status}"}

    if menu_action == "SUBMIT":
        prompt_status = resume_submission(sender, member, submission)
        return {"status": f"menu_submit_{prompt_status}"}

    if menu_action == "FIX_RESULT":
        start_fix_result(sender, submission)
        return {"status": "fix_result"}

    if button and submission["status"] == "COMPLETE":
        btn = button.get("id", "").lower().strip()

        if btn == "edit":
            start_fix_result(sender, submission)
            return {"status": "edit_existing"}

        if btn == "confirm":
            send_text(sender, "✅ Already confirmed.")
            return {"status": "already_confirmed"}

    if submission["status"] == "COMPLETE":
        send_text(
            sender,
            (
                "You’ve already submitted today’s TT.\n\n"
                f"{submission['distance_text']}km — {submission['time_text']}\n\n"
                "Type FIX RESULT to change it, or MENU to go back."
            ),
        )
        return {"status": "edit_existing"}

    # ───────── TT GATE ─────────
    allowed, reason = ensure_tt_open()
    if not allowed:
        send_text(sender, reason)
        return {"status": "closed"}

    # ───────── PARTICIPATION ─────────
    if not member.get("participation_type"):

        if not button:
            send_participation_buttons(sender)
            return {"status": "await_type"}

        ptype = button.get("id")
        if ptype not in {"RUNNER", "WALKER", "BOTH"}:
            send_participation_buttons(sender)
            return {"status": "bad_type"}

        save_participation_type(member["id"], ptype)

        send_text(sender, "👍 Send tonight’s TT code.")
        return {"status": "ptype"}

    # ───────── TT CODE ─────────
    if not submission["tt_code_verified"]:

        if not text:
            send_text(sender, "🔑 Please send tonight's TT code.")
            return {"status": "await_code"}

        if not is_valid_tt_code(text):
            send_text(sender, "❌ That TT code is not valid for today.")
            return {"status": "bad_format"}

        submission = verify_tt_code(submission["id"], text)

        if not submission or not submission.get("tt_code_verified"):
            send_text(sender, "❌ Invalid TT code.")
            return {"status": "bad_code"}

        release_pending_submissions(member["id"])
        submission = get_or_create_submission(member["id"])

        try:
            mark_attendance(member["id"])
        except Exception as e:
            logger.exception("Attendance failed for member_id=%s: %s", member["id"], e)

        send_text(sender, "✅ Checked in!")
        send_whats_new_once(sender, member)
        prompt_status = send_submission_prompt(sender, member["participation_type"])
        return {"status": f"code_ok_{prompt_status}"}

    # ───────── WALKER ─────────
    if member["participation_type"] == "BOTH" and profile_state == "BOTH_WORKOUT":

        if text and not submission["time_text"]:
            submission = save_time(submission["id"], text, 0)
            submission = confirm_submission(submission["id"])
            clear_profile_state(member["id"])

            send_text(sender, "🚶 Workout logged! Well done.")
            return {"status": "both_workout_done"}

        send_text(sender, "🚶 Describe your workout.")
        return {"status": "both_await_workout"}

    if member["participation_type"] == "WALKER":

        if text and not submission["time_text"]:
            submission = save_time(submission["id"], text, 0)
            submission = confirm_submission(submission["id"])

            send_text(sender, "🚶 Workout logged! Well done.")
            return {"status": "walker_done"}

    if (
        member["participation_type"] == "BOTH"
        and not submission["distance_text"]
        and not submission["time_text"]
        and not button
    ):
        send_both_submission_buttons(sender)
        return {"status": "both_await_choice"}

    # ───────── BUTTONS ─────────
    if button:

        btn = button.get("id", "").lower().strip()

        # BOTH SUBMISSION TYPE
        if (
            member["participation_type"] == "BOTH"
            and not submission["distance_text"]
            and not submission["time_text"]
            and btn in {"submit_distance", "submit_workout"}
        ):
            if btn == "submit_workout":
                set_profile_state(member["id"], "BOTH_WORKOUT")
                send_text(sender, "🚶 Describe your workout.")
                return {"status": "both_workout"}

            if btn == "submit_distance":
                clear_profile_state(member["id"])
                send_distance_buttons(sender)
                return {"status": "both_distance"}

            send_both_submission_buttons(sender)
            return {"status": "both_bad_choice"}

        # DISTANCE
        if btn in {"4km", "6km", "8km"}:
            clear_profile_state(member["id"])
            submission = save_distance(
                submission["id"],
                btn.replace("km", "")
            )

            send_text(sender, "⏱ Send your time.")
            return {"status": "distance"}

        # CONFIRM
        if btn == "confirm":

            #Prevent double confirm logic
            if submission["status"] =="COMPLETE":
                send_text(sender,"Already confirmed.")
                return {"status" : "already confirmed"}

            previous_best = None
            if submission.get("seconds"):
                previous_best = get_previous_best(
                    member["id"],
                    submission["distance_text"],
                    submission["id"],
                )

            submission = confirm_submission(submission["id"])
            if not submission:
                send_text(sender, "✅ Already confirmed.")
                return {"status": "already_confirmed"}

            send_text(sender, "TT recorded.")
            enqueue_post_confirm_messages(
                sender,
                dict(member),
                dict(submission),
                previous_best,
            )
            background_tasks.add_task(run_due_jobs, 5)

            return {"status": "done"}

        # EDIT
        if btn == "edit":
            send_distance_buttons(sender)
            return {"status": "edit"}

        if submission["status"] == "PENDING":
            prompt_status = prompt_for_pending_submission(sender, member, submission)
            return {"status": f"unknown_button_{prompt_status}"}

    # ───────── TIME ─────────
    if (
        submission["status"] == "PENDING"
        and submission["distance_text"]
        and not submission["time_text"]
    ):

        if not text or not is_valid_time(text):
            send_text(sender, "⏱ Format: 27:41 or 01:27:41")
            return {"status": "bad_time"}

        seconds = time_to_seconds(text)

        submission = save_time(submission["id"], text, seconds)

        send_confirm_buttons(
            sender,
            submission["distance_text"],
            text
        )

        return {"status": "confirm"}

    if submission["status"] == "PENDING" and submission.get("tt_code_verified"):
        prompt_status = prompt_for_pending_submission(sender, member, submission)
        return {"status": f"recover_{prompt_status}"}

    send_text(
        sender,
        "I can help with submitting a result, checking progress, or leaderboards.",
    )
    send_help_menu(sender, is_admin(sender))
    return {"status": "fallback_help"}



@router.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    raw_body = await request.body()
    signature = request.headers.get("x-hub-signature-256")

    if not verify_webhook_signature(raw_body, signature):
        logger.warning("Rejected webhook with invalid signature")
        raise HTTPException(status_code=403, detail="Invalid webhook signature")

    payload = json.loads(raw_body)
    return await run_in_threadpool(process_webhook_payload, payload, background_tasks)
