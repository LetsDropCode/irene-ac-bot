from app.db import get_db

def store_submission(
    member_id,
    activity,
    distance_text,
    time_text,
    seconds,
):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, confirmed
        FROM submissions
        WHERE member_id = %s
          AND activity = %s
          AND created_at::date = CURRENT_DATE
        ORDER BY created_at DESC
        LIMIT 1;
        """,
        (member_id, activity),
    )

    existing = cur.fetchone()

    if existing:
        if existing["confirmed"]:
            cur.close()
            conn.close()
            return "locked"

        cur.execute(
            """
            UPDATE submissions
            SET
                distance_text = %s,
                time_text = %s,
                seconds = %s,
                updated_at = NOW()
            WHERE id = %s;
            """,
            (distance_text, time_text, seconds, existing["id"]),
        )
        action = "updated"
    else:
        cur.execute(
            """
            INSERT INTO submissions (
                member_id,
                activity,
                distance_text,
                time_text,
                seconds,
                confirmed,
                created_at
            )
            VALUES (%s, %s, %s, %s, %s, FALSE, NOW());
            """,
            (member_id, activity, distance_text, time_text, seconds),
        )
        action = "created"

    conn.commit()
    cur.close()
    conn.close()

    return action


def confirm_submission(member_id, activity="TT"):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE submissions
        SET confirmed = TRUE,
            updated_at = NOW()
        WHERE id = (
            SELECT id
            FROM submissions
            WHERE member_id = %s
              AND activity = %s
              AND created_at::date = CURRENT_DATE
            ORDER BY created_at DESC
            LIMIT 1
        );
        """,
        (member_id, activity),
    )

    conn.commit()
    cur.close()
    conn.close()