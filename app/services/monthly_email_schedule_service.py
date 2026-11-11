"""Default-off monthly attendance email, using the existing durable job runner."""

from datetime import date, datetime

from app import config
from app.db import get_cursor
from app.services.engagement_service import SA_TZ
from app.services.job_queue_service import enqueue_job
from app.services.monthly_attendance_report_service import previous_month_report_date, send_monthly_attendance_report

JOB_MONTHLY_EMAIL = "monthly_attendance_email"


def email_schedule_ready():
    return bool(config.ATTENDANCE_REPORT_ENABLED and config.SMTP_HOST and config.SMTP_FROM_EMAIL
                and config.ATTENDANCE_REPORT_RECIPIENTS
                and bool(config.SMTP_USERNAME) == bool(config.SMTP_PASSWORD))


def _local_now(now=None):
    now = now or datetime.now(SA_TZ)
    return now.replace(tzinfo=SA_TZ) if now.tzinfo is None else now.astimezone(SA_TZ)


def queue_monthly_attendance_email(now=None):
    now = _local_now(now)
    if not email_schedule_ready() or not (now.day <= 3 and 14 <= now.hour < 20):
        return {"queued": 0}
    report_date = previous_month_report_date(now.date())
    key = f"monthly-attendance-email:{report_date}"
    with get_cursor() as cur:
        cur.execute("SELECT id FROM job_queue WHERE dedupe_key = %s", (key,))
        if cur.fetchone():
            return {"queued": 0}
        enqueue_job(JOB_MONTHLY_EMAIL, {"report_date": report_date.isoformat()}, dedupe_key=key, cursor=cur)
    return {"queued": 1}


def deliver_monthly_attendance_email(payload, now=None):
    now = _local_now(now)
    report_date = date.fromisoformat(payload["report_date"])
    if not email_schedule_ready() or now.day > 3 or report_date != previous_month_report_date(now.date()):
        return False
    # The normal queue's claim/lease prevents concurrent sends. The monthly
    # key survives completed jobs; no extra cron or recipient list is needed.
    send_monthly_attendance_report(report_date)
    return True
