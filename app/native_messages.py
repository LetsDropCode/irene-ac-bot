"""Pure builders for the supported subset of native session messages.

No transport here: callers must use whatsapp._send or the transactional queue.
Identifiers are supplied by the caller, never synthesized from row positions.
"""

from copy import deepcopy


def bounded(value, maximum, field):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"Invalid {field} (1–{maximum} characters required)")
    return value


def reply_buttons(to, body, choices):
    if not 1 <= len(choices) <= 3:
        raise ValueError("Reply buttons require 1–3 choices")
    ids, titles = set(), set()
    buttons = []
    for action_id, title in choices:
        bounded(action_id, 256, "button ID")
        bounded(title, 20, "button title")
        if action_id != action_id.strip() or action_id in ids or title in titles:
            raise ValueError("Button IDs and titles must be unique")
        ids.add(action_id)
        titles.add(title)
        buttons.append({"type": "reply", "reply": {"id": action_id, "title": title}})
    return {"messaging_product": "whatsapp", "to": to, "type": "interactive", "interactive": {
        "type": "button", "body": {"text": bounded(body, 1024, "body")},
        "action": {"buttons": buttons},
    }}


def selection_list(to, body, sections, *, button="Choose", header=None, footer=None):
    if not 1 <= len(sections) <= 10 or not 1 <= sum(len(s["rows"]) for s in sections) <= 10:
        raise ValueError("Lists require 1–10 total rows in 1–10 sections")
    ids = set()
    for section in sections:
        bounded(section["title"], 24, "section title")
        if not section["rows"]:
            raise ValueError("List sections cannot be empty")
        for row in section["rows"]:
            bounded(row["id"], 200, "row ID")
            bounded(row["title"], 24, "row title")
            if "description" in row:
                bounded(row["description"], 72, "row description")
            if row["id"] in ids:
                raise ValueError("List row IDs must be unique")
            ids.add(row["id"])
    interactive = {"type": "list", "body": {"text": bounded(body, 1024, "body")},
                   "action": {"button": bounded(button, 20, "list button"), "sections": deepcopy(sections)}}
    if header:
        interactive["header"] = {"type": "text", "text": bounded(header, 60, "header")}
    if footer:
        interactive["footer"] = {"text": bounded(footer, 60, "footer")}
    return {"messaging_product": "whatsapp", "to": to, "type": "interactive", "interactive": interactive}


def static_flow(to, body, *, flow_id, token, cta, screen, data):
    return {"messaging_product": "whatsapp", "to": to, "type": "interactive", "interactive": {
        "type": "flow", "body": {"text": bounded(body, 1024, "body")},
        "action": {"name": "flow", "parameters": {
            "flow_message_version": "3", "flow_id": bounded(flow_id, 128, "Flow ID"),
            "flow_token": bounded(token, 256, "Flow token"), "flow_cta": bounded(cta, 20, "Flow CTA"),
            "flow_action": "navigate", "flow_action_payload": {"screen": screen, "data": deepcopy(data)},
        }},
    }}
