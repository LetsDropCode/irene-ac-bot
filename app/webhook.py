# app/webhook.py
from fastapi import APIRouter, Request
from app.config import VERIFY_TOKEN

router = APIRouter()

@router.get("/webhook")
async def verify_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return int(challenge)

    return {"error": "Verification failed"}


@router.post("/webhook")
async def receive_webhook(request: Request):
    payload = await request.json()
    print("Incoming WhatsApp payload:")
    print(payload)
    return {"status": "received"}