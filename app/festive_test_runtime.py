"""Explicit entry point for the isolated Railway festive test deployment.

Production continues to use app.main:app. This module is never imported there.
"""

import base64
import hmac
import json
import logging
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

TEST_ENVIRONMENT_ID = "930b1b8f-9404-4bf2-8b42-20981603be2f"
TEST_PHONE_ID = "1524654827389567"
TEST_WABA_ID = "1638834777722587"
TEST_DATABASE_HOST = "postgres-xp5s.railway.internal"


def install_flow_diagnostics(endpoint):
    """Log only failure categories, never tokens, signatures or request data."""
    original = endpoint.verify_token_signature

    def checked(request, secret):
        valid = original(request, secret)
        if not valid:
            value = request.get("flow_token_signature")
            reason = "missing" if value is None else "invalid"
            if value is not None and not isinstance(value, str):
                reason = "wrong_type"
            logging.getLogger(__name__).warning(
                "Festive test Flow token signature rejected: %s", reason
            )
        return valid

    endpoint.verify_token_signature = checked


def valid_unsigned_test_session(request, env):
    """Builder draft sends can omit Meta's optional per-token JWT.

    The endpoint has already authenticated the HTTP body and decrypted it.
    This exception is confined to this isolated runtime and durable test sessions.
    """
    try:
        validate_isolation(env)
        if env.get("FESTIVE_UAT_MODE") != "true":
            return False
        if "flow_token_signature" in request or request.get("version") != "4.0":
            return False
        if request.get("action") not in {"INIT", "BACK", "data_exchange"}:
            return False
        from app.db import get_cursor
        from app.services.festive_flow_service import load_session
        from app.services.festive_service import member

        with get_cursor() as cur:
            session = load_session(cur, request.get("flow_token"))
            actor = member(cur, session["member_id"])
            recipients = {p.strip() for p in env["FESTIVE_UAT_ALLOWLIST"].split(",")}
            return (
                session["kind"] in {"HOST", "JOIN", "MANAGE"}
                and actor["phone"] in recipients
            )
    except (RuntimeError, ValueError, KeyError, TypeError):
        return False


def install_test_flow_compatibility(endpoint, env):
    original = endpoint.verify_token_signature

    def checked(request, secret):
        if "flow_token_signature" not in request:
            return valid_unsigned_test_session(request, env)
        return original(request, secret)

    endpoint.verify_token_signature = checked


def validate_isolation(env):
    checks = {
        "ENV": env.get("ENV") == "test",
        "Railway test environment": env.get("RAILWAY_ENVIRONMENT_ID")
        == TEST_ENVIRONMENT_ID,
        "test phone number": env.get("PHONE_NUMBER_ID") == TEST_PHONE_ID,
        "test database": urlsplit(env.get("DATABASE_URL", "")).hostname
        == TEST_DATABASE_HOST,
    }
    for label, valid in checks.items():
        if not valid:
            raise RuntimeError(f"Festive test isolation failed: {label}")
    required = (
        "WHATSAPP_APP_SECRET",
        "WHATSAPP_TOKEN",
        "VERIFY_TOKEN",
        "JOB_RUNNER_TOKEN",
        "FESTIVE_UAT_ALLOWLIST",
        "FESTIVE_FLOW_PRIVATE_KEY_B64",
    )
    missing = [name for name in required if not env.get(name)]
    if missing:
        raise RuntimeError("Test configuration missing: " + ", ".join(missing))


def allowed_payload(payload, recipients):
    """Reject mismatched destinations and any unapproved sender in a batch."""
    try:
        entries = payload["entry"]
        if not entries or payload.get("object") != "whatsapp_business_account":
            return False
        for entry in entries:
            if entry["id"] != TEST_WABA_ID or not entry["changes"]:
                return False
            for change in entry["changes"]:
                value = change["value"]
                if value["metadata"]["phone_number_id"] != TEST_PHONE_ID:
                    return False
                if any(m["from"] not in recipients for m in value.get("messages", [])):
                    return False
        return True
    except (KeyError, TypeError, AttributeError):
        return False


def wrap_app(inner, env):
    """Guard inbound traffic before it reaches the existing application."""
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    recipients = frozenset(
        p.strip() for p in env["FESTIVE_UAT_ALLOWLIST"].split(",") if p.strip()
    )

    @app.middleware("http")
    async def test_boundary(request: Request, call_next):
        if request.url.path == "/jobs/run" and not hmac.compare_digest(
            request.headers.get("x-job-token", ""), env["JOB_RUNNER_TOKEN"]
        ):
            return JSONResponse({"detail": "Forbidden"}, status_code=403)
        if request.url.path == "/webhook" and request.method == "POST":
            raw = await request.body()
            if len(raw) > 65536:
                return JSONResponse({"detail": "Payload too large"}, status_code=413)
            try:
                valid = allowed_payload(json.loads(raw), recipients)
            except (ValueError, TypeError):
                valid = False
            if not valid:
                return JSONResponse({"status": "ignored_test_boundary"})
        return await call_next(request)

    @app.get("/webhook", response_class=PlainTextResponse)
    def verify(request: Request):
        query = request.query_params
        if query.get("hub.mode") == "subscribe" and hmac.compare_digest(
            query.get("hub.verify_token", ""), env["VERIFY_TOKEN"]
        ):
            return PlainTextResponse(query.get("hub.challenge", ""))
        return PlainTextResponse("Forbidden", status_code=403)

    # A mounted app's startup events are not run by Starlette. Forward the
    # existing startup validation explicitly after the isolated migration.
    for handler in inner.router.on_startup:
        app.add_event_handler("startup", handler)
    for handler in inner.router.on_shutdown:
        app.add_event_handler("shutdown", handler)
    app.mount("/", inner)
    return app


def main():
    # Validate before importing app.db (which otherwise loads the local .env)
    # and before any database connection or migration can happen.
    validate_isolation(os.environ)
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    pem = base64.b64decode(os.environ["FESTIVE_FLOW_PRIVATE_KEY_B64"], validate=True)
    key = serialization.load_pem_private_key(pem, password=None)
    if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 2048:
        raise RuntimeError("Test encryption requires an RSA key of at least 2048 bits")
    with tempfile.TemporaryDirectory(prefix="festive-test-key-") as directory:
        key_path = Path(directory) / "private.pem"
        with os.fdopen(
            os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"
        ) as f:
            f.write(pem)
        os.environ["FESTIVE_FLOW_PRIVATE_KEY_PATH"] = str(key_path)
        from app.migrations import upgrade_database

        upgrade_database()
        import uvicorn

        from app.main import app
        from app import festive_endpoint

        install_flow_diagnostics(festive_endpoint)
        install_test_flow_compatibility(festive_endpoint, os.environ)

        uvicorn.run(
            wrap_app(app, os.environ),
            host="0.0.0.0",
            port=int(os.getenv("PORT", "8080")),
        )


if __name__ == "__main__":
    main()
