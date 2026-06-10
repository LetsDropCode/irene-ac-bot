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
    "3": "LEADERBOARD",
    "LEADERBOARD": "LEADERBOARD",
    "4": "EDIT_PROFILE",
    "EDIT": "EDIT_PROFILE",
    "EDIT PROFILE": "EDIT_PROFILE",
    "EDIT DETAILS": "EDIT_PROFILE",
    "5": "OPT_OUT",
    "STOP LEADERBOARD": "OPT_OUT",
    "OPT OUT": "OPT_OUT",
}


def is_help_command(text: str) -> bool:
    return text in HELP_COMMANDS


def resolve_menu_action(text: str):
    return MENU_ACTIONS.get(text)


def format_help_menu(admin: bool = False) -> str:
    menu = (
        "🏃 *Irene AC Bot Menu*\n\n"
        "Reply with a number or command:\n\n"
        "1 - Submit TT result\n"
        "2 - My profile\n"
        "3 - Tonight's leaderboard\n"
        "4 - Edit my details\n"
        "5 - Stop leaderboard sharing\n\n"
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
