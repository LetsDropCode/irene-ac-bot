# Deployment Guide

This app is a FastAPI WhatsApp bot for Irene AC TT. The web process is:

```sh
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

The current `Procfile` already uses that command.

## Required Environment Variables

Core app:

```text
DATABASE_URL
ENV=production
VERIFY_TOKEN
WHATSAPP_TOKEN
PHONE_NUMBER_ID
WHATSAPP_APP_SECRET
JOB_RUNNER_TOKEN
```

`META_APP_SECRET` can be used instead of `WHATSAPP_APP_SECRET`.

Optional app settings:

```text
ADMIN_NUMBERS=277...,278...
JOB_RUNNER_BATCH_SIZE=10
WHATSAPP_CONNECT_TIMEOUT=2
WHATSAPP_READ_TIMEOUT=5
WHATS_NEW_VERSION=2026-06-shop-league-menu
WHATS_NEW_MESSAGE=...
```

OpenAI coaching fallback:

```text
OPENAI_API_KEY
OPENAI_MODEL=gpt-4o-mini
OPENAI_MAX_TOKENS=120
OPENAI_TIMEOUT=6
```

Monthly attendance email:

```text
SMTP_HOST
SMTP_PORT=587
SMTP_USERNAME
SMTP_PASSWORD
SMTP_FROM_EMAIL
SMTP_USE_TLS=true
ATTENDANCE_REPORT_RECIPIENTS=bulllindsa@icloud.com,info@irenerunner.co.za
```

## Database Startup

On app startup, `app.db.init_db()` creates required tables, backfills safe fields,
and creates indexes/constraints. This includes:

- members and submissions
- event codes and attendance
- admin correction audit records
- inbound WhatsApp idempotency records
- durable job queue

Before major database changes, take a database backup. The next structural upgrade
should be moving these startup migrations into versioned Alembic migrations.

## Webhook Setup

Use the deployed app URL:

```text
https://<your-domain>/webhook
```

Meta webhook verification uses `VERIFY_TOKEN`.

Runtime webhook requests are protected with `X-Hub-Signature-256`. Set the Meta app
secret as:

```text
WHATSAPP_APP_SECRET=<meta app secret>
```

In production, missing or invalid signatures are rejected.

## Health Check

Use:

```text
GET /health
```

Healthy response returns HTTP `200`. Degraded/error response returns HTTP `503`.

The health check covers:

- database access
- missing `submissions.event_date` rows
- job queue counts
- failed jobs
- oldest pending job age

## Job Runner

Durable background work is stored in `job_queue`.

Run pending jobs with:

```text
POST /jobs/run
Header: x-job-token: <JOB_RUNNER_TOKEN>
```

Recommended schedule:

```text
Every 1-5 minutes
```

The endpoint processes up to `JOB_RUNNER_BATCH_SIZE` jobs per call. Default is `10`.

Admin WhatsApp commands:

```text
JOBS STATUS
JOBS RUN
JOBS FAILED
JOBS RETRY
```

## Scheduled Jobs

See [docs/scheduled-jobs.md](docs/scheduled-jobs.md) for scheduler details.

Important current behavior:

- `scripts/send_next_day_leaderboard.py` queues one WhatsApp message per checked-in recipient.
- The `/jobs/run` runner must run afterwards to send those queued messages.
- Monthly attendance report still sends email directly.

Next-day TT leaderboard:

```sh
python scripts/send_next_day_leaderboard.py
```

Recommended schedule:

```text
Wednesday 08:00 Africa/Johannesburg
```

Monthly attendance dashboard:

```sh
python scripts/send_monthly_attendance_report.py
```

## CI

GitHub Actions runs on push and pull request:

```text
.github/workflows/ci.yml
```

It installs dependencies, compiles Python files, and runs the unit test suite:

```sh
python -m compileall app scripts tests
python -m unittest discover -s tests
```

## Deploy Checklist

1. Confirm all required environment variables are set.
2. Confirm `ENV=production`.
3. Confirm `WHATSAPP_APP_SECRET` or `META_APP_SECRET` is set.
4. Confirm `JOB_RUNNER_TOKEN` is set.
5. Deploy the web process.
6. Open `/health` and confirm HTTP `200`.
7. Configure scheduler for `POST /jobs/run`.
8. Configure scheduled leaderboard and monthly report jobs.
9. Send a test WhatsApp message.
10. Use admin command `JOBS STATUS` to confirm the queue is healthy.

## Rollback Notes

App rollback is usually safe when database changes are backward-compatible.

Be careful with these database changes:

- `submissions.event_date` is now required.
- one pending submission per member/event date is enforced.
- inbound message IDs are stored for idempotency.
- queued jobs may remain pending after deploy rollback.

If a deploy fails:

1. Check `/health`.
2. Check app logs for startup DB errors.
3. Use `JOBS FAILED` from WhatsApp admin tools.
4. Roll back the app version if needed.
5. Do not manually delete queued jobs unless you are sure they are unsafe to retry.

## Secret Hygiene

If any secrets were ever committed to Git history, rotate them. `.gitignore` prevents
future local files from being tracked, but it does not remove old secrets from history.
