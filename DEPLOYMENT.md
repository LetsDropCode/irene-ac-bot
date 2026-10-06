# Deployment Guide

This app is a FastAPI WhatsApp bot for Irene AC TT. The web process is:

```sh
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

The current `Procfile` already uses that command.

Use Python **3.13.5** locally, in CI, and for deployment. `.python-version`
is the development/CI selector; `runtime.txt` retains the deployment selector.
The unit suite checks that the two files match. Install from the pinned
`requirements.txt` and run `python -m pip check` after installation. The
explicit `tzdata` dependency keeps `Africa/Johannesburg` available on systems
without a system IANA time-zone database.

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

`ENV` is required and must be exactly `development`, `test`, or `production`.

`META_APP_SECRET` can be used instead of `WHATSAPP_APP_SECRET`.

Optional app settings:

```text
# Required in production (comma-separated E.164-style numbers, no +).
ADMIN_NUMBERS=27...,27...
JOB_RUNNER_BATCH_SIZE=10
WHATSAPP_CONNECT_TIMEOUT=2
WHATSAPP_READ_TIMEOUT=5
WHATS_NEW_VERSION=2026-06-shop-league-menu
WHATS_NEW_MESSAGE=...
PUBLIC_BASE_URL=https://your-public-app-domain
```

`PUBLIC_BASE_URL` lets the bot send the Irene tree logo to first-time members. On Railway it is inferred from `RAILWAY_PUBLIC_DOMAIN` when this setting is omitted.

Optional OpenAI coaching (the bot uses deterministic coaching when the key is omitted or the API is unavailable):

```text
OPENAI_API_KEY
OPENAI_MODEL=gpt-4o-mini
OPENAI_MAX_TOKENS=120
OPENAI_TIMEOUT=6
```

Coaching requests contain only distance, finish time, calculated pace, trend,
and the deterministic fatigue signal. Responses are not stored by the OpenAI
API (`store=false`), and provider output is limited to four short lines.

Trend and fatigue signals compare only runs over the same distance in the
five most recent valid running results. At least three matching results are
required; otherwise the trend is "Not enough comparable runs yet" and no
fatigue signal is supplied. Coaching uses the confirmed result's distance;
My Progress uses the most recent run's distance.

The saved-result reply and `MY PROGRESS` also show a deterministic private
comparison with the preceding TT at the same numeric distance. After four
comparable results, a rolling pace line compares the average seconds/km of
the latest three results with the immediately preceding three-result window
(the windows overlap by two results). Pace is rounded to the nearest second
per km; no AI output is used to calculate or label this line. Historical
completed results remain eligible even if their legacy `confirmed` flag is
unset.

Monthly attendance email:

```text
SMTP_HOST
SMTP_PORT=587
SMTP_USERNAME
SMTP_PASSWORD
SMTP_FROM_EMAIL
SMTP_USE_TLS=true
ATTENDANCE_REPORT_RECIPIENTS=reports@example.org,operations@example.org
```

## Database Migrations

The web process does not change the schema at startup. Before starting a new
release, run this once against that release's `DATABASE_URL`:

```sh
python -m app.migrations upgrade
```

The command applies pending versions in order within one transaction and uses a
PostgreSQL advisory lock so concurrent invocations cannot apply the same version
at the same time. Repeating it after success is safe. The web process checks the
recorded versions at startup and refuses to start if a migration is pending.

The initial version adopts an existing database or creates a new one. It covers:

- members and submissions
- event codes and attendance
- admin correction audit records
- inbound WhatsApp idempotency records
- durable job queue

The next version adds the outbound queue deduplication key. The POPIA lifecycle
version adds consent and withdrawal timestamps for new transitions; historical
consents remain undated rather than being assigned a fictional date. Before applying
migrations to an existing database, take a database backup. The initial adoption
also performs the previous one-time cleanup of duplicate event codes and duplicate
pending submissions.

The engagement-preferences version adds separate, default-off opt-ins for
Wednesday incomplete-result reminders and private attendance milestones.

Add future changes as new modules in `app/migrations/versions/` and list them in
`app/migrations/__init__.py`; do not edit a version after it has been deployed.

## Member Privacy Lifecycle

`PRIVACY` explains the bot's data use. `MY DATA` sends the member their stored
profile and TT result summary to their WhatsApp number. `DELETE MY DATA` (or
`WITHDRAW CONSENT`) immediately disables consent, hides public results and
removes queued messages for that member. The bot then requires the exact reply
`CONFIRM DELETE` before atomically removing the member, submissions, attendance,
correction drafts/history, inbound sender identifiers and matching queued payloads.
Opaque inbound message IDs are retained to reject delayed webhook retries, so
an old `OK` cannot recreate a deleted profile.
`CANCEL DELETE` stops erasure but does **not** restore consent; the member must
send `OK` to opt in again. The final confirmation is sent directly so it does
not recreate a persistent outbound record for the erased number.

This erases the app's active PostgreSQL records. It does not erase previously
sent WhatsApp messages, emailed reports, provider logs, or database backups.
The club must separately define and operate retention, backup expiry, and
handling of any copies outside the app; do not claim those copies are erased
by this command. Make a backup before migrating, but restrict access to it and
honour the applicable retention/deletion policy.

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

In production and hosted non-test environments, startup fails if the app secret,
WhatsApp token, phone-number ID, verify token, job-runner token, or production
admin numbers are absent. Missing or invalid signatures are rejected. Local
unsigned-webhook bypasses are limited to explicit development/test operation.

## Health Checks

Configure the hosting platform's process/liveness check as:

```text
GET /live
```

It returns HTTP `200` while the app process can respond, even if a queue job has
failed. Use `GET /ready` for database readiness: it returns HTTP `200` when the
database responds and HTTP `503` when it does not.

Use `GET /health` for operational details. It returns HTTP `200` with status
`ok` or `degraded`, and HTTP `503` with status `error` when the database is
unavailable. Do not use `/health` as a liveness probe.

The detailed health check covers:

- database access
- missing `submissions.event_date` rows
- job queue counts
- failed jobs
- oldest pending job age

## Job Runner

Durable background work is stored in `job_queue`.
All WhatsApp replies and campaign messages are persisted there before they are
sent. The runner must remain scheduled for members to receive messages; a webhook
also requests an immediate short drain after it queues its replies. Repeated
webhook deliveries and repeated next-day leaderboard runs reuse their existing
outbound jobs rather than creating duplicates.

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
DATE RANGE LEADERBOARD
```

