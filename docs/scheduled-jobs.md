# Scheduled Jobs

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

The job emails a dashboard to `bulllindsa@icloud.com` and `info@irenerunner.co.za`
by default. It includes month-to-date and year-to-date attendance statistics plus a
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
ATTENDANCE_REPORT_RECIPIENTS=bulllindsa@icloud.com,info@irenerunner.co.za
SMTP_USE_TLS=true
```

If the scheduler runs on the first day of the next month instead, use:

```sh
venv/bin/python scripts/send_monthly_attendance_report.py --previous-month
```
