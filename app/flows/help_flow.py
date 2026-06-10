HELP_COMMANDS = {"HELP", "MENU", "START", "HI", "HELLO", "\\HELP", "/HELP", "?"}

MENU_ACTIONS = {
    "1": "SUBMIT",
    "SUBMIT": "SUBMIT",
    "SUBMIT TT": "SUBMIT",
    "TT": "SUBMIT",
    "TT RESULT": "SUBMIT",
    "2": "PROFILE",
    "PROFILE": "PROFILE",
    "MY PROFILE": "PROFILE",
    "3": "PROGRESS",
    "PROGRESS": "PROGRESS",
    "MY PROGRESS": "PROGRESS",
    "STATS": "PROGRESS",
    "MY STATS": "PROGRESS",
    "4": "LEADERBOARD",
    "LEADERBOARD": "LEADERBOARD",
    "5": "EDIT_PROFILE",
    "EDIT": "EDIT_PROFILE",
    "EDIT PROFILE": "EDIT_PROFILE",
    "EDIT DETAILS": "EDIT_PROFILE",
    "6": "OPT_OUT",
    "STOP LEADERBOARD": "OPT_OUT",
    "OPT OUT": "OPT_OUT",
}

INTERACTIVE_ACTIONS = {
    "menu_submit": "SUBMIT",
    "menu_profile": "PROFILE",
    "menu_progress": "PROGRESS",
    "menu_leaderboard": "LEADERBOARD",
    "menu_edit_profile": "EDIT_PROFILE",
    "menu_opt_out": "OPT_OUT",
    "admin_tt_code": "ADMIN_TT_CODE",
    "admin_tt_status": "ADMIN_TT_STATUS",
    "admin_pending": "ADMIN_PENDING",
}


def is_help_command(text: str) -> bool:
    return text in HELP_COMMANDS


def resolve_menu_action(text: str):
    return MENU_ACTIONS.get(text)


def resolve_interactive_action(reply_id: str):
    return INTERACTIVE_ACTIONS.get(reply_id)


def format_help_menu(admin: bool = False) -> str:
    menu = (
        "🏃 *Irene AC Bot Menu*\n\n"
        "Reply with a number or command:\n\n"
        "1 - Submit TT result\n"
        "2 - My profile\n"
        "3 - My progress\n"
        "4 - Tonight's leaderboard\n"
        "5 - Edit my details\n"
        "6 - Stop leaderboard sharing\n\n"
        "Tip: you can send HELP anytime."
    )

    if not admin:
        return menu

    return (
        f"{menu}\n\n"
        "🔐 *Admin commands*\n"
        "TT CODE\n"
        "TT STATUS\n"
        "PENDING\n"
        "RECOVER TONIGHT\n"
        "SEASON"
    )
