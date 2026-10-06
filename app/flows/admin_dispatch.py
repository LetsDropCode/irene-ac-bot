"""Admin command routing for the WhatsApp conversation."""

from types import ModuleType


def handle_admin_message(actions: ModuleType, sender: str, text: str | None, raw_text: str | None, button: dict | None, menu_action: str | None, admin_sender: bool):
    # ───────── ADMIN ─────────
    if admin_sender:
        admin_member = actions.get_member(sender)
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
            return actions.correct_admin_result(
                sender,
                raw_text,
                admin_member["id"] if admin_member else None,
            )

        if text and any(text.startswith(prefix) for prefix in ("FIND ", "LOOKUP ", "SEARCH ")):
            query = raw_text.split(" ", 1)[1].strip()
            count = actions.send_member_lookup(sender, query, admin_member)
            return {"status": "member_lookup", "count": count}

        if text and any(text.startswith(prefix) for prefix in ("HISTORY ", "TIMES ")):
            identifier = raw_text.split(" ", 1)[1].strip()
            count = actions.send_submission_history(sender, identifier)
            if admin_member and count:
                actions.set_profile_state(admin_member["id"], f"ADMIN_HISTORY|{identifier}")
            return {"status": "submission_history", "count": count}

        if menu_action == "ADMIN_MENU":
            actions.clear_admin_edit_state_if_needed(admin_member)
            actions.send_admin_dashboard(sender)
            actions.send_admin_tools_menu(sender)
            return {"status": "admin_menu"}

        state_result = actions.handle_admin_edit_state(
            sender,
            admin_member,
            admin_state_raw_text,
            admin_state_text,
        )
        if state_result:
            return state_result

        if menu_action == "ADMIN_FIND":
            actions.set_profile_state(admin_member["id"], "ADMIN_FIND")
            actions.send_text(
                sender,
                (
                    "Send a member name or phone number, e.g. Lindsay or 2772...\n"
                    "Then reply with the number to open that member."
                ),
            )
            return {"status": "member_lookup_prompt"}

        if menu_action == "ADMIN_HISTORY":
            actions.send_text(
                sender,
                "Choose Find member first, then select History from the Member Command Center.\n\n"
                "You can still type HISTORY plus a member ID or phone number.",
            )
            return {"status": "submission_history_prompt"}

        if menu_action == "ADMIN_LEADERBOARDS":
            if not actions.send_admin_leaderboard_menu_list(sender):
                actions.send_text(sender, "Reply TONIGHT LEADERBOARD, OVERALL PBs, or DATE RANGE LEADERBOARD.")
            return {"status": "admin_leaderboards"}

        if menu_action == "ADMIN_DATE_RANGE_LEADERBOARD":
            actions.set_profile_state(admin_member["id"], "ADMIN_LEADERBOARD_RANGE")
            actions.send_text(
                sender,
                (
                    "Send the inclusive date range for past Tuesday leaderboards.\n"
                    "Each TT night will be shown separately.\n\n"
                    "Example: 2026-09-01 to 2026-09-30\n"
                    "You can also use 01/09/2026 to 30/09/2026.\n"
                    "For one Tuesday, use the same date twice."
                ),
            )
            return {"status": "admin_leaderboard_range_prompt"}

        if menu_action == "ADMIN_TT_CODE":
            actions.send_admin_code(sender)
            return {"status": "admin_code"}

        if menu_action == "ADMIN_TT_STATUS":
            actions.send_text(sender, f"{actions.get_tt_status()}\n\nType ADMIN for tools.")
            return {"status": "status"}

        if menu_action == "ADMIN_JOBS_STATUS":
            actions.send_jobs_status(sender)
            return {"status": "jobs_status"}

        if menu_action == "ADMIN_JOBS_RUN":
            processed = actions.run_jobs_from_admin(sender)
            return {"status": "jobs_run", "processed": processed}

        if menu_action == "ADMIN_JOBS_FAILED":
            count = actions.send_failed_jobs(sender)
            return {"status": "jobs_failed", "count": count}

        if menu_action == "ADMIN_JOBS_RETRY":
            retried = actions.retry_jobs_from_admin(sender)
            return {"status": "jobs_retry", "retried": retried}

        if menu_action == "ADMIN_PENDING":
            count = actions.send_pending_members(sender)
            return {"status": "pending_list" if count else "no_pending"}

        if menu_action == "ADMIN_CORRECT":
            return actions.start_admin_correct_flow(sender, admin_member)

        if menu_action == "ADMIN_RECOVER_TONIGHT":
            count = actions.recover_tonight(sender)
            return {"status": "recover_tonight" if count else "recover_none", "count": count}


    return None
