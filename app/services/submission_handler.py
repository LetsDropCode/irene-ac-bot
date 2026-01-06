# app/services/submission_handler.py

import re
from app.services.event_detector import get_active_event
from app.services.event_code_validator import validate_event_code


RUN_PATTERN = re.compile(
    r"(?P<distance>\d+(\.\d+)?km)\s+(?P<time>\d{1,2}:\d{2})(\s+(?P<code>[A-Za-z0-9]+))?",
    re.IGNORECASE
)

WALK_PATTERN = re.compile(r"^\d{1,2}:\d{2}$")


def handle_submission(member: dict, text: str):
    event = get_active_event()

    if not event:
        return False, (
            "❌ There’s no active club event right now.\n\n"
            "Please submit during official run times 🕒"
        ), None

    participation = member["participation_type"]

    # ---------------- RUN ----------------
    run_match = RUN_PATTERN.search(text)

    if run_match:
        if participation == "WALKER":
            return False, (
                "🚶 You’re registered as a *WALKER*.\n\n"
                "Please submit *time only*."
            ), None

        code = run_match.group("code")
        valid, result = validate_event_code(code, event)

        if not valid:
            return False, result, None

        parsed = {
            "type": "RUN",
            "event": event,
            "distance": run_match.group("distance"),
            "time": run_match.group("time"),
        }

        reply = (
            f"✅ *{event}* run submitted!\n\n"
            f"🏃 {parsed['distance']}\n"
            f"⏱ {parsed['time']}\n\n"
            "Nice work 💪"
        )

        return True, reply, parsed

    # ---------------- WALK ----------------
    if WALK_PATTERN.match(text.strip()):
        parsed = {
            "type": "WALK",
            "event": event,
            "distance": None,
            "time": text.strip(),
        }

        reply = (
            f"✅ *{event}* walk submitted!\n\n"
            f"🚶 {parsed['time']}\n\n"
            "Lekker one 👌"
        )

        return True, reply, parsed

    # ---------------- INVALID ----------------
    return False, (
        "❌ Submission format not recognised.\n\n"
        "🏃 *Run:* `5km 24:30 CODE`\n"
        "🚶 *Walk:* `45:30`"
    ), None