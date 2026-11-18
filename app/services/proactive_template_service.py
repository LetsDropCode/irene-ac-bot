"""Build approved WhatsApp templates for business-initiated messages."""

import os
import re
from urllib.parse import quote


def proactive_template_payload(phone: str, template_env: str, parameters: list[str], *,
                               expected_parameters: int | None = None,
                               url_buttons: list[tuple[int, str]] | None = None) -> dict:
    """The supplied name, language and button positions must match an approved template.

    URL values are variable suffixes, never replacement domains. No template
    creation/approval or free-form proactive fallback happens here.
    """
    name = os.getenv(template_env, "").strip()
    if not name:
        raise RuntimeError(f"{template_env} must name an approved WhatsApp template")
    if not re.fullmatch(r"[a-z0-9_]{1,512}", name):
        raise ValueError("Invalid approved template name")
    if not isinstance(parameters, list) or any(not isinstance(value, str) or not value.strip() or len(value) > 32768 for value in parameters):
        raise ValueError("Template parameters must be non-empty text")
    if expected_parameters is not None and len(parameters) != expected_parameters:
        raise ValueError("Template parameter count does not match approved definition")
    components = [{"type": "body", "parameters": [{"type": "text", "text": value} for value in parameters]}]
    buttons = url_buttons or []
    if len(buttons) > 2:
        raise ValueError("This adapter supports at most two approved URL buttons")
    seen = set()
    for index, value in buttons:
        if type(index) is not int or not 0 <= index <= 9 or index in seen:
            raise ValueError("Invalid template button index")
        if not isinstance(value, str) or not value.strip() or len(value) > 1024:
            raise ValueError("Invalid template URL parameter")
        seen.add(index)
        components.append({"type": "button", "sub_type": "url", "index": str(index),
                           "parameters": [{"type": "text", "text": quote(value, safe="")}]})
    language = os.getenv("WHATSAPP_TEMPLATE_LANGUAGE", "en_US").strip() or "en_US"
    if not re.fullmatch(r"[a-z]{2,3}(?:_[A-Z]{2})?", language):
        raise ValueError("Invalid template language")
    return {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "template",
        "template": {
            "name": name,
            "language": {"code": language},
            "components": components,
        },
    }
