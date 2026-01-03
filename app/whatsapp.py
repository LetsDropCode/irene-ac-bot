# app/whatsapp.py
import os
import requests

GRAPH_API_URL = "https://graph.facebook.com/v18.0"


def send_whatsapp_message(to: str, message: str):
    """
    Send a WhatsApp text message using Meta Graph API
    """

    token = os.getenv("WHATSAPP_TOKEN")
    phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")

    # 🔎 TEMP DEBUG LOGS (safe – do not expose token value)
    print("WHATSAPP_TOKEN present:", bool(token))
    print("WHATSAPP_PHONE_NUMBER_ID:", phone_number_id)

    if not token or not phone_number_id:
        print("❌ Missing WhatsApp credentials")
        return False

    url = f"{GRAPH_API_URL}/{phone_number_id}/messages"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {
            "body": message
        }
    }

    response = requests.post(url, headers=headers, json=payload)

    print("📤 WhatsApp send status:", response.status_code)
    print("📤 WhatsApp response:", response.text)

    return response.status_code == 200