Selecting **Date range** under Admin tools → Leaderboard views prompts for an
inclusive period. Send either `YYYY-MM-DD to YYYY-MM-DD` or the day-first
`DD/MM/YYYY to DD/MM/YYYY` format. The bot returns each historical TT night's
actual leaderboard separately; use the same start and end date for one Tuesday.

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

Wednesday unfinished-result reminders are queued automatically by `POST /jobs/run`
from 11:00 until 13:00 Africa/Johannesburg, then drained by that same runner.
Keep the runner scheduled during this window. Members must send `REMINDERS ON`
to opt in. `MILESTONES ON` enables private check-in/streak messages, and
`MY STREAK` works on demand without a proactive-message opt-in.
Before enabling proactive delivery, create and approve the reminder and
milestone WhatsApp templates, then set `WHATSAPP_REMINDER_TEMPLATE_NAME`,
`WHATSAPP_MILESTONE_TEMPLATE_NAME`, and `WHATSAPP_TEMPLATE_LANGUAGE` as
described in [docs/scheduled-jobs.md](docs/scheduled-jobs.md). The bot uses
approved templates rather than free-form text for these business-initiated
messages.

Monthly attendance dashboard:

```sh
python scripts/send_monthly_attendance_report.py
```

## CI

GitHub Actions runs on push and pull request:

```text
.github/workflows/ci.yml
```

It installs dependencies, verifies their compatibility, compiles Python files,
and runs the unit suite on pinned Ubuntu and macOS runners using Python 3.13.5.
A separate Ubuntu/PostgreSQL 16 integration job applies the
migrations before running tests. It uses an
ephemeral GitHub Actions PostgreSQL service and never uses Railway:

```sh
python -m compileall app scripts tests
python -m unittest discover -s tests
python -m app.migrations upgrade
python -m unittest discover -s tests/integration -p '*_integration.py'
```

## PostgreSQL Integration Tests

Integration tests require PostgreSQL **16** and a disposable database. They
drop and recreate the `public` schema before each test, so never point them at
a shared, staging, or production database.

```sh
export DATABASE_URL=postgresql://irene_test:irene_test@localhost:5432/irene_integration
export INTEGRATION_DATABASE_URL="$DATABASE_URL"
python -m unittest discover -s tests/integration -p '*_integration.py'
```

The suite refuses to run unless `INTEGRATION_DATABASE_URL` names a database
containing `test` or `integration`.

## Deploy Checklist

1. Confirm all required environment variables are set.
2. Confirm `ENV=production`.
3. Confirm `WHATSAPP_APP_SECRET` or `META_APP_SECRET` is set.
4. Confirm `JOB_RUNNER_TOKEN` is set.
5. Back up the database, then run `python -m app.migrations upgrade` as a pre-deploy step.
6. Deploy the web process.
7. Confirm `/live` and `/ready` return HTTP `200`, and review `/health` for warnings.
8. Configure scheduler for `POST /jobs/run`.
9. Configure scheduled leaderboard and monthly report jobs.
10. Send a test WhatsApp message.
11. Use admin command `JOBS STATUS` to confirm the queue is healthy.

## Rollback Notes

App rollback is usually safe when database changes are backward-compatible.

Be careful with these database changes:

- `submissions.event_date` is now required.
- one pending submission per member/event date is enforced.
- inbound message IDs are stored for idempotency.
- queued jobs may remain pending after deploy rollback.
- older app versions that still run startup DDL should not be used after a
  migration that removes or renames columns they expect.

If a deploy fails:

1. Check `/live`, `/ready`, and `/health`.
2. Check app logs for startup DB errors.
3. Use `JOBS FAILED` from WhatsApp admin tools.
4. Roll back the app version if needed.
5. Do not manually delete queued jobs unless you are sure they are unsafe to retry.

## Secret Hygiene

If any secrets were ever committed to Git history, rotate them. `.gitignore` prevents
future local files from being tracked, but it does not remove old secrets from history.
