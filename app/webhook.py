import hashlib
import hmac
import json
import logging
import sys

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
from app.flows.webhook_dispatch import route_message
from app.whatsapp import (
    _send_direct,
    queue_inbound_replies,
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
from app.services.openai_service import CoachingContext, coach_for_result
from app.services.profile_service import get_user_profile
from app.services.profile_formatter import format_profile
from app.services.progress_formatter import format_progress
from app.services.engagement_service import (
    format_streak_summary,
    get_attendance_stats,
    set_engagement_preference,
)
from app.services.privacy_service import (
    DELETE_CONFIRMATION_STATE,
    cancel_erasure_request,
    erase_member_after_confirmation,
    get_member_result_history,
    withdraw_consent_and_request_erasure,
)

router = APIRouter()
logger = logging.getLogger(__name__)

IRENE_SHOP_URL = "https://store126837536.shop.netcash.co.za/products"
IRENE_LEAGUE_URL = "https://iac-league-web.onrender.com"

WORKOUT_ENTRY_PROMPT = (
    "🚶 *Workout selected.*\n\n"
    "Type your walk or workout in the message box below, then tap Send.\n"
    "Example: 45 min walk"
)
WORKOUT_EDIT_PROMPT = (
    "🚶 *Edit workout.*\n\n"
    "Type the corrected walk or workout in the message box below, then tap Send."
)


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


def send_streak_summary(sender: str, member: dict):
    send_text(sender, format_streak_summary(get_attendance_stats(member["id"])))


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
        send_text(sender, WORKOUT_ENTRY_PROMPT)
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
        send_text(
            sender,
            f"{WORKOUT_EDIT_PROMPT}\n\nYour saved result remains unchanged until confirmation.",
        )
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
        send_text(sender, WORKOUT_ENTRY_PROMPT)
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

    try:
        from app.services.pace_comparison_service import (
            get_previous_comparable_runs,
            pace_comparison_lines,
        )

        if submission.get("id") and submission.get("event_date"):
            previous_runs = get_previous_comparable_runs(member_id, submission)
            comparison = pace_comparison_lines(submission, previous_runs)
            if comparison:
                lines.extend(["", "*Pace progress*", *comparison])
    except Exception:
        logger.exception("Deterministic pace comparison failed")

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

            trend = detect_trend(profile["recent"], submission["distance_text"])
            fatigue = detect_fatigue(profile["recent"], submission["distance_text"])

            # Identity, contact details, IDs, and unrelated profile history
            # cannot enter the model-facing coaching context.
            insight = coach_for_result(
                CoachingContext(
                    distance_km=submission["distance_text"],
                    time_text=submission["time_text"],
                    pace=pace,
                    trend=trend,
                    fatigue=fatigue,
                )
            )

            if insight:
                lines.extend(["", "*Coach note*", insight])

    except Exception:
        logger.error("Insight engine failed")

    lines.extend(["", "Type MENU for more options, or MY PROGRESS to see your history."])
    if send_text(sender, "\n".join(lines)) is False:
        raise RuntimeError("WhatsApp post-confirm reply was not accepted")


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
        with queue_inbound_replies(message_id):
            result = _process_webhook_message(
                sender,
                text,
                button,
                background_tasks,
            )
        # A scheduled worker drains the durable queue even if this process exits.
        background_tasks.add_task(run_due_jobs, 5)
    except Exception as exc:
        if message_id:
            mark_inbound_message_processed(message_id, "FAILED", str(exc))
        raise

    if message_id:
        mark_inbound_message_processed(message_id, "PROCESSED")
    return result


def _process_webhook_message(sender: str, text: str | None, button: dict | None, background_tasks: BackgroundTasks):
    return route_message(sys.modules[__name__], sender, text, button)


def send_member_data_summary(sender: str, member: dict):
    """Show the member their stored profile and complete TT result history."""
    def display_timestamp(value):
        return value.isoformat(sep=" ", timespec="minutes") if hasattr(value, "isoformat") else (value or "not recorded")

    visibility = "private" if member.get("leaderboard_opt_out") else "public"
    name = f"{member.get('first_name') or ''} {member.get('last_name') or ''}".strip()
    send_text(
        sender,
        "*Your bot data summary*\n"
        f"Phone: {member.get('phone') or sender}\n"
        f"Name: {name}\n"
        f"Participation: {member.get('participation_type') or 'not set'}\n"
        f"Leaderboard: {visibility}\n"
        f"Consent: {'yes' if member.get('popia_acknowledged') else 'no'}\n\n"
        f"Reminders: {'on' if member.get('reminders_opt_in') else 'off'}\n"
        f"Milestones: {'on' if member.get('milestones_opt_in') else 'off'}\n"
        f"Profile created: {display_timestamp(member.get('created_at'))}\n"
        f"Consent recorded: {display_timestamp(member.get('popia_consented_at'))}\n"
        f"Consent withdrawn: {display_timestamp(member.get('popia_withdrawn_at'))}\n\n"
        "Your result history follows. Send PRIVACY for your choices.",
    )
    rows = get_member_result_history(member["id"])
    if not rows:
        send_text(sender, "No TT results are stored for your profile.")
        return

    chunks = []
    current = "*Your TT results*\n"
    for row in rows:
        event_date = row.get("event_date")
        date_label = event_date.isoformat() if hasattr(event_date, "isoformat") else str(event_date)
        detail = row.get("time_text") or "not entered"
        if row.get("distance_text"):
            detail = f"{row['distance_text']}km — {detail}"
        line = f"{date_label}: {detail} ({row.get('status') or 'unknown'})\n"
        if len(current) + len(line) > 3000:
            chunks.append(current)
            current = "*Your TT results (continued)*\n"
        current += line
    chunks.append(current)
    for chunk in chunks:
        send_text(sender, chunk)


def send_erasure_confirmation(sender: str):
    """Send once without persisting the erased phone in a new queue row."""
    try:
        sent = _send_direct({
            "messaging_product": "whatsapp",
            "to": sender,
            "type": "text",
            "text": {
                "body": (
                    "Your TT profile and results have been removed from the bot's active database. "
                    "You will need to opt in again if you return."
                ),
            },
        })
    except Exception:
        logger.exception("Erasure confirmation send failed")
        return False
    if not sent:
        logger.warning("Erasure confirmation could not be delivered")
    return sent



@router.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    raw_body = await request.body()
    signature = request.headers.get("x-hub-signature-256")

    if not verify_webhook_signature(raw_body, signature):
        logger.warning("Rejected webhook with invalid signature")
        raise HTTPException(status_code=403, detail="Invalid webhook signature")

    payload = json.loads(raw_body)
    return await run_in_threadpool(process_webhook_payload, payload, background_tasks)
