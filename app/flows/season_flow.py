"""Private season/history commands with explicit, bounded year and page input."""

import re

from app.services.season_service import current_season


def handle_season_message(actions, sender, member, text, menu_action):
    if menu_action == "MY_PBS":
        actions.send_personal_bests(sender, member)
        return {"status": "personal_bests"}
    if menu_action == "HOW_TT_WORKS":
        actions.send_tt_introduction(sender)
        return {"status": "tt_introduction"}
    if menu_action not in {"MEMBER_HISTORY", "SEASON", "SEASON_LEADERBOARD"}:
        return None

    patterns = {
        "MEMBER_HISTORY": r"(?:MY )?HISTORY(?: (\d{4})(?: PAGE (\d{1,5}))?)?",
        "SEASON": r"(?:MY )?SEASON(?: (\d{4}))?",
        "SEASON_LEADERBOARD": r"SEASON (?:LEADERBOARD|PBS?)(?: (\d{4}))?",
    }
    # Interactive selections have no command text.
    command = (None if text == "3" else text) or {"MEMBER_HISTORY": "MY HISTORY", "SEASON": "SEASON",
                       "SEASON_LEADERBOARD": "SEASON LEADERBOARD"}[menu_action]
    match = re.fullmatch(patterns[menu_action], command)
    if not match:
        actions.send_text(sender, "Try MY HISTORY 2026, MY HISTORY 2026 PAGE 2, SEASON 2026, or SEASON LEADERBOARD 2026.")
        return {"status": "invalid_season_command"}
    year = int(match[1]) if match[1] else None
    page = int(match[2]) if menu_action == "MEMBER_HISTORY" and match[2] else 1
    if (year is not None and not 1 <= year <= current_season()) or not 1 <= page <= 10000:
        actions.send_text(sender, "Choose a calendar year up to the current season and a page from 1 to 10000. Send MY HISTORY to see your years.")
        return {"status": "invalid_season_command"}
    if menu_action == "MEMBER_HISTORY":
        actions.send_member_history(sender, member, year, page)
        return {"status": "member_history"}
    if menu_action == "SEASON_LEADERBOARD":
        actions.send_season_leaderboard(sender, member, year)
        return {"status": "season_leaderboard"}
    actions.send_member_season(sender, member, year)
    return {"status": "member_season"}
