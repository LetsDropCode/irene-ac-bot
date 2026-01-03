# app/whatsapp.py
import os
import requests

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

GRAPH_URL = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"

def send_whatsapp_message(to: str, text: str):
    # 🔍 TEMP DEBUG (Step 2.3)
    print("📌 DEBUG — WhatsApp ENV CHECK")
    print("📌 PHONE_NUMBER_ID:", PHONE_NUMBER_ID)
    print("📌 WHATSAPP_TOKEN present:", bool(WHATSAPP_TOKEN))

    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        print("❌ Missing WhatsApp env vars — aborting send")
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

    response = requests.post(GRAPH_URL, json=payload, headers=headers)

    print("📤 WhatsApp send response:")
    print("📤 Status:", response.status_code)
    print("📤 Body:", response.text)