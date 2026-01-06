# app/services/admin_code_service.py

import random
import string
from datetime import date
from app.db import get_db
from app.services.event_detector import get_active_event


def generate_code(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


def create_event_code():
    event = get_active_event()

    if not event:
        return False, "❌ No active event right now."

    code = generate_code()

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO event_codes (event, code, event_date)
        VALUES (%s, %s, %s);
        """,
        (event, code, date.today())
    )

    conn.commit()
    cur.close()
    conn.close()

    return True, (
        f"✅ *{event}* code generated:\n\n"
        f"🔑 *{code}*\n\n"
        "Share this with runners 👌"
    )