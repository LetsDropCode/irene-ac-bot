# app/main.py
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from app.webhook import router as webhook_router
from app.config import ENV, JOB_RUNNER_BATCH_SIZE, JOB_RUNNER_TOKEN
from app.db import init_db
from app.services.health_service import get_system_health
from app.services.job_queue_service import run_due_jobs

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


@app.post("/jobs/run")
def run_jobs(x_job_token: str | None = Header(default=None)):
    if JOB_RUNNER_TOKEN and x_job_token != JOB_RUNNER_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")

    if not JOB_RUNNER_TOKEN and ENV != "development":
        raise HTTPException(status_code=503, detail="JOB_RUNNER_TOKEN is not configured")

    processed = run_due_jobs(JOB_RUNNER_BATCH_SIZE)
    return {
        "status": "ok",
        "processed": processed,
    }
