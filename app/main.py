# app/main.py
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from app.webhook import router as webhook_router
from app.config import ENV
from app.db import init_db
from app.services.health_service import get_system_health

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
    result = get_system_health()
    status_code = 200 if result["status"] == "ok" else 503
    return JSONResponse(result, status_code=status_code)
