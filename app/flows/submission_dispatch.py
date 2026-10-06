"""TT check-in, result entry, and correction routing."""

from types import ModuleType


def handle_submission_message(actions: ModuleType, sender: str, text: str | None, raw_text: str | None, button: dict | None, menu_action: str | None, member: dict):
    # ───────── SUBMISSION ─────────
    # Preserve a verified pending check-in from last night so members can
    # complete the same TT result before the next-day deadline.
    if menu_action == "FIX_RESULT":
        completed_submission = actions.get_self_correctable_tt_submission(member["id"])
        if not completed_submission:
            actions.send_text(sender, "I don’t have a completed result from the current TT to fix. Type MENU for more options.")
            return {"status": "no_result_to_fix"}

        allowed, reason = actions.ensure_tt_open(submission_event_date=completed_submission.get("event_date"))
        if not allowed:
            actions.send_text(sender, reason)
            return {"status": "closed"}

        actions.start_fix_result(sender, member, completed_submission)
        return {"status": "fix_result"}

    # Completed-result corrections are separate from draft submissions. The
    # original remains COMPLETE until this proposal is explicitly confirmed.
    correction = actions.get_member_self_correction(member["id"])
    if correction:
        allowed, reason = actions.ensure_tt_open(submission_event_date=correction.get("event_date"))
        if not allowed:
            actions.cancel_member_self_correction(correction["id"], member["id"])
            actions.send_text(sender, reason)
            return {"status": "self_correction_expired"}
        return actions.handle_member_self_correction(sender, member, correction, raw_text, button, menu_action)

    submission = actions.get_resumable_submission(member["id"]) or actions.get_active_submission(member["id"])

    # Greetings are conversational. They can only resume a real, verified TT
    # state and otherwise remain completely independent of TT availability.
    if menu_action == "GREETING":
        if submission and submission.get("tt_code_verified"):
            allowed, _ = actions.ensure_tt_open(submission_event_date=submission.get("event_date"))
            if allowed:
                prompt_status = actions.resume_submission(sender, member, submission)
                return {"status": f"greeting_{prompt_status}"}

        actions.send_member_greeting(sender, member)
        return {"status": "greeting"}

    if not submission:
        # A delayed duplicate Confirm can arrive after the first click has
        # already completed the row, so no pending row will be found above.
        # Treat it as a harmless acknowledgement rather than opening a new TT.
        if button and button.get("id", "").lower().strip() == "confirm":
            completed_submission = actions.get_completed_submission_for_current_event(member["id"])
            if completed_submission:
                actions.send_text(sender, "✅ Already confirmed.")
                return {"status": "already_confirmed"}

        # A new TT session is gate-controlled before a row is ever created.
        if menu_action == "RESUME":
            actions.send_text(sender, "You don’t have an unfinished TT result to continue.")
            actions.send_help_menu(sender, actions.is_admin(sender), member)
            return {"status": "nothing_to_resume"}

        if menu_action == "SUBMIT":
            completed_submission = actions.get_completed_submission_for_current_event(member["id"])
            if completed_submission:
                actions.send_text(
                    sender,
                    (
                        "You’ve already submitted today’s TT.\n\n"
                        f"{completed_submission['distance_text']}km — {completed_submission['time_text']}\n\n"
                        "Type FIX RESULT while submissions are open, or MENU to go back."
                    ),
                )
                return {"status": "already_submitted"}

            allowed, reason = actions.ensure_tt_open()
            if not allowed:
                actions.send_text(sender, reason)
                return {"status": "closed"}

            actions.send_text(sender, "🔑 Send tonight's TT code to check in. You can type MENU anytime.")
            return {"status": "await_code"}

        allowed, reason = actions.ensure_tt_open()
        if not allowed:
            actions.send_text(sender, reason)
            return {"status": "closed"}

        if not text or not actions.is_valid_tt_code(text):
            actions.send_text(sender, "🔑 Send tonight's TT code to check in.")
            return {"status": "await_code"}

        completed_submission = actions.get_completed_submission_for_current_event(member["id"])
        if completed_submission:
            actions.send_text(
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
        actions.release_pending_submissions(member["id"])
        submission = actions.get_or_create_submission(member["id"])

        if not submission:
            actions.send_text(sender, "⚠️ Please send TT code again.")
            return {"status": "error"}

        submission = actions.verify_tt_code(submission["id"], text)

        if not submission or not submission.get("tt_code_verified"):
            actions.send_text(sender, "❌ Invalid TT code.")
            return {"status": "bad_code"}

        try:
            actions.mark_attendance(member["id"])
        except Exception as e:
            actions.logger.exception("Attendance failed for member_id=%s: %s", member["id"], e)

        first_name = member.get("first_name") or "there"
        actions.send_text(sender, f"✅ Welcome back, {first_name}! You’re checked in. Let’s capture your TT result.")
        actions.send_whats_new_once(sender, member)
        prompt_status = actions.send_submission_prompt(sender, member["participation_type"])
        return {"status": f"code_ok_{prompt_status}"}

    # Every continuation, including explicit RESUME/SUBMIT, is gated. This
    # preserves the verified Tuesday submission until Wednesday's deadline.
    allowed, reason = actions.ensure_tt_open(submission_event_date=submission.get("event_date"))
    if not allowed:
        actions.send_text(sender, reason)
        return {"status": "closed"}

    if menu_action == "RESUME":
        prompt_status = actions.resume_submission(sender, member, submission)
        return {"status": f"resume_{prompt_status}"}

    if menu_action == "SUBMIT":
        prompt_status = actions.resume_submission(sender, member, submission)
        return {"status": f"menu_submit_{prompt_status}"}

    if button and submission["status"] == "COMPLETE":
        btn = button.get("id", "").lower().strip()

        if btn == "edit":
            actions.start_fix_result(sender, member, submission)
            return {"status": "edit_existing"}

        if btn == "confirm":
            actions.send_text(sender, "✅ Already confirmed.")
            return {"status": "already_confirmed"}

    if submission["status"] == "COMPLETE":
        actions.send_text(
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
            actions.send_text(sender, "🔑 Please send tonight's TT code to check in.")
            return {"status": "await_code"}

        if not actions.is_valid_tt_code(text):
            actions.send_text(sender, "❌ That TT code is not valid for today.")
            return {"status": "bad_format"}

        # Clear any abandoned attempt before verifying a fresh submission.  Doing
        # this after verification would cancel the submission we just checked in.
        actions.release_pending_submissions(member["id"])
        submission = actions.get_or_create_submission(member["id"])

        if not submission:
            actions.send_text(sender, "⚠️ Please send TT code again.")
            return {"status": "error"}

        submission = actions.verify_tt_code(submission["id"], text)

        if not submission or not submission.get("tt_code_verified"):
            actions.send_text(sender, "❌ Invalid TT code.")
            return {"status": "bad_code"}

        try:
            actions.mark_attendance(member["id"])
        except Exception as e:
            actions.logger.exception("Attendance failed for member_id=%s: %s", member["id"], e)

        first_name = member.get("first_name") or "there"
        actions.send_text(
            sender,
            f"✅ Welcome back, {first_name}! You’re checked in. Let’s capture your TT result.",
        )
        actions.send_whats_new_once(sender, member)
        prompt_status = actions.send_submission_prompt(sender, member["participation_type"])
        return {"status": f"code_ok_{prompt_status}"}

    # ───────── WALKER ─────────
    if actions._is_workout_submission(member, submission) and not submission.get("time_text"):
        # The submission mode selects this path. Profile state is only
        # onboarding/UI residue and is deliberately not needed after Edit.
        is_both_workout = member.get("participation_type") == "BOTH"
        status_prefix = "both_" if is_both_workout else "walker_"

        if text and not submission["time_text"]:
            submission = actions.save_workout_for_confirmation(submission["id"], text)
            actions.clear_profile_state(member["id"])
            if not submission:
                actions.send_text(sender, "⚠️ I couldn't save that workout note. Please send it again.")
                return {"status": f"{status_prefix}workout_save_failed"}

            actions.send_workout_confirm_buttons(sender, submission["time_text"])
            return {"status": f"{status_prefix}workout_confirm"}

        actions.send_text(sender, actions.WORKOUT_ENTRY_PROMPT)
        return {"status": f"{status_prefix}await_workout"}

    if (
        not submission.get("mode")
        and member["participation_type"] == "BOTH"
        and not submission["distance_text"]
        and not submission["time_text"]
        and not button
    ):
        actions.send_both_submission_buttons(sender)
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
                actions.set_submission_mode(submission["id"], "WORKOUT")
                actions.set_profile_state(member["id"], "BOTH_WORKOUT")
                actions.send_text(sender, actions.WORKOUT_ENTRY_PROMPT)
                return {"status": "both_workout"}

            if btn == "submit_distance":
                actions.set_submission_mode(submission["id"], "RUN")
                actions.clear_profile_state(member["id"])
                actions.send_distance_buttons(sender)
                return {"status": "both_distance"}

            actions.send_both_submission_buttons(sender)
            return {"status": "both_bad_choice"}

        # Saved workouts (including legacy rows) always receive a review step.
        if actions._is_workout_submission(member, submission) and submission.get("time_text"):
            if btn == "confirm":
                submission = actions.confirm_workout_submission(submission["id"])
                if not submission:
                    actions.send_text(sender, "✅ Already confirmed.")
                    return {"status": "already_confirmed"}
                actions.clear_profile_state(member["id"])
                actions.send_text(sender, "🚶 Workout logged! Well done.")
                return {"status": "workout_confirmed"}

            if btn == "edit":
                actions.reopen_workout_submission_for_edit(submission["id"])
                actions.clear_profile_state(member["id"])
                actions.send_text(sender, actions.WORKOUT_EDIT_PROMPT)
                return {"status": "workout_edit"}

        # DISTANCE
        if btn in {"4km", "6km", "8km"}:
            actions.clear_profile_state(member["id"])
            submission = actions.save_distance(
                submission["id"],
                btn.replace("km", "")
            )

            actions.send_text(sender, "⏱ Send your time, e.g. 27:41. I’ll show a confirmation before saving.")
            return {"status": "distance"}

        # CONFIRM
        if btn == "confirm":

            #Prevent double confirm logic
            if submission["status"] =="COMPLETE":
                actions.send_text(sender,"Already confirmed.")
                return {"status" : "already confirmed"}

            # A late interactive reply must not turn an unfinished check-in
            # into a result. The service repeats this condition in SQL so a
            # concurrent or direct caller cannot bypass it.
            if (
                submission.get("distance_text") not in {"4", "6", "8"}
                or not submission.get("time_text")
                or not submission.get("seconds")
            ):
                prompt_status = actions.prompt_for_pending_submission(sender, member, submission)
                return {"status": f"confirm_not_ready_{prompt_status}"}

            previous_best = None
            if submission.get("seconds"):
                previous_best = actions.get_previous_best(
                    member["id"],
                    submission["distance_text"],
                    submission["id"],
                )

            submission = actions.confirm_submission(
                submission["id"],
                followup={"sender": sender, "member": dict(member), "previous_best": previous_best},
            )
            if not submission:
                actions.send_text(sender, "✅ Already confirmed.")
                return {"status": "already_confirmed"}

            actions.send_text(sender, "TT recorded.")
            return {"status": "done"}

        # EDIT
        if btn == "edit":
            # Editing a reviewed runner result is a state transition, not just
            # a new prompt.  Persistently clear the reviewed values first so a
            # late Confirm from the old WhatsApp card cannot complete them.
            submission = actions.reopen_submission_for_edit(submission["id"])
            actions.clear_profile_state(member["id"])
            actions.send_distance_buttons(sender)
            return {"status": "edit"}

        if submission["status"] == "PENDING":
            prompt_status = actions.prompt_for_pending_submission(sender, member, submission)
            return {"status": f"unknown_button_{prompt_status}"}

    # ───────── TIME ─────────
    if (
        submission["status"] == "PENDING"
        and submission["distance_text"]
        and not submission["time_text"]
    ):

        if not text or not actions.is_valid_time(text):
            actions.send_text(sender, "⏱ Format: 27:41 or 01:27:41")
            return {"status": "bad_time"}

        seconds = actions.time_to_seconds(text)

        submission = actions.save_time(submission["id"], text, seconds)

        actions.send_confirm_buttons(
            sender,
            submission["distance_text"],
            text
        )

        return {"status": "confirm"}

    if submission["status"] == "PENDING" and submission.get("tt_code_verified"):
        prompt_status = actions.prompt_for_pending_submission(sender, member, submission)
        return {"status": f"recover_{prompt_status}"}

    actions.send_text(
        sender,
        "I can help with submitting a result, checking progress, or leaderboards.",
    )
    actions.send_help_menu(sender, actions.is_admin(sender), member)
    return {"status": "fallback_help"}
