# app/services/admin_codes.py
from datetime import date
from app.services.event_codes import create_event_code
from app.services.event_resolver import get_today_events

def generate_admin_code_message(now=None):
    events = get_today_events(now)

    if not events:
        return "ℹ️ No scheduled events today."

    today = date.today().isoformat()
    lines = ["📅 *Today's Run Codes*"]

    for event in events:
        code = create_event_code(event, today)
        lines.append(f"{event}: *{code}*")

    return "\n".join(lines)