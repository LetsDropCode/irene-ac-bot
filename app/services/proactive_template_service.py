"""Build approved WhatsApp templates for business-initiated messages."""

import os


def proactive_template_payload(phone: str, template_env: str, parameters: list[str]) -> dict:
    name = os.getenv(template_env, "").strip()
    if not name:
        raise RuntimeError(f"{template_env} must name an approved WhatsApp template")
    language = os.getenv("WHATSAPP_TEMPLATE_LANGUAGE", "en_US").strip() or "en_US"
    return {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "template",
        "template": {
            "name": name,
            "language": {"code": language},
            "components": [{
                "type": "body",
                "parameters": [{"type": "text", "text": value} for value in parameters],
            }],
        },
    }
