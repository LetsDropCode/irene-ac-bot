# app/whatsapp.py

import os
import json
import requests
from typing import Dict, Any

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

GRAPH_URL = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"


# ─────────────────────────────────────────────
# INTERNAL SEND HELPER (HARD LOGGING)
# ─────────────────────────────────────────────
def _send(payload: Dict[str, Any]) -> None:
    print("📨 WhatsApp send attempt payload:")
    print(json.dumps(payload, indent=2))

    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        print("❌ WhatsApp ENV VARS MISSING")
        print("WHATSAPP_TOKEN present:", bool(WHATSAPP_TOKEN))
        print("PHONE_NUMBER_ID:", PHONE_NUMBER_ID)
        return

    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            GRAPH_URL,
            json=payload,
            headers=headers,
            timeout=10,
        )

        print("📤 WhatsApp response")
        print("Status:", response.status_code)
        print("Body:", response.text)

    except requests.RequestException as e:
        print("❌ WhatsApp send exception:", str(e))


# ─────────────────────────────────────────────
# BASIC TEXT MESSAGE
# ─────────────────────────────────────────────
def send_text(to: str, text: str) -> None:
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {
            "body": text
        },
    }
    _send(payload)


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