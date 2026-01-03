# app/whatsapp.py
import os
import requests

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

def send_whatsapp_message(to: str, text: str):
    print("🔎 ENV CHECK")
    print("WHATSAPP_TOKEN present:", bool(WHATSAPP_TOKEN))
    print("PHONE_NUMBER_ID:", PHONE_NUMBER_ID)

    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        print("❌ Missing WhatsApp env vars")
        return

    url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"

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

    response = requests.post(url, json=payload, headers=headers)

    print("📤 WhatsApp send response:")
    print("Status:", response.status_code)
    print("Body:", response.text)