from app.db import get_cursor


def get_member(phone: str):
    with get_cursor() as cur:
        cur.execute("SELECT * FROM members WHERE phone=%s", (phone,))
        return cur.fetchone()


def create_member(phone: str):
    """
    Creates a new member record safely.

    IMPORTANT:
    If your DB schema enforces NOT NULL on first_name / last_name,
    we insert placeholders so the insert never fails.
    """

    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO members (phone, first_name, last_name)
            VALUES (%s, %s, %s)
            RETURNING *
            """,
            (phone, "", "")
        )
        return cur.fetchone()


def save_member_name(member_id: int, first_name: str, last_name: str):
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE members
            SET first_name = %s,
                last_name = %s
            WHERE id = %s
            """,
            (first_name, last_name, member_id)
        )


def save_participation_type(member_id: int, participation_type: str):
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE members
            SET participation_type = %s
            WHERE id = %s
            """,
            (participation_type, member_id)
        )


def acknowledge_popia(sender: str):
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE members
            SET popia_acknowledged = TRUE
            WHERE phone = %s
            """,
            (sender,)
        )


def opt_out_leaderboard(sender: str):
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE members
            SET leaderboard_opt_out = TRUE
            WHERE phone = %s
            """,
            (sender,)
        )