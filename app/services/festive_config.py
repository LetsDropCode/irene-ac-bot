"""Runtime kill switches; no production activation during imports or migration."""

import os


def flag(name, default="false"):
    return os.getenv(name, default).lower() in {"true", "1", "yes"}


def enabled(phone=None):
    if not flag("FESTIVE_RUNS_ENABLED"):
        return False
    if flag("FESTIVE_UAT_MODE", "true") and phone is not None:
        return phone in {
            v.strip()
            for v in os.getenv("FESTIVE_UAT_ALLOWLIST", "").split(",")
            if v.strip()
        }
    return True


def capabilities(client="auto"):
    """Cloud API contract, separate from account provisioning and client ability.

    Webhooks do not identify OS/client Flow compatibility. Explicit fallback is
    offered; never infer Android/iOS capabilities from a phone number.
    """
    native = client != "text" and flag("FESTIVE_INTERACTIVE_ENABLED", "true")
    ids = {
        kind: os.getenv(f"FESTIVE_{kind}_FLOW_ID", "").strip()
        for kind in ("HOST", "JOIN", "MANAGE")
    }
    ready = bool(
        os.getenv("FESTIVE_FLOW_PRIVATE_KEY_PATH")
        or os.getenv("FESTIVE_FLOW_PRIVATE_KEY_B64")
    ) and flag("FESTIVE_FLOWS_READY")
    return {
        "provider": "meta_cloud",
        "graph_version": "v22.0",
        "list_rows": 10,
        "reply_buttons": 3,
        "native": native,
        "location": native,
        "flows": native and client != "no_flow" and ready,
        "flow_ids": ids,
        "flow_json_version": "7.3",
        "data_api_version": "4.0",
    }
