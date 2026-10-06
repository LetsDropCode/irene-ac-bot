"""Consent, onboarding, profile, and member menu routing."""

from types import ModuleType


def handle_member_message(actions: ModuleType, sender: str, text: str | None, raw_text: str | None, button: dict | None, menu_action: str | None, member: dict | None):
    # Erasure removes inbound idempotency rows too. A retried confirmation must
    # remain silent instead of generating a fresh welcome/outbound PII record.
    if not member and text == "CONFIRM DELETE":
        return {"status": "data_erased"}

    if menu_action == "PRIVACY":
        actions.send_text(
            sender,
            "*Irene AC TT privacy*\n\n"
            "With your OK, the bot stores your phone number, name, participation "
            "choice, check-ins and TT results to run your profile and progress. "
            "You choose separately whether results appear on public leaderboards. "
            "The bot uses WhatsApp to send replies and TT updates.\n\n"
            "Send MY DATA for a summary of your stored profile and results, "
            "EDIT PROFILE or FIX RESULT to correct details, STOP LEADERBOARD "
            "to hide public results, or DELETE MY DATA to withdraw consent "
            "and erase your bot records after confirmation. Optional REMINDERS "
            "and MILESTONES messages are off until you opt in."
        )
        return {"status": "privacy_notice"}

    if not member and menu_action in {"MY_DATA", "DELETE_MY_DATA"}:
        actions.send_text(sender, "I don't have a TT profile for this number.")
        return {"status": "no_member_data"}

    if member and menu_action == "MY_DATA":
        actions.send_member_data_summary(sender, member)
        return {"status": "member_data_summary"}

    if member and member.get("profile_state") == actions.DELETE_CONFIRMATION_STATE:
        if text == "CONFIRM DELETE":
            if actions.erase_member_after_confirmation(sender):
                actions.send_erasure_confirmation(sender)
                return {"status": "data_erased"}
            actions.send_text(sender, "I couldn't complete the deletion. Please try again.")
            return {"status": "data_erasure_failed"}
        if text == "CANCEL DELETE":
            if not actions.cancel_erasure_request(sender):
                actions.send_text(sender, "I couldn't cancel the request. Please try again.")
                return {"status": "data_erasure_cancel_failed"}
            actions.send_text(
                sender,
                "Deletion cancelled. Consent is still withdrawn and your results remain private. "
                "Send OK to consent again, or DELETE MY DATA to restart deletion.",
            )
            return {"status": "data_erasure_cancelled"}
        actions.send_text(
            sender,
            "Consent is withdrawn. Reply CONFIRM DELETE to erase your TT profile and "
            "results, or CANCEL DELETE to keep them private without using the bot.",
        )
        return {"status": "await_delete_confirmation"}

    if member and menu_action == "DELETE_MY_DATA":
        if not actions.withdraw_consent_and_request_erasure(sender):
            actions.send_text(sender, "I don't have a TT profile for this number.")
            return {"status": "no_member_data"}
        actions.send_text(
            sender,
            "Consent withdrawn; your results are hidden and pending queued bot messages have been "
            "stopped. Erasure is permanent: reply CONFIRM DELETE to erase your TT profile "
            "and results, or CANCEL DELETE to keep them private without using the bot.",
        )
        return {"status": "await_delete_confirmation"}

    # ───────── CONSENT / ONBOARDING ─────────
    # Do not persist a profile simply because an unknown number contacted us.
    # The affirmative consent reply is the sole creation path for new members.
    if not member:
        if text == "OK":
            member = actions.create_member(sender, popia_acknowledged=True)
            actions.send_text(sender, "✅ Thanks. Please send your *first and last name* so I can set up your TT profile.")
            return {"status": "popia_ack"}

        if text in {"STOP", "NO", "NO THANKS", "DECLINE"}:
            actions.send_text(
                sender,
                "No problem — no TT profile or results have been stored. "
                "Send HI anytime if you would like to join later.",
            )
            return {"status": "consent_declined"}

        if actions.PUBLIC_BASE_URL:
            actions.send_image(
                sender,
                f"{actions.PUBLIC_BASE_URL}{actions.LOGO_PATH}",
                f"Welcome to {actions.BRAND_NAME} — {actions.TAGLINE}.",
            )

        actions.send_text(
            sender,
            (
                f"🌳 *Welcome to Irene AC TT*\n_{actions.TAGLINE}._\n\n"
                "Reply *OK* to create your TT profile and allow the bot to store "
                "your profile and TT results.\n\n"
                "Reply *NO THANKS* to leave without creating a profile. "
                "Send *PRIVACY* to read how your data is used before deciding."
            ),
        )
        return {"status": "popia"}

    # ───────── LEADERBOARD SHARING ─────────
    # Sharing is independent from consent to store a member's private profile
    # and results. Neither choice deletes historical data.
    if menu_action == "OPT_OUT":
        actions.opt_out_leaderboard(sender)
        actions.send_text(
            sender,
            "✅ Your results are now hidden from public leaderboards. "
            "Your TT profile and results are still saved privately. "
            "Send START SHARING anytime to opt back in.",
        )
        return {"status": "opt_out"}

    if menu_action == "OPT_IN":
        if not member.get("popia_acknowledged"):
            actions.send_text(sender, "Consent is withdrawn. Send OK to consent again before sharing results.")
            return {"status": "consent_required"}
        actions.opt_in_leaderboard(sender)
        actions.send_text(
            sender,
            "✅ Your results will appear on public leaderboards again. "
            "Your existing TT profile and results are unchanged.",
        )
        return {"status": "opt_in"}

    if text == "STOP":
        actions.send_text(
            sender,
            "To hide your results from public leaderboards, send STOP LEADERBOARD. "
            "This does not delete your TT profile or results.",
        )
        return {"status": "stop_clarified"}

    # ───────── POPIA ─────────
    if not member.get("popia_acknowledged"):
        if text == "OK":
            actions.acknowledge_popia(sender)
            actions.send_text(sender, "✅ Thanks. Please send your *first and last name* so I can set up your TT profile.")
            return {"status": "popia_ack"}

        actions.send_text(
            sender,
            (
                f"🌳 *Welcome to Irene AC TT*\n_{actions.TAGLINE}._\n\n"
                "Reply *OK* to allow the bot to store your TT profile and results.\n\n"
                "Leaderboard sharing is a separate setting you can change anytime. "
                "Send *PRIVACY* for data details and your choices."
            ),
        )
        return {"status": "popia"}

    if menu_action == "MY_STREAK":
        actions.send_streak_summary(sender, member)
        return {"status": "streak_summary"}

    engagement_actions = {
        "REMINDERS_ON": ("reminders", True),
        "REMINDERS_OFF": ("reminders", False),
        "MILESTONES_ON": ("milestones", True),
        "MILESTONES_OFF": ("milestones", False),
    }
    if menu_action in engagement_actions:
        preference, enabled = engagement_actions[menu_action]
        if not actions.set_engagement_preference(member["id"], preference, enabled):
            actions.send_text(sender, "I couldn't update that setting. Please try again.")
            return {"status": "engagement_setting_failed"}
        actions.send_text(
            sender,
            f"✅ {preference.title()} messages are now {'on' if enabled else 'off'}. "
            "You can change this anytime from your profile.",
        )
        return {"status": "engagement_setting_updated"}

    # ───────── PROFILE ─────────
    profile_state = member.get("profile_state")

    if profile_state == "ONBOARDING_LEADERBOARD" and text in {"CANCEL", "CANCEL PROFILE"}:
        actions.send_leaderboard_visibility_buttons(sender)
        return {"status": "onboarding_await_visibility"}

    if profile_state and text in {"CANCEL", "CANCEL PROFILE"}:
        actions.clear_profile_state(member["id"])
        actions.send_text(sender, "✅ Profile update cancelled.")
        return {"status": "profile_cancelled"}

    if button:
        profile_btn = button.get("id", "").lower().strip()

        if profile_btn == "edit_name":
            actions.set_profile_state(member["id"], "EDIT_NAME")
            actions.send_text(sender, "Send your first and last name.")
            return {"status": "profile_edit_name"}

        if profile_btn == "edit_type":
            actions.set_profile_state(member["id"], "EDIT_PARTICIPATION")
            actions.send_participation_buttons(sender)
            return {"status": "profile_edit_type"}

    if profile_state == "EDIT_NAME":
        if not raw_text or len(raw_text.split()) < 2:
            actions.send_text(sender, "Please send both your first and last name, e.g. Lindsay Bull.")
            return {"status": "profile_await_name"}

        parts = raw_text.split()
        actions.save_member_name(member["id"], parts[0], " ".join(parts[1:]))
        actions.clear_profile_state(member["id"])
        actions.send_text(sender, "✅ Name updated.")
        return {"status": "profile_name_updated"}

    if profile_state == "EDIT_PARTICIPATION":
        if not button:
            actions.send_participation_buttons(sender)
            return {"status": "profile_await_type"}

        ptype = button.get("id")
        if ptype not in {"RUNNER", "WALKER", "BOTH"}:
            actions.send_participation_buttons(sender)
            return {"status": "profile_bad_type"}

        actions.save_participation_type(member["id"], ptype)
        actions.clear_profile_state(member["id"])
        actions.send_text(sender, f"✅ Participation updated to {ptype.title()}.")
        return {"status": "profile_type_updated"}

    if profile_state == "ONBOARDING_PARTICIPATION":
        if not button:
            actions.send_participation_buttons(sender)
            return {"status": "onboarding_await_type"}

        ptype = button.get("id")
        if ptype not in {"RUNNER", "WALKER", "BOTH"}:
            actions.send_participation_buttons(sender)
            return {"status": "onboarding_bad_type"}

        actions.save_onboarding_participation_and_advance(member["id"], ptype)
        actions.send_text(sender, "✅ Participation saved. Choose whether to share your TT results publicly.")
        actions.send_leaderboard_visibility_buttons(sender)
        return {"status": "onboarding_await_visibility"}

    if profile_state == "ONBOARDING_LEADERBOARD":
        visibility_button = button.get("id", "").lower().strip() if button else ""
        if visibility_button not in {"onboarding_show_results", "onboarding_keep_private"}:
            actions.send_leaderboard_visibility_buttons(sender)
            return {"status": "onboarding_await_visibility"}

        private = visibility_button == "onboarding_keep_private"
        completed = actions.complete_onboarding_visibility(member["id"], private)
        if not completed:
            # Never claim a profile is public/private if the guarded atomic
            # transition was not applied; leave it safely incomplete instead.
            actions.send_leaderboard_visibility_buttons(sender)
            return {"status": "onboarding_await_visibility"}
        actions.send_text(
            sender,
            "✅ Your TT profile is complete. "
            + ("Your results will stay private." if private else "Your results can appear on public leaderboards.")
            + " Type MENU anytime to explore your options.",
        )
        actions.send_help_menu(sender, actions.is_admin(sender), member)
        return {"status": "profile_complete"}

    if menu_action in {"PROFILE", "EDIT_PROFILE"}:
        actions.send_user_profile(sender, member)
        return {"status": "profile"}

    if menu_action == "PROGRESS":
        actions.send_user_progress(sender, member)
        return {"status": "progress"}

    if menu_action == "LEADERBOARDS":
        actions.send_leaderboards_menu(sender)
        return {"status": "leaderboards_menu"}

    if menu_action == "TONIGHT_LEADERBOARD":
        actions.send_tonight_leaderboard(sender)
        return {"status": "leaderboard"}

    if menu_action == "OVERALL_LEADERBOARD":
        actions.send_overall_leaderboard(sender, member["id"])
        return {"status": "overall_leaderboard"}

    if menu_action == "MY_RANKING":
        actions.send_my_ranking(sender, member)
        return {"status": "my_ranking"}

    if menu_action == "SHOP":
        actions.send_irene_shop(sender)
        return {"status": "shop"}

    if menu_action == "LEAGUE_STANDINGS":
        actions.send_irene_league_standings(sender)
        return {"status": "league_standings"}

    if text in {"SEASON", "SEASON PB", "SEASON PBS"}:
        actions.send_text(sender, "Season PBs has been replaced by Overall PBs.")
        actions.send_leaderboards_menu(sender)
        return {"status": "leaderboards_menu"}

    if (
        not member.get("first_name")
        or not member.get("last_name")
        or member["first_name"] == "Unknown"
    ):
        if not raw_text or len(raw_text.split()) < 2:
            actions.send_text(sender, "👋 Welcome. Please send your *first and last name* to set up your TT profile.")
            return {"status": "await_name"}

        parts = raw_text.split()
        actions.save_onboarding_name_and_advance(member["id"], parts[0], " ".join(parts[1:]))

        actions.send_text(sender, "✅ Profile created. Now choose how you usually take part.")
        actions.send_participation_buttons(sender)
        return {"status": "profile_done"}

    # Older profiles may have a saved name but no participation type. Completing
    # that profile is available at all times and never starts a TT submission.
    if not member.get("participation_type"):
        if not button:
            actions.set_profile_state(member["id"], "ONBOARDING_PARTICIPATION")
            actions.send_participation_buttons(sender)
            return {"status": "onboarding_await_type"}

        ptype = button.get("id")
        if ptype not in {"RUNNER", "WALKER", "BOTH"}:
            actions.send_participation_buttons(sender)
            return {"status": "onboarding_bad_type"}

        actions.save_onboarding_participation_and_advance(member["id"], ptype)
        actions.send_text(sender, "✅ Participation saved. Choose whether to share your TT results publicly.")
        actions.send_leaderboard_visibility_buttons(sender)
        return {"status": "onboarding_await_visibility"}

    # New profiles must choose visibility before accessing TT submission.
    # Missing/NULL retains compatibility for profiles created before this step.
    if member.get("leaderboard_visibility_set") is False:
        actions.set_profile_state(member["id"], "ONBOARDING_LEADERBOARD")
        actions.send_leaderboard_visibility_buttons(sender)
        return {"status": "onboarding_await_visibility"}

    return None
