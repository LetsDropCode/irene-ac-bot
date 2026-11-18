"""Shared Graph API addressing and sanitized delivery error classification."""

import os
import re


def graph_base_url(version=None):
    version = version if version is not None else os.getenv("WHATSAPP_GRAPH_API_VERSION", "v22.0")
    if not isinstance(version, str) or not re.fullmatch(r"v[1-9][0-9]*\.0", version):
        raise ValueError("WHATSAPP_GRAPH_API_VERSION must look like v22.0")
    return "https://graph.facebook.com/" + version


class MetaSendError(RuntimeError):
    """Only numeric codes and our own labels may enter persisted diagnostics."""

    def __init__(self, category, *, permanent=False, status=None, code=None):
        self.permanent = permanent
        self.category = category
        super().__init__(f"Meta send {category}; HTTP={status}; code={code}")


def response_error(status, data):
    error = data.get("error", {}) if isinstance(data, dict) else {}
    error = error if isinstance(error, dict) else {}
    code = error.get("code")
    code = code if type(code) is int else None
    if code in {190, 102} or status == 401:
        return MetaSendError("credentials", permanent=True, status=status, code=code)
    if code in {10, 200, 131005} or status == 403:
        return MetaSendError("permission", permanent=True, status=status, code=code)
    if status == 429 or status >= 500 or error.get("is_transient") is True or code in {1, 2, 4, 17, 80007, 130429, 131000, 131016, 131048, 131056}:
        return MetaSendError("transient", status=status, code=code)
    return MetaSendError("rejected", permanent=400 <= status < 500, status=status, code=code)
