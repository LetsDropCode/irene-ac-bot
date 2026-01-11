# app/whatsapp.py
import os
import requests

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

GRAPH_URL = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"


def _send(payload: dict):
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        print("❌ WhatsApp env vars missing")
        return

    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }

    response = requests.post(GRAPH_URL, json=payload, headers=headers)

    print("📤 WhatsApp response:", response.status_code, response.text)


# ─────────────────────────────────────────────
# BASIC TEXT
# ─────────────────────────────────────────────
def send_text(to: str, text: str):
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }
    _send(payload)


# ─────────────────────────────────────────────
# DISTANCE BUTTONS (4 / 6 / 8 km)
# ─────────────────────────────────────────────
def send_distance_buttons(to: str):
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
                        "reply": {"id": "4km", "title": "🏃 4 km"}
                    },
                    {
                        "type": "reply",
                        "reply": {"id": "6km", "title": "🏃 6 km"}
                    },
                    {
                        "type": "reply",
                        "reply": {"id": "8km", "title": "🏃 8 km"}
                    },
                ]
            },
        },
    }
    _send(payload)


# ─────────────────────────────────────────────
# CONFIRM / EDIT BUTTONS
# ─────────────────────────────────────────────
def send_confirm_buttons(to: str, distance: str, time: str):
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": (
                    f"Please confirm your TT:\n\n"
                    f"📏 Distance: {distance} km\n"
                    f"⏱ Time: {time}"
                )
            },
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {"id": "confirm", "title": "✅ Confirm"}
                    },
                    {
                        "type": "reply",
                        "reply": {"id": "edit", "title": "✏️ Edit"}
                    },
                ]
            },
        },
    }
    _send(payload)