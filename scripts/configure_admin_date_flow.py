"""Create/validate the admin calendar Flow; publish only with --publish.

Uses the existing WhatsApp token without sending any WhatsApp messages.
"""

import argparse
import json
from pathlib import Path
import sys

import requests
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
FLOW_NAME = "irene_admin_tt_calendar_v1"
ASSET = ROOT / "app/flows/assets/admin_tt_date.json"
BASE = "https://graph.facebook.com/v22.0"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--waba-id", required=True)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    import os
    values = {**dotenv_values(ROOT / ".env"), **os.environ}
    token = values.get("WHATSAPP_TOKEN")
    phone_id = values.get("PHONE_NUMBER_ID")
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
    flows = [row for row in rows(f"{args.waba_id}/flows", "id,name,status") if row["name"] == FLOW_NAME]
    if len(flows) > 1:
        raise RuntimeError("Multiple matching calendar Flows exist; select the intended Flow in WhatsApp Manager")
    flow = flows[0] if flows else request("POST", f"{args.waba_id}/flows", data={
        "name": FLOW_NAME, "categories": json.dumps(["OTHER"]),
    })
    flow_id = flow["id"]
    print("Calendar Flow ID:", flow_id, flush=True)
    if flow.get("status") != "PUBLISHED":
        with ASSET.open("rb") as source:
            result = request("POST", f"{flow_id}/assets", data={"name": "flow.json", "asset_type": "FLOW_JSON"},
                             files={"file": ("flow.json", source, "application/json")})
        errors = result.get("validation_errors", [])
        if errors:
            print(json.dumps(errors, indent=2))
            raise RuntimeError("Calendar Flow validation failed; not published")
        if not result.get("success"):
            raise RuntimeError("Meta did not confirm the Flow asset upload; not published")
        print("Calendar JSON validated by Meta.", flush=True)
        if args.publish:
            result = request("POST", f"{flow_id}/publish")
            if not result.get("success"):
                raise RuntimeError("Meta did not confirm publication")
    status = request("GET", flow_id, params={"fields": "id,status,validation_errors"})
    print("Flow status:", status.get("status"))
    if args.publish and status.get("status") != "PUBLISHED":
        raise RuntimeError("Calendar Flow is not published")
    print(f"After publication, configure WHATSAPP_ADMIN_DATE_FLOW_ID={flow_id} on the bot service.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, requests.RequestException) as exc:
        # Requests exceptions may embed URLs; none of these URLs contain tokens.
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
