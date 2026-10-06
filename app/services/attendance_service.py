# app/services/attendance_service.py
from app.db import get_cursor
from app.services.job_queue_service import JOB_ATTENDANCE_MILESTONE, enqueue_job


def mark_attendance(member_id: int, event: str = "TT", source: str = "whatsapp"):
    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO attendance (member_id, event, event_date, source)
            VALUES (
                %s,
                %s,
                (CURRENT_TIMESTAMP AT TIME ZONE 'Africa/Johannesburg')::date,
                %s
            )
            ON CONFLICT (member_id, event, event_date)
            DO UPDATE SET source = EXCLUDED.source
            RETURNING *
        """, (member_id, event, source))

        attendance = cur.fetchone()
        if event == "TT" and attendance:
            cur.execute(
                "SELECT milestones_opt_in, popia_acknowledged FROM members WHERE id = %s",
                (member_id,),
            )
            member = cur.fetchone()
            if member and member["popia_acknowledged"] and member["milestones_opt_in"]:
                event_date = attendance["event_date"]
                enqueue_job(
                    JOB_ATTENDANCE_MILESTONE,
                    {"member_id": member_id, "event_date": event_date.isoformat()},
                    dedupe_key=f"attendance-milestone:{member_id}:{event_date.isoformat()}",
                    cursor=cur,
                )
        return attendance
