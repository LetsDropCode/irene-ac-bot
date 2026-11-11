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

Manual report command (use only when requested; the automatic trigger described below replaces a separate monthly email cron):

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

## Personal monthly recap (optional)

No new cron is needed: authenticated `POST /jobs/run` also queues personal
recaps on days **1–3 of each month, 14:00–20:00 Africa/Johannesburg**. The
three-day window permits catch-up after a short outage. Waiting until 14:00
lets a final Tuesday result be completed before Wednesday's 13:00 cutoff.
The recap covers the **previous calendar month**, including December at a
January rollover.

Apply the `2026-11-11-monthly-recaps-v1` migration before deploying this release.
It adds only `members.recaps_opt_in`, defaulting to false for everyone.

Members use:

- `MY GOAL`: progress toward three TT check-ins in the current month. Missing
  a week does not reset progress. The goal also appears in the check-in reply
  and `MY PROGRESS`; it creates no additional message.
- `MY RECAP`: the last completed month's check-ins, completed activities,
  recorded kilometres, goal outcome and any improved running PBs.
- `RECAPS ON` / `RECAPS OFF`: a separate preference for automatic recaps.
  These commands do not change reminder or milestone preferences.

Walkers and runners count equally toward the goal. Recorded distance is
summed only from structured 4/6/8 km results; free-text walks are never
estimated. PB comparisons use the same running distance against the best
completed TT before the recap month. Attendance and results are counted
separately, so an unfinished result does not lose its attendance credit.

On-demand views work without a template. To enable automatic delivery, obtain
approval in WhatsApp Manager for this six-parameter template and configure:

```text
WHATSAPP_MONTHLY_RECAP_TEMPLATE_NAME=irene_tt_monthly_recap
WHATSAPP_TEMPLATE_LANGUAGE=en_GB
```

Suggested template body (match the approved language):

```text
Your requested Irene AC TT monthly summary for {{1}}.
TT check-ins: {{2}}
Completed activities: {{3}}
Recorded distance: {{4}} km (free-text walks are not estimated).
Monthly goal of 3 check-ins: {{5}}
Personal best update: {{6}}
Reply RECAPS OFF to stop monthly summaries.
```

Parameters are month/year, attendance count, completed activities, recorded
kilometres, goal outcome, and PB highlights (or a note that no new timed running best was recorded).

Without the template setting, the scheduler skips recaps and `RECAPS ON`
explains that automatic recaps are not yet available. No free-form proactive
fallback is used. Only consented, opted-in members with at least one TT
check-in in the recap month are eligible, regardless of public leaderboard
visibility. Empty months do not generate messages.

Queue keys are unique per member and calendar month. Delivery rechecks consent
and opt-in under a member lock. `RECAPS OFF` removes pending/failed recap jobs;
consent withdrawal removes all member jobs. Retries after day 3 or for an old
month are discarded. Failed sends use the existing queue retry and health
reporting. As with other outbound jobs, a crash after WhatsApp accepts a
message but before the queue records completion can cause a repeated send.

## Compact admin event summary

`TT STATUS` and the `ADMIN` dashboard share the same current-date summary:
check-ins, submitted results, outstanding results, participation types, first
recorded TTs, attendance milestones and monthly goals reached that day.
Outstanding results include check-ins without a submission row. Completed
walk/workout notes count as submissions. The first five outstanding members
and first three milestones are shown, with an overflow count and a link to
the existing `PENDING` tools. This is an on-demand view, with no new admin
notifications or configuration.

Submit or check the recap template using the bot's production credentials:

```sh
railway run --service web --environment production --no-local \
  venv/bin/python scripts/configure_monthly_recap_template.py \
  --waba-id 4252184618398067 --submit
```

Omit `--submit` for a read-only status check. The script verifies account
ownership, includes six sample values, and reuses an existing matching
template without editing or resubmitting it. Meta determines the final
category and approval status. Configure the template name only after the
script reports `APPROVED` for `en_GB`.

## Automatic monthly email trigger (admin workflow upgrade)

The existing authenticated `/jobs/run` runner now supports the monthly
attendance email. It is **off by default**. No extra cron service is needed.
On days 1–3, from 14:00 to 20:00 Africa/Johannesburg, it queues one report for
the last day of the previous calendar month. The delay accommodates the final
Tuesday's Wednesday result deadline; the additional days allow catch-up.

Before enabling, configure the `web` service with:

```text
ATTENDANCE_REPORT_ENABLED=false
SMTP_HOST=<mail provider host>
SMTP_PORT=587
SMTP_USERNAME=<mail account>
SMTP_PASSWORD=<provider credential>
SMTP_FROM_EMAIL=<approved sender>
SMTP_USE_TLS=true
ATTENDANCE_REPORT_RECIPIENTS=<existing approved recipient list>
```

Set `ATTENDANCE_REPORT_ENABLED=true` only when the sender and recipients are
ready. Missing host/sender/recipients or incomplete login settings prevent
queueing. The existing SMTP implementation also supports a trusted relay
without username/password. The standalone report script remains available
for an explicitly requested manual send; its `--dry-run` builds without sending.
Do not keep a separate monthly cron alongside the built-in trigger.

The job type is `monthly_attendance_email`; its unique key contains the report
end date. Completed jobs prevent a second scheduled send for that month.
Delivery rechecks enablement, configuration and report age. Errors use the
existing retries and appear in `JOBS FAILED`; `DONE` records SMTP acceptance,
not final inbox delivery. A process crash after SMTP accepts the email but
before job completion is recorded can still cause a repeated send on retry.
A job skipped after disabling or expiry stays completed; re-enabling does not
retroactively send that report.

Production configuration inspection on 11 November 2026 found the five-minute
Railway job runner, no monthly email cron in Railway or the local crontab,
one report recipient, and no SMTP host, sender or login configuration. No email
was sent during inspection. The new trigger must remain off until configured.
