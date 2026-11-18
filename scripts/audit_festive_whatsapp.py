"""Read-only capability/provisioning audit. No sends, uploads or publication.

Default: local configuration only. --remote performs GET requests to Meta;
never prints tokens, phone numbers, private keys, Flow IDs or template bodies.
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import requests
from dotenv import load_dotenv

load_dotenv()
from app.services.festive_config import capabilities


def audit(remote=False):
    caps = capabilities()
    report = {
        "provider": caps["provider"],
        "api_type": "WhatsApp Business Platform Cloud API",
        "configured_graph_version": caps["graph_version"],
        "flow_json_version": "7.3",
        "data_api_version": "4.0",
        "configured_festive_flows": {k: bool(v) for k, v in caps["flow_ids"].items()},
        "private_key_configured": bool(os.getenv("FESTIVE_FLOW_PRIVATE_KEY_PATH")),
        "template_configured": bool(os.getenv("FESTIVE_NOTIFICATION_TEMPLATE")),
        "remote_checked": remote,
    }
    if not remote:
        return report
    token = os.getenv("WHATSAPP_TOKEN")
    phone_id = os.getenv("PHONE_NUMBER_ID")
    if not token or not phone_id:
        report["remote_error"] = "WHATSAPP_TOKEN and PHONE_NUMBER_ID are required"
        return report
    headers = {"Authorization": f"Bearer {token}"}

    def get(path, fields=None):
        try:
            response = requests.get(
                f"https://graph.facebook.com/v22.0/{path}",
                params={"fields": fields} if fields else None,
                headers=headers,
                timeout=(3, 10),
            )
            value = response.json()
            if not response.ok:
                return {
                    "http_status": response.status_code,
                    "error_code": value.get("error", {}).get("code"),
                }
            return value
        except (requests.RequestException, ValueError):
            return {"error": "Remote audit unavailable"}

    encryption = get(f"{phone_id}/whatsapp_business_encryption")
    report["encryption_status"] = [
        {"signature_status": item.get("business_public_key_signature_status")}
        for item in encryption.get("data", [])
    ] or {
        k: v
        for k, v in encryption.items()
        if k in {"http_status", "error_code", "error"}
    }
    report["flows"] = {}
    for kind, flow_id in caps["flow_ids"].items():
        if flow_id:
            result = get(
                flow_id, "status,validation_errors,health_status,data_api_version"
            )
            report["flows"][kind] = {
                k: result.get(k)
                for k in ("status", "data_api_version", "http_status", "error_code")
                if k in result
            }
            report["flows"][kind]["validation_error_count"] = len(
                result.get("validation_errors", [])
            )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remote", action="store_true")
    args = parser.parse_args()
    print(json.dumps(audit(args.remote), indent=2))
