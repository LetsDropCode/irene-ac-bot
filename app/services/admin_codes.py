# app/services/admin_codes.py
from app.services.event_codes import get_or_create_event_code

def generate_admin_code_message():
    events = ["TT", "WEDLSD", "SUNSOCIAL"]

    lines = ["📋 *Today’s Event Codes*"]

    for event in events:
        code = get_or_create_event_code(event)
        lines.append(f"• {event}: *{code}*")

    return "\n".join(lines)