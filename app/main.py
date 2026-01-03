# app/main.py
from fastapi import FastAPI
from app.webhook import router as webhook_router
from app.config import ENV

app = FastAPI()

app.include_router(webhook_router)

@app.get("/")
async def root():
    return {
        "status": "ok",
        "message": "Irene AC Bot is running",
        "env": ENV
    }