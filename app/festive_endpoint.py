"""Encrypted Meta Flow data channel; no plaintext business-data endpoint."""

import base64
import hashlib
import hmac
import json
import os
import time
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.padding import MGF1, OAEP
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from starlette.concurrency import run_in_threadpool

from app.config import WHATSAPP_APP_SECRET
from app.db import get_cursor
from app.services.festive_config import enabled
from app.services.festive_flow_service import exchange, load_session
from app.services.festive_service import FestiveError

router = APIRouter()


def decrypt(body, pem, password=None):
    key = serialization.load_pem_private_key(pem, password=password)
    aes = key.decrypt(
        base64.b64decode(body["encrypted_aes_key"], validate=True),
        OAEP(mgf=MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
    )
    iv = base64.b64decode(body["initial_vector"], validate=True)
    if len(aes) != 16 or len(iv) != 16:
        raise ValueError("Invalid key or IV size")
    raw = AESGCM(aes).decrypt(
        iv, base64.b64decode(body["encrypted_flow_data"], validate=True), None
    )
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise TypeError("Invalid payload")
    return data, aes, iv


def encrypt(response, aes, iv):
    return base64.b64encode(
        AESGCM(aes).encrypt(
            bytes(b ^ 255 for b in iv), json.dumps(response).encode(), None
        )
    ).decode()


def verify_token_signature(request, secret):
    """HS256 only; token binding and standard temporal claims where supplied."""
    try:
        header, payload, signature = request["flow_token_signature"].split(".")
        decode = lambda value: base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        if json.loads(decode(header)).get("alg") != "HS256":
            return False
        expected = hmac.new(
            secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256
        ).digest()
        claims = json.loads(decode(payload))
        return (
            hmac.compare_digest(expected, decode(signature))
            and claims.get("flow_token") == request.get("flow_token")
            and claims.get("exp", time.time() + 1) > time.time()
            and claims.get("nbf", 0) <= time.time()
        )
    except (KeyError, ValueError, TypeError, AttributeError):
        return False


def process(raw):
    key_path = os.getenv("FESTIVE_FLOW_PRIVATE_KEY_PATH", "")
    encoded_key = os.getenv("FESTIVE_FLOW_PRIVATE_KEY_B64", "")
    if not key_path and not encoded_key:
        raise HTTPException(503, "Flow encryption is not configured")
    try:
        pem = (
            Path(key_path).read_bytes()
            if key_path
            else base64.b64decode(encoded_key, validate=True)
        )
    except (OSError, ValueError):
        raise HTTPException(503, "Flow encryption is not available") from None
    try:
        password = os.getenv("FESTIVE_FLOW_PRIVATE_KEY_PASSWORD", "").encode() or None
        request, aes, iv = decrypt(json.loads(raw), pem, password)
    except (ValueError, KeyError, TypeError, InvalidTag):
        raise HTTPException(421, "Unable to decrypt") from None
    if request.get("version") != "4.0":
        raise HTTPException(400, "Data API 4.0 is required")
    # Meta documents the extra token JWT as optional. The HTTP HMAC and
    # encrypted channel remain mandatory; exchange validates the durable,
    # unexpired, member-bound session even when this additional JWT is absent.
    if (
        request.get("action") != "ping"
        and "flow_token_signature" in request
        and not verify_token_signature(request, WHATSAPP_APP_SECRET)
    ):
        raise HTTPException(432, "Invalid Flow token signature")
    data = request.get("data") or {}
    if not isinstance(data, dict):
        raise HTTPException(400, "Invalid Flow data")
    try:
        if data.get("error"):
            # Error acknowledgements must not bypass session authorization.
            with get_cursor() as cur:
                load_session(cur, request.get("flow_token"))
            response = {"data": {"acknowledged": True}}
        else:
            response = exchange(request)
    except FestiveError:
        # Session failures use Meta's token-invalid response; no user data leaked.
        raise HTTPException(427, "Open a new festive form in the chat") from None
    return encrypt(response, aes, iv)


@router.post("/festive/flows", response_class=PlainTextResponse)
async def flow_endpoint(request: Request):
    if not enabled():
        raise HTTPException(404, "Not found")
    raw = await request.body()
    if len(raw) > 65536:
        raise HTTPException(413, "Payload too large")
    expected = (
        "sha256="
        + hmac.new(
            (WHATSAPP_APP_SECRET or "").encode(), raw, hashlib.sha256
        ).hexdigest()
    )
    if not WHATSAPP_APP_SECRET or not hmac.compare_digest(
        expected, request.headers.get("x-hub-signature-256", "")
    ):
        raise HTTPException(432, "Invalid signature")
    return await run_in_threadpool(process, raw)
