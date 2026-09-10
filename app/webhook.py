import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app.config import (
    ADMIN_NUMBERS,
    ENV,
    PUBLIC_BASE_URL,
    WHATSAPP_APP_SECRET,
    WHATS_NEW_MESSAGE,
    WHATS_NEW_VERSION,
    is_deployed_environment,
)
from app.branding import BRAND_NAME, LOGO_PATH, TAGLINE
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
    AWAITING_WORKOUT_CONFIRM,
    resolve_pending_submission_state,
)
from app.whatsapp import (
    send_image,
    send_text,
    send_distance_buttons,
    send_confirm_buttons,
    send_workout_confirm_buttons,
    send_self_correction_confirm_buttons,
    send_participation_buttons,
    send_leaderboard_visibility_buttons,
    send_profile_buttons,
    send_both_submission_buttons,
    send_main_menu_list,
    send_leaderboard_menu_list,
    send_admin_menu_list,
    send_admin_leaderboard_menu_list,
    send_admin_pending_actions,
)

from app.services.event_code_service import generate_tt_code
from app.services.member_service import (
    get_member,
    create_member,
    save_member_name,
    save_participation_type,
    save_onboarding_name_and_advance,
    save_onboarding_participation_and_advance,
    set_profile_state,
    clear_profile_state,
    acknowledge_popia,
    opt_out_leaderboard,
    opt_in_leaderboard,
    set_leaderboard_visibility,
    complete_onboarding_visibility,
    has_seen_whats_new,
    mark_whats_new_seen,
)

