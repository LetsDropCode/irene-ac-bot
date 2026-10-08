# Scheduled Jobs

## Wednesday unfinished-result reminders

The Railway production function `jobs-runner` calls authenticated
`POST /jobs/run` every five minutes (`*/5 * * * *`, UTC). Its source is
`scripts/jobs_run_cron.ts`; its `JOB_RUNNER_URL` and `JOB_RUNNER_TOKEN` variables
reference the `web` service rather than containing copied secrets. Check the
function's execution logs for `status: ok`, and `/health` for pending or failed
queue jobs. Railway cron functions must exit after each call.

Each run between **11:00 and 13:00 Africa/Johannesburg on Wednesday** queues
at most one durable reminder per unfinished Tuesday submission. Delivery
rechecks consent, the member's `REMINDERS ON` setting, the submission's pending
status, and the deadline. Repeated runs are deduplicated.

If the regular job runner is not scheduled during that window, run this once
at 11:00 Wednesday instead, then run `POST /jobs/run` to deliver the queue:

```sh
venv/bin/python scripts/send_incomplete_submission_reminders.py
```

Members opt in with `REMINDERS ON` and can stop messages with `REMINDERS OFF`.
Both reminders and private attendance-milestone messages default to off.
Members can opt into milestones with `MILESTONES ON`, stop them with
`MILESTONES OFF`, and request their current/longest TT streak with `MY STREAK`.

These are proactive WhatsApp messages, so create and obtain approval for two
message templates in WhatsApp Manager before enabling delivery. Configure:

```text
WHATSAPP_REMINDER_TEMPLATE_NAME=irene_tt_result_reminder
WHATSAPP_MILESTONE_TEMPLATE_NAME=irene_tt_attendance_milestone
WHATSAPP_TEMPLATE_LANGUAGE=en_GB
```

The reminder template body uses one parameter (`{{1}}` = first name). Suggested
copy: “Hi {{1}}, your Tuesday TT result is unfinished. Complete it before 13:00
today. Reply RESUME to continue or REMINDERS OFF to stop reminders.” The
milestone template body uses two parameters (`{{1}}` = total TT check-ins,
`{{2}}` = current weekly streak). Suggested copy: “You have {{1}} TT check-ins
and a current weekly streak of {{2}}. Reply MILESTONES OFF to stop these
messages.” Match the configured language to the approved templates. If a
template is missing or rejected, the durable job fails and is visible in queue
health; no free-form proactive-message fallback is attempted.

## Next-day TT leaderboard

Run this as a scheduled job on Wednesday mornings after Tuesday TT:

```sh
venv/bin/python scripts/send_next_day_leaderboard.py
```

Recommended schedule:

```text
0 8 * * 3
```

Timezone:

```text
Africa/Johannesburg
```

The job sends yesterday's TT leaderboard only to members who checked in for that TT
and have not opted out of leaderboard sharing.

## Monthly TT attendance dashboard

Run this at the end of every month after the final TT check-ins have closed:

```sh
venv/bin/python scripts/send_monthly_attendance_report.py
```

Recommended schedule:

```text
Last day of the month, 21:30
```

Timezone:

```text
Africa/Johannesburg
```

The job emails a dashboard to the configured `ATTENDANCE_REPORT_RECIPIENTS`
(there is no built-in recipient default). It includes month-to-date and year-to-date attendance statistics plus a
YTD CSV attachment of members who checked in with the correct TT code.

Required email environment variables:

```text
SMTP_HOST
SMTP_PORT
SMTP_USERNAME
SMTP_PASSWORD
SMTP_FROM_EMAIL
```

Optional overrides:

```text
ATTENDANCE_REPORT_RECIPIENTS=reports@example.org,operations@example.org
SMTP_USE_TLS=true
```

If the scheduler runs on the first day of the next month instead, use:

```sh
venv/bin/python scripts/send_monthly_attendance_report.py --previous-month
```
