from fastapi import APIRouter, Request

from app.whatsapp import (
    send_text,
    send_distance_buttons,
    send_confirm_buttons,
    send_participation_buttons,
    send_profile_buttons,
    send_both_submission_buttons,
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
from app.services.leaderboard_service import get_walker_feed
from app.services.leaderboard_formatter import format_season_pb_leaderboard
from app.services.leaderboard_formatter import format_full_leaderboard
from app.services.tt_status_service import get_tt_status
from app.services.openai_service import coach_reply
from app.services.profile_service import get_user_profile

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


def send_submission_prompt(sender: str, participation_type: str):
    if participation_type == "WALKER":
        send_text(sender, "🚶 Describe your workout.")
        return "walk"

    if participation_type == "BOTH":
        send_both_submission_buttons(sender)
        return "both_choice"

    send_distance_buttons(sender)
    return "distance"


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
            button = msg.get("interactive", {}).get("button_reply")

        print("📲 Incoming:", sender, "|", text, "|", button)
        return sender, text, button

    except Exception as e:
        print("❌ extractor error:", str(e))
        return None, None, None


@router.post("/webhook")
async def webhook(request: Request):

    payload = await request.json()
    sender, text, button = extract_whatsapp_message(payload)

    if not sender or (not text and not button):
        return {"status": "ignored"}

    raw_text = text.strip() if text else None
    if text:
        text = raw_text.upper()

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

        if text == "SEASON":
            rows = get_season_pb_leaderboard()
            send_text(sender, format_season_pb_leaderboard(rows))
            return {"status": "season_pb"}

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


    # ───────── MEMBER ─────────
    member = get_member(sender)
    if not member:
        member = create_member(sender)

    # ───────── OPT OUT ─────────
    if text in {"STOP", "OPT OUT"}:
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

    if text in {"PROFILE", "MY PROFILE"}:
        from app.services.profile_formatter import format_profile
        data = get_user_profile(member["id"])
        send_profile_buttons(sender, format_profile(member, data))
        return {"status": "profile"}

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
            print("⚠️ Attendance failed:", str(e))

        send_text(sender, "✅ Checked in!")
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
            is_pb = False
            if submission.get("seconds"):
                previous_best = get_previous_best(
                    member["id"],
                    submission["distance_text"],
                    submission["id"],
                )
                is_pb = previous_best is None or submission["seconds"] < previous_best

            submission = confirm_submission(submission["id"])
            if not submission:
                send_text(sender, "✅ Already confirmed.")
                return {"status": "already_confirmed"}

            send_text(sender, "🔥 TT recorded!")

            if is_pb:
                if previous_best:
                    diff = previous_best - submission["seconds"]
                    mins = diff // 60
                    secs = diff % 60
                    send_text(sender, f"🚀 {submission['distance_text']}km PB! (-{mins}:{secs:02d}) 🔥")
                else:
                    send_text(sender, f"🚀 First {submission['distance_text']}km PB! 🔥")

            # ───────── ELITE INSIGHTS ─────────
            try:
                if submission.get("seconds"):

                    from app.services.insight_services import (
                        seconds_to_pace,
                        detect_trend,
                        detect_fatigue,
                    )

                    profile = get_user_profile(member["id"])

                    pace = seconds_to_pace(
                        submission["seconds"],
                        submission["distance_text"]
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
                        send_text(sender, f"🧠 Coach:\n{insight}")

            except Exception as e:
                print("⚠️ Insight engine failed:", str(e))

            # ───────── LEADERBOARD ─────────
            rows = get_runner_leaderboard()
            walkers = get_walker_feed()
            send_text(sender, format_full_leaderboard(rows, walkers))

            for r in rows:
                if (
                    r.get("member_id") == member["id"]
                    and r["distance_text"] == submission["distance_text"]
                ):
                    send_text(
                        sender,
                        f"🏆 You are position {r['position']} in the {r['distance_text']}!"
                    )
                    break

            return {"status": "done"}

        # EDIT
        if btn == "edit":
            send_distance_buttons(sender)
            return {"status": "edit"}

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

    return {"status": "noop"}
