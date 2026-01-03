# app/whatsapp.py
import os
import requests

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")

GRAPH_API_URL = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"


def send_whatsapp_message(to: str, text: str):
    """
    Send a WhatsApp text message using Meta Cloud API
    """

    # ---- TEMP DEBUG (safe, no secrets exposed) ----
    print("🔍 Sending WhatsApp message")
    print("WHATSAPP_TOKEN present:", bool(WHATSAPP_TOKEN))
    print("PHONE_NUMBER_ID:", PHONE_NUMBER_ID)
    print("To:", to)
    print("Text:", text)
    # ----------------------------------------------

    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        print("❌ Missing WhatsApp credentials")
        return

    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }

    response = requests.post(GRAPH_API_URL, headers=headers, json=payload)

    print("📤 WhatsApp API status:", response.status_code)
    print("📤 WhatsApp API response:", response.text)