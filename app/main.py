# app/main.py
from fastapi import FastAPI
from app.webhook import router as webhook_router
from app.config import ENV
from app.db import init_db

app = FastAPI()

@app.on_event("startup")
def startup():
    init_db()

app.include_router(webhook_router)

@app.get("/")
def read_root():
    return {
        "status": "ok",
        "env": ENV
    }

@app.get("/health")
def health():
    return {"status": "ok"}