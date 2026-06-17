# app/whatsapp.py

import os
import requests
from typing import Dict, Any

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
CONNECT_TIMEOUT = float(os.getenv("WHATSAPP_CONNECT_TIMEOUT", "2"))
READ_TIMEOUT = float(os.getenv("WHATSAPP_READ_TIMEOUT", "5"))

_session = requests.Session()


def _graph_url() -> str:
    return f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"


# ─────────────────────────────────────────────
# INTERNAL SEND HELPER (HARD LOGGING)
# ─────────────────────────────────────────────
def _send(payload: Dict[str, Any]) -> bool:
    message_type = payload.get("type")
    recipient = payload.get("to")
    print(f"📨 WhatsApp send attempt: type={message_type} to={recipient}")

    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        print("❌ WhatsApp ENV VARS MISSING")
        print("WHATSAPP_TOKEN present:", bool(WHATSAPP_TOKEN))
        print("PHONE_NUMBER_ID:", PHONE_NUMBER_ID)
        return False

    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        response = _session.post(
            _graph_url(),
            json=payload,
            headers=headers,
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        )

        print("📤 WhatsApp response")
        print("Status:", response.status_code)
        if not response.ok:
            print("Body:", response.text)

        return response.ok

    except requests.RequestException as e:
        print("❌ WhatsApp send exception:", str(e))
        return False


# ─────────────────────────────────────────────
# BASIC TEXT MESSAGE
# ─────────────────────────────────────────────
def send_text(to: str, text: str) -> bool:
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {
            "body": text
        },
    }
    return _send(payload)


# ─────────────────────────────────────────────
# MAIN MENU LIST
# ─────────────────────────────────────────────
def send_main_menu_list(to: str, admin: bool = False) -> bool:
    rows = [
        {
            "id": "menu_submit",
            "title": "Submit TT result",
            "description": "Check in and submit tonight's TT.",
        },
        {
            "id": "menu_profile",
            "title": "My profile",
            "description": "View or edit your details.",
        },
        {
            "id": "menu_progress",
            "title": "My progress",
            "description": "See your latest activity, PBs and milestones.",
        },
        {
            "id": "menu_leaderboard",
            "title": "Leaderboard",
            "description": "See tonight's results.",
        },
        {
            "id": "menu_overall_leaderboard",
            "title": "Overall leaderboard",
            "description": "Fastest 8km, 6km and 4km PBs.",
        },
        {
            "id": "menu_edit_profile",
            "title": "Edit details",
            "description": "Change your name or participation type.",
        },
        {
            "id": "menu_opt_out",
            "title": "Stop sharing",
            "description": "Opt out of leaderboard sharing.",
        },
    ]

    if admin:
        rows.extend([
            {
                "id": "admin_tt_code",
                "title": "TT code",
                "description": "Get tonight's TT code.",
            },
            {
                "id": "admin_tt_status",
                "title": "TT status",
                "description": "View participants and pending results.",
            },
            {
                "id": "admin_pending",
                "title": "Pending",
                "description": "List checked-in members still pending.",
            },
        ])

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": "Irene AC Bot"},
            "body": {"text": "Choose what you’d like to do."},
            "footer": {"text": "You can also type HELP anytime."},
            "action": {
                "button": "Open menu",
                "sections": [
                    {
                        "title": "Member options",
                        "rows": rows,
                    }
                ],
            },
        },
    }
    return _send(payload)


# ─────────────────────────────────────────────
# PARTICIPATION BUTTONS (RUNNER / WALKER / BOTH)
# ─────────────────────────────────────────────
def send_participation_buttons(to: str):
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": "How do you usually participate?"},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "RUNNER", "title": "🏃 Runner"}},
                    {"type": "reply", "reply": {"id": "WALKER", "title": "🚶 Walker"}},
                    {"type": "reply", "reply": {"id": "BOTH", "title": "🔄 Both"}},
                ]
            },
        },
    }
    _send(payload)


# ─────────────────────────────────────────────
# PROFILE ACTION BUTTONS
# ─────────────────────────────────────────────
def send_profile_buttons(to: str, body: str):
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "edit_name", "title": "Edit name"}},
                    {"type": "reply", "reply": {"id": "edit_type", "title": "Change type"}},
                ]
            },
        },
    }
    _send(payload)


# ─────────────────────────────────────────────
# DISTANCE BUTTONS (4 / 6 / 8 km)
# ─────────────────────────────────────────────
def send_distance_buttons(to: str) -> None:
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": "Select your TT distance:"
            },
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": "4km",
                            "title": "🏃 4 km"
                        }
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": "6km",
                            "title": "🏃 6 km"
                        }
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": "8km",
                            "title": "🏃 8 km"
                        }
                    },
                ]
            },
        },
    }
    _send(payload)


# ─────────────────────────────────────────────
# BOTH MEMBER SUBMISSION TYPE BUTTONS
# ─────────────────────────────────────────────
def send_both_submission_buttons(to: str) -> None:
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": "What would you like to submit?"
            },
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": "submit_distance",
                            "title": "📏 Distance"
                        }
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": "submit_workout",
                            "title": "🚶 Workout"
                        }
                    },
                ]
            },
        },
    }
    _send(payload)


# ─────────────────────────────────────────────
# CONFIRM / EDIT BUTTONS
# ─────────────────────────────────────────────
def send_confirm_buttons(
    to: str,
    distance: str,
    time: str,
) -> None:
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": (
                    "Please confirm your Time Trial:\n\n"
                    f"📏 Distance: {distance} km\n"
                    f"⏱ Time: {time}"
                )
            },
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": "confirm",
                            "title": "✅ Confirm"
                        }
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": "edit",
                            "title": "✏️ Edit"
                        }
                    },
                ]
            },
        },
    }
    _send(payload)
