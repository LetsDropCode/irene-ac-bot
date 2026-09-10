# app/main.py
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from app.webhook import router as webhook_router
from app.config import ENV, JOB_RUNNER_BATCH_SIZE, JOB_RUNNER_TOKEN, validate_configuration
from app.db import init_db
from app.services.health_service import get_system_health
from app.services.job_queue_service import run_due_jobs
from app.branding import BARK, DEEP_PURPLE, LEAF_GREEN, LOGO_PATH, TURQUOISE

app = FastAPI()
app.mount("/assets", StaticFiles(directory="app/static"), name="assets")

@app.on_event("startup")
def startup():
    validate_configuration()
    init_db()

app.include_router(webhook_router)

@app.get("/")
def read_root():
    return {
        "status": "ok",
        "env": ENV
    }


@app.get("/brand", response_class=HTMLResponse, include_in_schema=False)
def brand_preview():
    """A small, public reference page for the Irene AC bot identity."""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Irene AC Bot</title><style>
body{{margin:0;font-family:Arial,sans-serif;background:#f2fbfa;color:{DEEP_PURPLE}}}
main{{max-width:680px;margin:48px auto;padding:32px;text-align:center;background:#fff;border-top:8px solid {TURQUOISE};border-radius:18px;box-shadow:0 12px 40px #342b8220}}
img{{width:116px;height:116px;object-fit:contain}} h1{{margin:12px 0 8px}} p{{color:{BARK};line-height:1.55}}
.palette{{display:flex;justify-content:center;gap:12px;margin-top:24px}} .swatch{{width:52px;height:52px;border-radius:50%}}
</style></head><body><main><img src="{LOGO_PATH}" alt="Irene Athletics Club tree logo">
<h1>Irene AC TT Bot</h1><p>Tuesday time-trial check-ins, results and progress for Irene Athletics Club.</p>
<div class="palette" aria-label="Irene AC colour palette"><i class="swatch" style="background:{TURQUOISE}"></i><i class="swatch" style="background:{LEAF_GREEN}"></i><i class="swatch" style="background:{DEEP_PURPLE}"></i><i class="swatch" style="background:{BARK}"></i></div>
</main></body></html>"""

@app.get("/health")
def health():
    result = get_system_health()
    status_code = 200 if result["status"] == "ok" else 503
    return JSONResponse(result, status_code=status_code)


@app.post("/jobs/run")
def run_jobs(x_job_token: str | None = Header(default=None)):
    if JOB_RUNNER_TOKEN and x_job_token != JOB_RUNNER_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")

    if not JOB_RUNNER_TOKEN and ENV not in {"development", "test"}:
        raise HTTPException(status_code=503, detail="JOB_RUNNER_TOKEN is not configured")

    processed = run_due_jobs(JOB_RUNNER_BATCH_SIZE)
    return {
        "status": "ok",
        "processed": processed,
    }
