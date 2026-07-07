from app.db import get_cursor
from app.services.job_queue_service import get_queue_health


def get_system_health():
    try:
        with get_cursor(commit=False) as cur:
            cur.execute("""
                SELECT
                    (CURRENT_TIMESTAMP AT TIME ZONE 'Africa/Johannesburg')::date AS sa_date,
                    (
                        SELECT COUNT(*)
                        FROM submissions
                        WHERE event_date IS NULL
                    ) AS submissions_missing_event_date
            """)
            row = cur.fetchone()
            queue = get_queue_health()
    except Exception as exc:
        return {
            "status": "error",
            "checks": {
                "database": {
                    "status": "error",
                    "detail": str(exc),
                }
            },
        }

    missing_event_dates = row["submissions_missing_event_date"] if row else None
    queue_status = "degraded" if queue["failed_jobs"] else "ok"
    status = "ok" if missing_event_dates == 0 and queue_status == "ok" else "degraded"

    return {
        "status": status,
        "checks": {
            "database": {
                "status": "ok",
                "sa_date": row["sa_date"] if row else None,
            },
            "submissions_event_date": {
                "status": "ok" if missing_event_dates == 0 else "degraded",
                "missing_rows": missing_event_dates,
            },
            "job_queue": {
                "status": queue_status,
                **queue,
            },
        },
    }
