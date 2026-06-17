from fastapi import APIRouter, BackgroundTasks, Request

from app.config import WHATS_NEW_MESSAGE, WHATS_NEW_VERSION
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
from app.services.validation import is_valid_time, is_valid_tt_code
from app.services.submission_gate import ensure_tt_open
from app.services.pb_service import get_previous_best
from app.services.leaderboard_service import get_runner_leaderboard
from app.services.leaderboard_service import get_season_pb_leaderboard
from app.services.leaderboard_service import get_overall_leaderboard
from app.services.leaderboard_service import get_walker_feed
from app.services.leaderboard_formatter import format_season_pb_leaderboard
from app.services.leaderboard_formatter import format_overall_leaderboard
from app.services.leaderboard_formatter import format_full_leaderboard
from app.services.tt_status_service import get_tt_status
from app.services.openai_service import coach_reply
from app.services.profile_service import get_user_profile
from app.services.profile_formatter import format_profile
from app.services.progress_formatter import format_progress

router = APIRouter()

ADMIN_NUMBERS = {
    "27722135094",
    "27738870757",
    "27829370733",
    "27818513864",
    "27828827067",
}


def is_admin(sender: str) -> bool:
    return sender in ADMIN_NUMBERS


def send_help_menu(sender: str, admin: bool = False):
    if not send_main_menu_list(sender, admin):
        send_text(sender, format_help_menu(admin))


def send_user_profile(sender: str, member: dict):
    data = get_user_profile(member["id"])
    send_profile_buttons(sender, format_profile(member, data))


def send_user_progress(sender: str, member: dict):
    data = get_user_profile(member["id"])
    send_text(sender, format_progress(member, data))


