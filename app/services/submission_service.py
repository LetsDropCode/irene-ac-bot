from app.db import get_db


def get_or_create_submission(member, activity=None):
    conn = get_db()
    cur = conn.cursor()

    # Try find latest pending submission
    cur.execute("""
        SELECT *
        FROM submissions
        WHERE member_id = %s
          AND status = 'PENDING'
        ORDER BY created_at DESC
        LIMIT 1
    """, (member["id"],))

    submission = cur.fetchone()

    if submission:
        cur.close()
        conn.close()
        return submission

    # Create placeholder submission
    cur.execute("""
        INSERT INTO submissions (
            member_id,
            activity,
            mode,
            status
        )
        VALUES (%s, %s, %s, 'PENDING')
        RETURNING *
    """, (
        member["id"],
        activity,          # can be NULL initially
        "RUN"
    ))

    submission = cur.fetchone()
    conn.commit()

    cur.close()
    conn.close()

    return submission


def finalize_submission(
    submission_id,
    distance_text,
    time_text,
    seconds
):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE submissions
        SET
            distance_text = %s,
            time_text = %s,
            seconds = %s,
            status = 'COMPLETE'
        WHERE id = %s
        RETURNING *
    """, (
        distance_text,
        time_text,
        seconds,
        submission_id
    ))

    submission = cur.fetchone()
    conn.commit()

    cur.close()
    conn.close()

    return submission