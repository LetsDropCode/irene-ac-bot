"""Inspect the monthly recap template, or submit it to Meta with --submit.

Uses the existing WhatsApp credentials. Never sends messages or changes opt-ins.
"""

import argparse
import json
import os
from pathlib import Path
import sys

import requests
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://graph.facebook.com/v22.0"
TEMPLATE_NAME = "irene_tt_monthly_recap"
TEMPLATE_BODY = (
    "Your requested Irene AC TT monthly summary for {{1}}.\n"
    "TT check-ins: {{2}}\n"
    "Completed activities: {{3}}\n"
    "Recorded distance: {{4}} km (free-text walks are not estimated).\n"
    "Monthly goal of 3 check-ins: {{5}}\n"
    "Personal best update: {{6}}\n"
    "Reply RECAPS OFF to stop monthly summaries."
)
EXAMPLES = ["October 2026", "3", "3", "12", "Reached", "4 km PB: 26:40 (improved by 0:18)"]


def template_payload(language):
    return {
        "name": TEMPLATE_NAME,
        "language": language,
        "category": "UTILITY",
        "components": [{"type": "BODY", "text": TEMPLATE_BODY,
                        "example": {"body_text": [EXAMPLES]}}],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--waba-id", required=True)
    parser.add_argument("--submit", action="store_true")
    args = parser.parse_args()
    values = {**dotenv_values(ROOT / ".env"), **os.environ}
    token, phone_id = values.get("WHATSAPP_TOKEN"), values.get("PHONE_NUMBER_ID")
    language = values.get("WHATSAPP_TEMPLATE_LANGUAGE", "en_GB").strip() or "en_GB"
    if not token or not phone_id:
        raise RuntimeError("WHATSAPP_TOKEN and PHONE_NUMBER_ID are required")
    session = requests.Session()
    session.headers["Authorization"] = "Bearer " + token

    def request(method, path, **kwargs):
        response = session.request(method, BASE + "/" + path, timeout=30, **kwargs)
        data = response.json()
        if not response.ok:
            error = data.get("error", {})
            message = str(error.get("message", "Request failed")).replace(token, "[redacted]")
            raise RuntimeError(f"Meta API error {error.get('code')}: {message}")
        return data

    def rows(path, fields):
        params = {"fields": fields, "limit": 100}
        while True:
            page = request("GET", path, params=params)
            yield from page.get("data", [])
            paging = page.get("paging", {})
            after = paging.get("cursors", {}).get("after")
            if not paging.get("next") or not after:
                break
            params["after"] = after

    phones = list(rows(f"{args.waba_id}/phone_numbers", "id"))
    if phone_id not in {row["id"] for row in phones}:
        raise RuntimeError("This WhatsApp account does not own the bot's phone-number ID")
    templates = list(rows(f"{args.waba_id}/message_templates", "id,name,status,language,category,components"))
    matches = [row for row in templates if row["name"] == TEMPLATE_NAME and row["language"] == language]
    if len(matches) > 1:
        raise RuntimeError("Multiple matching templates; select the intended template in WhatsApp Manager")
    if not matches:
        if not args.submit:
            print(json.dumps({"status": "NOT_CREATED", "submission": template_payload(language)}, indent=2))
            return
        created = request("POST", f"{args.waba_id}/message_templates", json=template_payload(language))
        template = request("GET", created["id"], params={"fields": "id,name,status,language,category,components"})
    else:
        template = matches[0]
    bodies = [c.get("text") for c in template.get("components", []) if c.get("type") == "BODY"]
    if bodies != [TEMPLATE_BODY]:
        raise RuntimeError("Existing template body differs from the bot's expected six-parameter template; not changed")
    print(json.dumps({key: template.get(key) for key in ("id", "name", "status", "language", "category")}, indent=2))
    if template.get("status") == "APPROVED":
        print(f"Ready to configure WHATSAPP_MONTHLY_RECAP_TEMPLATE_NAME={TEMPLATE_NAME}")
    else:
        print("Keep WHATSAPP_MONTHLY_RECAP_TEMPLATE_NAME unset until Meta reports APPROVED.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, requests.RequestException) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