def send_submission_prompt(sender: str, participation_type: str):
    if participation_type == "WALKER":
        send_text(sender, "🚶 Describe your workout.")
        return "walk"

    if participation_type == "BOTH":
        send_both_submission_buttons(sender)
        return "both_choice"

    send_distance_buttons(sender)
    return "distance"


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
        print("⚠️ Pace calculation failed:", str(e))

    try:
        profile = get_user_profile(member["id"])
    except Exception as e:
        print("⚠️ Profile summary failed:", str(e))

    lines = [
        f"🔥 *{first_name}, here’s your TT recap*",
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
        print("⚠️ Insight engine failed:", str(e))

    send_text(sender, "\n".join(lines))


def extract_whatsapp_message(payload: dict):
    try:
        entry = payload.get("entry", [{}])[0]
        change = entry.get("changes", [{}])[0]
        value = change.get("value", {})

        messages = value.get("messages")
        if not messages:
            return None, None, None

        msg = messages[0]
        sender = msg.get("from")

        text = None
        button = None

        if msg.get("type") == "text":
            text = msg.get("text", {}).get("body", "").strip()

        elif msg.get("type") == "interactive":
            interactive = msg.get("interactive", {})
            button = interactive.get("button_reply") or interactive.get("list_reply")

        print("📲 Incoming:", sender, "|", text, "|", button)
        return sender, text, button

    except Exception as e:
        print("❌ extractor error:", str(e))
        return None, None, None


@router.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):

    payload = await request.json()
    sender, text, button = extract_whatsapp_message(payload)

    if not sender or (not text and not button):
        return {"status": "ignored"}

    raw_text = text.strip() if text else None
    if text:
        text = raw_text.upper()

    if is_help_command(text):
        send_help_menu(sender, is_admin(sender))
        return {"status": "help"}

    menu_action = resolve_menu_action(text) if text else None
    if button:
        menu_action = resolve_interactive_action(button.get("id", "")) or menu_action

    # ───────── ADMIN ─────────
    if text and is_admin(sender):

        if text in {"TT CODE", "GET TT CODE", "CODE"}:
            code = generate_tt_code("TT")
            send_text(sender, f"🔐 Tonight’s TT Code\n\n*{code}*")
            return {"status": "admin_code"}

        if text == "LEADERBOARD":
            runners = get_runner_leaderboard()
            walkers = get_walker_feed()

            send_text(sender, format_full_leaderboard(runners, walkers))
            return {"status": "leaderboard"}

        if text == "TT STATUS":
            send_text(sender, get_tt_status())
            return {"status": "status"}

        if menu_action == "SEASON_PB":
            rows = get_season_pb_leaderboard()
            send_text(sender, format_season_pb_leaderboard(rows))
            return {"status": "season_pb"}

        if text in {"OVERALL", "OVERALL LEADERBOARD", "PB LEADERBOARD", "FASTEST"}:
            rows = get_overall_leaderboard()
            send_text(sender, format_overall_leaderboard(rows))
            return {"status": "overall_leaderboard"}

        if text == "PENDING":
            rows = get_pending_members()

            if not rows:
                send_text(sender, "✅ No pending submissions.")
                return {"status": "no_pending"}

            msg = "⏳ *Pending Submissions*\n\n"

            for r in rows:
                msg += f"{r['first_name']} {r['last_name']} ({r['phone']})\n"

            send_text(sender, msg)
            return {"status": "pending_list"}

        if text in {"RECOVER TONIGHT", "RESEND TONIGHT", "FIX TONIGHT"}:
            rows = get_tonight_unprompted_checked_in_members()

            if not rows:
                send_text(sender, "✅ No checked-in users need a prompt resend.")
                return {"status": "recover_none"}

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
                    f"🔄 Both choice: {counts['BOTH']}"
                )
            )
            return {"status": "recover_tonight", "count": len(rows)}

    if button and is_admin(sender):
        if menu_action == "ADMIN_TT_CODE":
            code = generate_tt_code("TT")
            send_text(sender, f"🔐 Tonight’s TT Code\n\n*{code}*")
            return {"status": "admin_code"}

        if menu_action == "ADMIN_TT_STATUS":
            send_text(sender, get_tt_status())
            return {"status": "status"}

        if menu_action == "ADMIN_PENDING":
            rows = get_pending_members()

            if not rows:
                send_text(sender, "✅ No pending submissions.")
                return {"status": "no_pending"}

            msg = "⏳ *Pending Submissions*\n\n"
            for r in rows:
                msg += f"{r['first_name']} {r['last_name']} ({r['phone']})\n"

            send_text(sender, msg)
            return {"status": "pending_list"}


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

    if menu_action == "SEASON_PB":
        rows = get_season_pb_leaderboard()
        send_text(sender, format_season_pb_leaderboard(rows))
        return {"status": "season_pb"}

    if menu_action == "OVERALL_LEADERBOARD":
        rows = get_overall_leaderboard(member["id"])
        send_text(sender, format_overall_leaderboard(rows, member["id"]))
        return {"status": "overall_leaderboard"}

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

    if button and submission["status"] == "COMPLETE":
        btn = button.get("id", "").lower().strip()

        if btn == "edit":
            submission = reopen_submission_for_edit(submission["id"])
            send_distance_buttons(sender)
            return {"status": "edit_existing"}

        if btn == "confirm":
            send_text(sender, "✅ Already confirmed.")
            return {"status": "already_confirmed"}

    if submission["status"] == "COMPLETE":
        send_confirm_buttons(
            sender,
            submission["distance_text"],
            submission["time_text"]
        )
        send_text(sender, "Need to change it? Tap Edit.")
        return {"status": "edit_existing"}

    if menu_action == "LEADERBOARD":
        runners = get_runner_leaderboard()
        walkers = get_walker_feed()
        send_text(sender, format_full_leaderboard(runners, walkers))
        return {"status": "leaderboard"}

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

    if menu_action == "SUBMIT":
        if not submission["tt_code_verified"]:
            send_text(sender, "🔑 Send tonight's TT code to check in.")
            return {"status": "menu_submit_await_code"}

        prompt_status = prompt_for_pending_submission(sender, member, submission)
        return {"status": f"menu_submit_{prompt_status}"}

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
            print("⚠️ Attendance failed:", str(e))

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

            send_text(sender, "🔥 TT recorded!")
            background_tasks.add_task(
                send_post_confirm_messages,
                sender,
                dict(member),
                dict(submission),
                previous_best,
            )

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

        parts = list(map(int, text.split(":")))
        seconds = parts[-1] + parts[-2] * 60
        if len(parts) == 3:
            seconds += parts[0] * 3600

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

    send_text(sender, "I’m not sure what to do with that yet. Send PROFILE, TT CODE, or use the buttons above.")
    return {"status": "fallback_help"}
