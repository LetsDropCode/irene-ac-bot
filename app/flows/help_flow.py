HELP_COMMANDS = {"HELP", "MENU", "START", "\\HELP", "/HELP", "?"}

MENU_ACTIONS = {
    "1": "SUBMIT",
    "SUBMIT": "SUBMIT",
    "SUBMIT TT": "SUBMIT",
    "TT": "SUBMIT",
    "TT RESULT": "SUBMIT",
    "CODE": "SUBMIT",
    "TT CODE": "SUBMIT",
    "TIME": "RESUME",
    "RESULT": "RESUME",
    "MY RESULT": "RESUME",
    "LAST RESULT": "RESUME",
    "CONTINUE": "RESUME",
    "RESUME": "RESUME",
    "CARRY ON": "RESUME",
    "HELP ME": "RESUME",
    "HI": "RESUME",
    "HELLO": "RESUME",
    "HEY": "RESUME",
    "2": "PROFILE",
    "PROFILE": "PROFILE",
    "MY PROFILE": "PROFILE",
    "3": "PROGRESS",
    "PROGRESS": "PROGRESS",
    "MY PROGRESS": "PROGRESS",
    "STATS": "PROGRESS",
    "MY STATS": "PROGRESS",
    "4": "LEADERBOARDS",
    "LEADERBOARD": "LEADERBOARDS",
    "LEADERBOARDS": "LEADERBOARDS",
    "RESULTS": "LEADERBOARDS",
    "RANKINGS": "LEADERBOARDS",
    "TONIGHT": "TONIGHT_LEADERBOARD",
    "TONIGHT LEADERBOARD": "TONIGHT_LEADERBOARD",
    "TONIGHT RESULTS": "TONIGHT_LEADERBOARD",
    "5": "OVERALL_LEADERBOARD",
    "OVERALL": "OVERALL_LEADERBOARD",
    "OVERALL LEADERBOARD": "OVERALL_LEADERBOARD",
    "OVERALL PBS": "OVERALL_LEADERBOARD",
    "PB": "OVERALL_LEADERBOARD",
    "PBS": "OVERALL_LEADERBOARD",
    "PB LEADERBOARD": "OVERALL_LEADERBOARD",
    "FASTEST": "OVERALL_LEADERBOARD",
    "RANK": "MY_RANKING",
    "RANKING": "MY_RANKING",
    "MY RANK": "MY_RANKING",
    "MY RANKING": "MY_RANKING",
    "SHOP": "SHOP",
    "IRENE SHOP": "SHOP",
    "THE IRENE SHOP": "SHOP",
    "CLUB SHOP": "SHOP",
    "LEAGUE": "LEAGUE_STANDINGS",
    "IRENE LEAGUE": "LEAGUE_STANDINGS",
    "THE IRENE LEAGUE": "LEAGUE_STANDINGS",
    "LEAGUE STANDINGS": "LEAGUE_STANDINGS",
    "STANDINGS": "LEAGUE_STANDINGS",
    "6": "SHOP",
    "7": "LEAGUE_STANDINGS",
    "8": "EDIT_PROFILE",
    "EDIT": "EDIT_PROFILE",
    "EDIT PROFILE": "EDIT_PROFILE",
    "EDIT DETAILS": "EDIT_PROFILE",
    "FIX": "FIX_RESULT",
    "FIX RESULT": "FIX_RESULT",
    "FIX MY RESULT": "FIX_RESULT",
    "CHANGE": "FIX_RESULT",
    "CHANGE RESULT": "FIX_RESULT",
    "CHANGE MY RESULT": "FIX_RESULT",
    "WRONG TIME": "FIX_RESULT",
    "WRONG DISTANCE": "FIX_RESULT",
    "EDIT RESULT": "FIX_RESULT",
    "EDIT MY RESULT": "FIX_RESULT",
    "9": "OPT_OUT",
    "STOP LEADERBOARD": "OPT_OUT",
    "OPT OUT": "OPT_OUT",
    "ADMIN": "ADMIN_MENU",
    "ADMIN MENU": "ADMIN_MENU",
    "ADMIN TOOLS": "ADMIN_MENU",
    "FIND": "ADMIN_FIND",
    "LOOKUP": "ADMIN_FIND",
    "SEARCH": "ADMIN_FIND",
    "HISTORY": "ADMIN_HISTORY",
    "TIMES": "ADMIN_HISTORY",
    "RESULT HISTORY": "ADMIN_HISTORY",
    "STATUS": "ADMIN_TT_STATUS",
    "TT STATUS": "ADMIN_TT_STATUS",
    "PENDING": "ADMIN_PENDING",
    "CORRECT": "ADMIN_CORRECT",
    "FIX TIME": "ADMIN_CORRECT",
    "CORRECT TIME": "ADMIN_CORRECT",
    "RECOVER TONIGHT": "ADMIN_RECOVER_TONIGHT",
    "RESEND TONIGHT": "ADMIN_RECOVER_TONIGHT",
    "FIX TONIGHT": "ADMIN_RECOVER_TONIGHT",
}

INTERACTIVE_ACTIONS = {
    "menu_submit": "SUBMIT",
    "menu_profile": "PROFILE",
    "menu_progress": "PROGRESS",
    "menu_leaderboard": "LEADERBOARDS",
    "leaderboard_tonight": "TONIGHT_LEADERBOARD",
    "leaderboard_overall": "OVERALL_LEADERBOARD",
    "leaderboard_my_ranking": "MY_RANKING",
    "menu_shop": "SHOP",
    "menu_league_standings": "LEAGUE_STANDINGS",
    "menu_edit_profile": "EDIT_PROFILE",
    "menu_opt_out": "OPT_OUT",
    "admin_menu": "ADMIN_MENU",
    "admin_tt_code": "ADMIN_TT_CODE",
    "admin_tt_status": "ADMIN_TT_STATUS",
    "admin_pending": "ADMIN_PENDING",
    "admin_correct": "ADMIN_CORRECT",
    "admin_recover_tonight": "ADMIN_RECOVER_TONIGHT",
    "admin_tonight_leaderboard": "TONIGHT_LEADERBOARD",
    "admin_overall_leaderboard": "OVERALL_LEADERBOARD",
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
        "4 - Leaderboards\n"
        "5 - Overall PBs\n"
        "6 - The Irene Shop\n"
        "7 - Irene League Standings\n"
        "8 - Edit my details\n"
        "9 - Stop leaderboard sharing\n\n"
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
        "CORRECT <member id or phone> <4|6|8> <time>\n"
        "RECOVER TONIGHT"
    )