from app.services.submission_service import (
    get_or_create_submission,
    get_resumable_submission,
    get_active_submission,
    get_completed_submission_for_current_event,
    get_self_correctable_tt_submission,
    start_member_self_correction,
    get_member_self_correction,
    save_member_self_correction_distance,
    save_member_self_correction_time,
    save_member_self_correction_workout,
    apply_member_self_correction,
    cancel_member_self_correction,
    get_pending_members,
    get_tonight_unprompted_checked_in_members,
    verify_tt_code,
    save_distance,
    save_time,
    confirm_submission,
    release_pending_submissions,
    reopen_submission_for_edit,
    reopen_workout_submission_for_edit,
    set_submission_mode,
    save_workout_for_confirmation,
    confirm_workout_submission,
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
        return ENV in {"development", "test"} and not is_deployed_environment()

    if not signature_header or not signature_header.startswith("sha256="):
        return False

    expected = hmac.new(
        WHATSAPP_APP_SECRET.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    received = signature_header.split("=", 1)[1]
    return hmac.compare_digest(f"sha256={expected}", f"sha256={received}")


def send_help_menu(sender: str, admin: bool = False, member: dict | None = None):
    if not send_main_menu_list(sender, admin, member):
        send_text(sender, format_help_menu(admin))


def send_member_greeting(sender: str, member: dict):
    first_name = member.get("first_name") or "there"
    send_text(sender, f"Hi {first_name} 👋 {TAGLINE}. What would you like to do?")
    send_help_menu(sender, is_admin(sender), member)


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
        if "submission_id" in row:
            prompt_for_pending_submission(
                row["phone"],
                {
                    "id": row.get("member_id"),
                    "participation_type": ptype,
                    "profile_state": row.get("profile_state"),
                },
                row,
            )
        else:
            # Compatibility with older recovery records and test doubles.
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
        send_text(sender, "🚶 Send a short note about your walk or workout, e.g. 45 min walk.")
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
        send_text(sender, "🔑 Send tonight's TT code to check in. You can type MENU anytime.")
        return "await_code"

    return prompt_for_pending_submission(sender, member, submission)


def _is_workout_submission(member: dict, submission: dict) -> bool:
    mode = (submission.get("mode") or "").upper()
    if mode == "WORKOUT":
        return True
    if mode == "RUN":
        return False

    # Mode-less rows predate per-submission activity types. Their populated
    # fields are the safest fallback; an empty legacy walker row still uses
    # the member preference as its original default.
    if not submission.get("distance_text") and submission.get("time_text"):
        return True
    return (
        not submission.get("distance_text")
        and member.get("participation_type") == "WALKER"
    )


def _format_self_correction_value(distance: str | None, time_text: str | None) -> str:
    return f"{distance}km — {time_text}" if distance else (time_text or "Workout")


def _send_self_correction_review(sender: str, correction: dict):
    was = _format_self_correction_value(
        correction.get("original_distance_text"), correction.get("original_time_text")
    )
    new = _format_self_correction_value(correction.get("distance_text"), correction.get("time_text"))
    send_self_correction_confirm_buttons(
        sender,
        f"*Confirm correction*\n\nWas: {was}\nNew: {new}\n\nYour original result changes only after confirmation.",
    )


def prompt_member_self_correction(sender: str, correction: dict):
    if correction.get("mode") == "WORKOUT":
        if correction.get("time_text"):
            _send_self_correction_review(sender, correction)
            return "awaiting_confirm"
        send_text(sender, "Send the corrected walk or workout note. Your saved result remains unchanged until confirmation.")
        return "awaiting_workout"

    if not correction.get("distance_text"):
        send_text(sender, "Choose the corrected distance. Your saved result remains unchanged until confirmation.")
        send_distance_buttons(sender)
        return "awaiting_distance"
    if not correction.get("time_text"):
        send_text(sender, "⏱ Send the corrected time, e.g. 42:58.")
        return "awaiting_time"
    _send_self_correction_review(sender, correction)
    return "awaiting_confirm"


def handle_member_self_correction(sender: str, member: dict, correction: dict, text: str | None, button: dict | None, menu_action):
    if menu_action == "RESUME":
        return {"status": f"self_correction_{prompt_member_self_correction(sender, correction)}"}

    btn = button.get("id", "").lower().strip() if button else ""
    if btn == "self_correction_cancel":
        cancel_member_self_correction(correction["id"], member["id"])
        send_text(sender, "✅ Correction cancelled. Your original TT result is unchanged.")
        return {"status": "self_correction_cancelled"}

    if btn == "self_correction_confirm":
        updated = apply_member_self_correction(correction["id"], member["id"])
        if not updated:
            send_text(sender, "✅ This correction was already handled, or it is no longer available.")
            return {"status": "self_correction_already_handled"}
        send_text(sender, "✅ Your TT result has been corrected.")
        return {"status": "self_correction_confirmed", "submission_id": updated["id"]}

    if correction.get("mode") == "WORKOUT":
        if text and not correction.get("time_text") and menu_action not in {"FIX_RESULT", "SUBMIT"}:
            updated = save_member_self_correction_workout(correction["id"], member["id"], text)
            if updated:
                _send_self_correction_review(sender, updated)
                return {"status": "self_correction_awaiting_confirm"}
        return {"status": f"self_correction_{prompt_member_self_correction(sender, correction)}"}

    if btn in {"4km", "6km", "8km"}:
        updated = save_member_self_correction_distance(
            correction["id"], member["id"], btn.replace("km", "")
        )
        if updated:
            send_text(sender, "⏱ Send the corrected time, e.g. 42:58.")
            return {"status": "self_correction_awaiting_time"}

    if correction.get("distance_text") and not correction.get("time_text"):
        if not text or not is_valid_time(text):
            send_text(sender, "⏱ Format: 27:41 or 01:27:41")
            return {"status": "self_correction_bad_time"}
        updated = save_member_self_correction_time(
            correction["id"], member["id"], text, time_to_seconds(text)
        )
        if updated:
            _send_self_correction_review(sender, updated)
            return {"status": "self_correction_awaiting_confirm"}

    return {"status": f"self_correction_{prompt_member_self_correction(sender, correction)}"}


def start_fix_result(sender: str, member: dict, submission: dict):
    if not submission.get("tt_code_verified"):
        send_text(sender, "I don’t have a result to fix yet. Send tonight’s TT code to start.")
        return submission

    mode = "WORKOUT" if _is_workout_submission(member, submission) else "RUN"
    correction = start_member_self_correction(member["id"], submission["id"], mode)
    if not correction:
        send_text(sender, "⚠️ I couldn't start that correction. Your original result is unchanged.")
        return None
    prompt_member_self_correction(sender, correction)
    return correction


def send_whats_new_once(sender: str, member: dict):
    if has_seen_whats_new(member, WHATS_NEW_VERSION):
        return False

    send_text(sender, WHATS_NEW_MESSAGE)
    mark_whats_new_seen(member["id"], WHATS_NEW_VERSION)
    return True


def prompt_for_pending_submission(sender: str, member: dict, submission: dict):
    state = resolve_pending_submission_state(member, submission)

    if state == AWAITING_WORKOUT:
        send_text(sender, "🚶 Send a short note about your walk or workout, e.g. 45 min walk.")
        return state

    if state == AWAITING_WORKOUT_CONFIRM:
        send_workout_confirm_buttons(sender, submission["time_text"])
        return state

    if state == AWAITING_BOTH_CHOICE:
        send_both_submission_buttons(sender)
        return state

    if state == AWAITING_DISTANCE:
        send_distance_buttons(sender)
        return state

    if state == AWAITING_TIME:
        send_text(sender, "⏱ Send your time, for example 27:41 or 01:27:41. I’ll show a confirmation before saving.")
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


def send_post_confirm_messages(
    sender: str,
    member_id: int,
    first_name: str,
    submission: dict,
    previous_best,
):
    profile = {"total_runs": None, "recent": []}
    pace = None

    try:
        from app.services.insight_services import seconds_to_pace

        if submission.get("seconds"):
            pace = seconds_to_pace(
                submission["seconds"],
                submission["distance_text"]
            )
    except Exception:
        logger.error("Pace calculation failed")

    try:
        profile = get_user_profile(member_id)
    except Exception:
        logger.error("Profile summary failed")

    lines = [
        f"🏁 *{first_name}, your TT result is saved*",
        "",
        "*Result*",
        f"Distance: {submission['distance_text']} km",
        f"Time: {submission['time_text']}",
    ]

    if pace:
        lines.append(f"Pace: {pace}")

    highlights = []
    if previous_best is None:
        highlights.append(f"First recorded {submission['distance_text']} km result")
    elif submission["seconds"] < previous_best:
        diff = previous_best - submission["seconds"]
        highlights.append(f"PB by {_format_improvement(diff)}")

    progress = []
    if profile.get("total_runs"):
        progress.append(f"Season TTs: {profile['total_runs']}")

    rows = get_runner_leaderboard()
    position = _find_runner_position(
        rows,
        member_id,
        submission["distance_text"],
    )
    if position:
        progress.append(f"Tonight's {submission['distance_text']} km position: #{position}")

    highlights.extend(
        _milestone_lines(profile.get("total_runs") or 0, previous_best, submission)
    )

    if progress:
        lines.extend(["", "*Progress*", *progress])

    if highlights:
        lines.extend(["", "*Highlights*"])
        lines.extend(f"- {line}" for line in highlights)

    try:
        if submission.get("seconds"):

            from app.services.insight_services import (
                detect_trend,
                detect_fatigue,
            )

            trend = detect_trend(profile["recent"])
            fatigue = detect_fatigue(profile["recent"])

            # This is the entire model-facing context. Identity, contact
            # details, IDs, and unrelated profile history stay outside it.
            prompt = (
                f"Runner completed {submission['distance_text']}km in {submission['time_text']} "
                f"(pace {pace}). Trend: {trend}. "
            )

            if fatigue:
                prompt += f"{fatigue}. "

            prompt += "Give short coaching feedback."

            insight = coach_reply(prompt)

            if insight:
                lines.extend(["", "*Coach note*", insight])

    except Exception:
        logger.error("Insight engine failed")

    lines.extend(["", "Type MENU for more options, or MY PROGRESS to see your history."])
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
    admin_sender = is_admin(sender)

    if admin_sender and text == "MENU":
        admin_member = get_member(sender)
        clear_admin_edit_state_if_needed(admin_member)
        send_help_menu(sender, True, admin_member)
        return {"status": "help"}

    if is_help_command(text):
        send_help_menu(sender, admin_sender, get_member(sender))
        return {"status": "help"}

    menu_action = resolve_menu_action(text, admin=admin_sender) if text else None
    if button:
        menu_action = resolve_interactive_action(button.get("id", "")) or menu_action

    if button and button.get("id", "").lower().strip() == "back_menu":
        if admin_sender:
            clear_admin_edit_state_if_needed(get_member(sender))
        send_help_menu(sender, admin_sender, get_member(sender))
        return {"status": "menu"}

    # ───────── ADMIN ─────────
    if admin_sender:
        admin_member = get_member(sender)
        admin_state_text = text
        admin_state_raw_text = raw_text

        if button:
            # Button semantics are resolved centrally in help_flow.py. The
            # existing admin state machine still receives its familiar input.
            admin_button_text = {
                "ADMIN_MEMBER_HISTORY": "HISTORY",
                "ADMIN_MEMBER_CORRECT": "CORRECT",
            }.get(menu_action)
            if not admin_button_text:
                admin_button_id = button.get("id", "").lower().strip()
                admin_button_text = {
                    "admin_edit_time": "TIME",
                    "admin_edit_distance": "DISTANCE",
                    "admin_edit_both": "BOTH",
                    "admin_confirm_correction": "YES",
                    "admin_cancel_correction": "NO",
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
            set_profile_state(admin_member["id"], "ADMIN_FIND")
            send_text(
                sender,
                (
                    "Send a member name or phone number, e.g. Lindsay or 2772...\n"
                    "Then reply with the number to open that member."
                ),
            )
            return {"status": "member_lookup_prompt"}

        if menu_action == "ADMIN_HISTORY":
            send_text(
                sender,
                "Choose Find member first, then select History from the Member Command Center.\n\n"
                "You can still type HISTORY plus a member ID or phone number.",
            )
            return {"status": "submission_history_prompt"}

        if menu_action == "ADMIN_LEADERBOARDS":
            if not send_admin_leaderboard_menu_list(sender):
                send_text(sender, "Reply TONIGHT LEADERBOARD or OVERALL PBs.")
            return {"status": "admin_leaderboards"}

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

    # ───────── CONSENT / ONBOARDING ─────────
    # Do not persist a profile simply because an unknown number contacted us.
    # The affirmative consent reply is the sole creation path for new members.
    if not member:
        if text == "OK":
            member = create_member(sender, popia_acknowledged=True)
            send_text(sender, "✅ Thanks. Please send your *first and last name* so I can set up your TT profile.")
            return {"status": "popia_ack"}

        if text in {"STOP", "NO", "NO THANKS", "DECLINE"}:
            send_text(
                sender,
                "No problem — no TT profile or results have been stored. "
                "Send HI anytime if you would like to join later.",
            )
            return {"status": "consent_declined"}

        if PUBLIC_BASE_URL:
            send_image(
                sender,
                f"{PUBLIC_BASE_URL}{LOGO_PATH}",
                f"Welcome to {BRAND_NAME} — {TAGLINE}.",
            )

        send_text(
            sender,
            (
                f"🌳 *Welcome to Irene AC TT*\n_{TAGLINE}._\n\n"
                "Reply *OK* to create your TT profile and allow the bot to store "
                "your profile and TT results.\n\n"
                "Reply *NO THANKS* to leave without creating a profile."
            ),
        )
        return {"status": "popia"}

    # ───────── LEADERBOARD SHARING ─────────
    # Sharing is independent from consent to store a member's private profile
    # and results. Neither choice deletes historical data.
    if menu_action == "OPT_OUT":
        opt_out_leaderboard(sender)
        send_text(
            sender,
            "✅ Your results are now hidden from public leaderboards. "
            "Your TT profile and results are still saved privately. "
            "Send START SHARING anytime to opt back in.",
        )
        return {"status": "opt_out"}

    if menu_action == "OPT_IN":
        opt_in_leaderboard(sender)
        send_text(
            sender,
            "✅ Your results will appear on public leaderboards again. "
            "Your existing TT profile and results are unchanged.",
        )
        return {"status": "opt_in"}

    if text == "STOP":
        send_text(
            sender,
            "To hide your results from public leaderboards, send STOP LEADERBOARD. "
            "This does not delete your TT profile or results.",
        )
        return {"status": "stop_clarified"}

    # ───────── POPIA ─────────
    if not member.get("popia_acknowledged"):
        if text == "OK":
            acknowledge_popia(sender)
            send_text(sender, "✅ Thanks. Please send your *first and last name* so I can set up your TT profile.")
            return {"status": "popia_ack"}

        send_text(
            sender,
            (
                f"🌳 *Welcome to Irene AC TT*\n_{TAGLINE}._\n\n"
                "Reply *OK* to allow the bot to store your TT profile and results.\n\n"
                "Leaderboard sharing is a separate setting you can change anytime."
            ),
        )
        return {"status": "popia"}

    # ───────── PROFILE ─────────
    profile_state = member.get("profile_state")

    if profile_state == "ONBOARDING_LEADERBOARD" and text in {"CANCEL", "CANCEL PROFILE"}:
        send_leaderboard_visibility_buttons(sender)
        return {"status": "onboarding_await_visibility"}

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
            send_text(sender, "Please send both your first and last name, e.g. Lindsay Bull.")
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

    if profile_state == "ONBOARDING_PARTICIPATION":
        if not button:
            send_participation_buttons(sender)
            return {"status": "onboarding_await_type"}

        ptype = button.get("id")
        if ptype not in {"RUNNER", "WALKER", "BOTH"}:
            send_participation_buttons(sender)
            return {"status": "onboarding_bad_type"}

        save_onboarding_participation_and_advance(member["id"], ptype)
        send_text(sender, "✅ Participation saved. Choose whether to share your TT results publicly.")
        send_leaderboard_visibility_buttons(sender)
        return {"status": "onboarding_await_visibility"}

    if profile_state == "ONBOARDING_LEADERBOARD":
        visibility_button = button.get("id", "").lower().strip() if button else ""
        if visibility_button not in {"onboarding_show_results", "onboarding_keep_private"}:
            send_leaderboard_visibility_buttons(sender)
            return {"status": "onboarding_await_visibility"}

        private = visibility_button == "onboarding_keep_private"
        completed = complete_onboarding_visibility(member["id"], private)
        if not completed:
            # Never claim a profile is public/private if the guarded atomic
            # transition was not applied; leave it safely incomplete instead.
            send_leaderboard_visibility_buttons(sender)
            return {"status": "onboarding_await_visibility"}
        send_text(
            sender,
            "✅ Your TT profile is complete. "
            + ("Your results will stay private." if private else "Your results can appear on public leaderboards.")
            + " Type MENU anytime to explore your options.",
        )
        send_help_menu(sender, is_admin(sender), member)
        return {"status": "profile_complete"}

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
            send_text(sender, "👋 Welcome. Please send your *first and last name* to set up your TT profile.")
            return {"status": "await_name"}

        parts = raw_text.split()
        save_onboarding_name_and_advance(member["id"], parts[0], " ".join(parts[1:]))

        send_text(sender, "✅ Profile created. Now choose how you usually take part.")
        send_participation_buttons(sender)
        return {"status": "profile_done"}

    # Older profiles may have a saved name but no participation type. Completing
    # that profile is available at all times and never starts a TT submission.
    if not member.get("participation_type"):
        if not button:
            set_profile_state(member["id"], "ONBOARDING_PARTICIPATION")
            send_participation_buttons(sender)
            return {"status": "onboarding_await_type"}

        ptype = button.get("id")
        if ptype not in {"RUNNER", "WALKER", "BOTH"}:
            send_participation_buttons(sender)
            return {"status": "onboarding_bad_type"}

        save_onboarding_participation_and_advance(member["id"], ptype)
        send_text(sender, "✅ Participation saved. Choose whether to share your TT results publicly.")
        send_leaderboard_visibility_buttons(sender)
        return {"status": "onboarding_await_visibility"}

    # New profiles must choose visibility before accessing TT submission.
    # Missing/NULL retains compatibility for profiles created before this step.
    if member.get("leaderboard_visibility_set") is False:
        set_profile_state(member["id"], "ONBOARDING_LEADERBOARD")
        send_leaderboard_visibility_buttons(sender)
        return {"status": "onboarding_await_visibility"}

    # ───────── SUBMISSION ─────────
    # Preserve a verified pending check-in from last night so members can
    # complete the same TT result before the next-day deadline.
    if menu_action == "FIX_RESULT":
        completed_submission = get_self_correctable_tt_submission(member["id"])
        if not completed_submission:
            send_text(sender, "I don’t have a completed result from the current TT to fix. Type MENU for more options.")
            return {"status": "no_result_to_fix"}

        allowed, reason = ensure_tt_open(submission_event_date=completed_submission.get("event_date"))
        if not allowed:
            send_text(sender, reason)
            return {"status": "closed"}

        start_fix_result(sender, member, completed_submission)
        return {"status": "fix_result"}

    # Completed-result corrections are separate from draft submissions. The
    # original remains COMPLETE until this proposal is explicitly confirmed.
    correction = get_member_self_correction(member["id"])
    if correction:
        allowed, reason = ensure_tt_open(submission_event_date=correction.get("event_date"))
        if not allowed:
            cancel_member_self_correction(correction["id"], member["id"])
            send_text(sender, reason)
            return {"status": "self_correction_expired"}
        return handle_member_self_correction(sender, member, correction, raw_text, button, menu_action)

    submission = get_resumable_submission(member["id"]) or get_active_submission(member["id"])

    # Greetings are conversational. They can only resume a real, verified TT
    # state and otherwise remain completely independent of TT availability.
    if menu_action == "GREETING":
        if submission and submission.get("tt_code_verified"):
            allowed, _ = ensure_tt_open(submission_event_date=submission.get("event_date"))
            if allowed:
                prompt_status = resume_submission(sender, member, submission)
                return {"status": f"greeting_{prompt_status}"}

        send_member_greeting(sender, member)
        return {"status": "greeting"}

    if not submission:
        # A delayed duplicate Confirm can arrive after the first click has
        # already completed the row, so no pending row will be found above.
        # Treat it as a harmless acknowledgement rather than opening a new TT.
        if button and button.get("id", "").lower().strip() == "confirm":
            completed_submission = get_completed_submission_for_current_event(member["id"])
            if completed_submission:
                send_text(sender, "✅ Already confirmed.")
                return {"status": "already_confirmed"}

        # A new TT session is gate-controlled before a row is ever created.
        if menu_action == "RESUME":
            send_text(sender, "You don’t have an unfinished TT result to continue.")
            send_help_menu(sender, is_admin(sender), member)
            return {"status": "nothing_to_resume"}

        if menu_action == "SUBMIT":
            completed_submission = get_completed_submission_for_current_event(member["id"])
            if completed_submission:
                send_text(
                    sender,
                    (
                        "You’ve already submitted today’s TT.\n\n"
                        f"{completed_submission['distance_text']}km — {completed_submission['time_text']}\n\n"
                        "Type FIX RESULT while submissions are open, or MENU to go back."
                    ),
                )
                return {"status": "already_submitted"}

            allowed, reason = ensure_tt_open()
            if not allowed:
                send_text(sender, reason)
                return {"status": "closed"}

            send_text(sender, "🔑 Send tonight's TT code to check in. You can type MENU anytime.")
            return {"status": "await_code"}

        allowed, reason = ensure_tt_open()
        if not allowed:
            send_text(sender, reason)
            return {"status": "closed"}

        if not text or not is_valid_tt_code(text):
            send_text(sender, "🔑 Send tonight's TT code to check in.")
            return {"status": "await_code"}

        completed_submission = get_completed_submission_for_current_event(member["id"])
        if completed_submission:
            send_text(
                sender,
                (
                    "You’ve already submitted today’s TT.\n\n"
                    f"{completed_submission['distance_text']}km — {completed_submission['time_text']}\n\n"
                    "Type FIX RESULT while submissions are open, or MENU to go back."
                ),
            )
            return {"status": "already_submitted"}

        # Compatibility cleanup for legacy unverified rows happens only after
        # an open gate and a valid code; new sessions do not exist before here.
        release_pending_submissions(member["id"])
        submission = get_or_create_submission(member["id"])

        if not submission:
            send_text(sender, "⚠️ Please send TT code again.")
            return {"status": "error"}

        submission = verify_tt_code(submission["id"], text)

        if not submission or not submission.get("tt_code_verified"):
            send_text(sender, "❌ Invalid TT code.")
            return {"status": "bad_code"}

        try:
            mark_attendance(member["id"])
        except Exception as e:
            logger.exception("Attendance failed for member_id=%s: %s", member["id"], e)

        first_name = member.get("first_name") or "there"
        send_text(sender, f"✅ Welcome back, {first_name}! You’re checked in. Let’s capture your TT result.")
        send_whats_new_once(sender, member)
        prompt_status = send_submission_prompt(sender, member["participation_type"])
        return {"status": f"code_ok_{prompt_status}"}

    # Every continuation, including explicit RESUME/SUBMIT, is gated. This
    # preserves the verified Tuesday submission until Wednesday's deadline.
    allowed, reason = ensure_tt_open(submission_event_date=submission.get("event_date"))
    if not allowed:
        send_text(sender, reason)
        return {"status": "closed"}

    if menu_action == "RESUME":
        prompt_status = resume_submission(sender, member, submission)
        return {"status": f"resume_{prompt_status}"}

    if menu_action == "SUBMIT":
        prompt_status = resume_submission(sender, member, submission)
        return {"status": f"menu_submit_{prompt_status}"}

    if button and submission["status"] == "COMPLETE":
        btn = button.get("id", "").lower().strip()

        if btn == "edit":
            start_fix_result(sender, member, submission)
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

    # ───────── TT CODE ─────────
    if not submission["tt_code_verified"]:

        if not text:
            send_text(sender, "🔑 Please send tonight's TT code to check in.")
            return {"status": "await_code"}

        if not is_valid_tt_code(text):
            send_text(sender, "❌ That TT code is not valid for today.")
            return {"status": "bad_format"}

        # Clear any abandoned attempt before verifying a fresh submission.  Doing
        # this after verification would cancel the submission we just checked in.
        release_pending_submissions(member["id"])
        submission = get_or_create_submission(member["id"])

        if not submission:
            send_text(sender, "⚠️ Please send TT code again.")
            return {"status": "error"}

        submission = verify_tt_code(submission["id"], text)

        if not submission or not submission.get("tt_code_verified"):
            send_text(sender, "❌ Invalid TT code.")
            return {"status": "bad_code"}

        try:
            mark_attendance(member["id"])
        except Exception as e:
            logger.exception("Attendance failed for member_id=%s: %s", member["id"], e)

        first_name = member.get("first_name") or "there"
        send_text(
            sender,
            f"✅ Welcome back, {first_name}! You’re checked in. Let’s capture your TT result.",
        )
        send_whats_new_once(sender, member)
        prompt_status = send_submission_prompt(sender, member["participation_type"])
        return {"status": f"code_ok_{prompt_status}"}

    # ───────── WALKER ─────────
    if _is_workout_submission(member, submission) and not submission.get("time_text"):
        # The submission mode selects this path. Profile state is only
        # onboarding/UI residue and is deliberately not needed after Edit.
        is_both_workout = member.get("participation_type") == "BOTH"
        status_prefix = "both_" if is_both_workout else "walker_"

        if text and not submission["time_text"]:
            submission = save_workout_for_confirmation(submission["id"], text)
            clear_profile_state(member["id"])
            if not submission:
                send_text(sender, "⚠️ I couldn't save that workout note. Please send it again.")
                return {"status": f"{status_prefix}workout_save_failed"}

            send_workout_confirm_buttons(sender, submission["time_text"])
            return {"status": f"{status_prefix}workout_confirm"}

        send_text(sender, "🚶 Send a short note about your walk or workout, e.g. 45 min walk.")
        return {"status": f"{status_prefix}await_workout"}

    if (
        not submission.get("mode")
        and member["participation_type"] == "BOTH"
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
            not submission.get("mode")
            and member["participation_type"] == "BOTH"
            and not submission["distance_text"]
            and not submission["time_text"]
            and btn in {"submit_distance", "submit_workout"}
        ):
            if btn == "submit_workout":
                set_submission_mode(submission["id"], "WORKOUT")
                set_profile_state(member["id"], "BOTH_WORKOUT")
                send_text(sender, "🚶 Send a short note about your walk or workout, e.g. 45 min walk.")
                return {"status": "both_workout"}

            if btn == "submit_distance":
                set_submission_mode(submission["id"], "RUN")
                clear_profile_state(member["id"])
                send_distance_buttons(sender)
                return {"status": "both_distance"}

            send_both_submission_buttons(sender)
            return {"status": "both_bad_choice"}

        # Saved workouts (including legacy rows) always receive a review step.
        if _is_workout_submission(member, submission) and submission.get("time_text"):
            if btn == "confirm":
                submission = confirm_workout_submission(submission["id"])
                if not submission:
                    send_text(sender, "✅ Already confirmed.")
                    return {"status": "already_confirmed"}
                clear_profile_state(member["id"])
                send_text(sender, "🚶 Workout logged! Well done.")
                return {"status": "workout_confirmed"}

            if btn == "edit":
                reopen_workout_submission_for_edit(submission["id"])
                clear_profile_state(member["id"])
                send_text(sender, "🚶 Send the corrected walk or workout note.")
                return {"status": "workout_edit"}

        # DISTANCE
        if btn in {"4km", "6km", "8km"}:
            clear_profile_state(member["id"])
            submission = save_distance(
                submission["id"],
                btn.replace("km", "")
            )

            send_text(sender, "⏱ Send your time, e.g. 27:41. I’ll show a confirmation before saving.")
            return {"status": "distance"}

        # CONFIRM
        if btn == "confirm":

            #Prevent double confirm logic
            if submission["status"] =="COMPLETE":
                send_text(sender,"Already confirmed.")
                return {"status" : "already confirmed"}

            # A late interactive reply must not turn an unfinished check-in
            # into a result. The service repeats this condition in SQL so a
            # concurrent or direct caller cannot bypass it.
            if (
                submission.get("distance_text") not in {"4", "6", "8"}
                or not submission.get("time_text")
                or not submission.get("seconds")
            ):
                prompt_status = prompt_for_pending_submission(sender, member, submission)
                return {"status": f"confirm_not_ready_{prompt_status}"}

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
            try:
                enqueue_post_confirm_messages(
                    sender,
                    dict(member),
                    dict(submission),
                    previous_best,
                )
            except Exception:
                # A coaching/follow-up delivery failure must never undo or
                # turn a saved TT result into a failed confirmation.
                logger.error("Could not queue post-confirm follow-up")
            background_tasks.add_task(run_due_jobs, 5)

            return {"status": "done"}

        # EDIT
        if btn == "edit":
            # Editing a reviewed runner result is a state transition, not just
            # a new prompt.  Persistently clear the reviewed values first so a
            # late Confirm from the old WhatsApp card cannot complete them.
            submission = reopen_submission_for_edit(submission["id"])
            clear_profile_state(member["id"])
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
    send_help_menu(sender, is_admin(sender), member)
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
