from app.db import get_cursor
from app.db import get_db

def get_member(phone: str):
    with get_cursor() as cur:
        cur.execute("SELECT * FROM members WHERE phone=%s", (phone,))
        return cur.fetchone()


def create_member(phone: str):
    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO members (phone)
            VALUES (%s)
            RETURNING *
        """, (phone,))
        return cur.fetchone()


def save_member_name(member_id: int, first_name: str, last_name: str):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE members
        SET first_name = %s,
            last_name = %s
        WHERE id = %s
        """,
        (first_name, last_name, member_id)
    )

    conn.commit()
    cur.close()
    conn.close()
    
def save_participation_type(member_id: int, participation_type: str):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE members
        SET participation_type = %s
        WHERE id = %s
        """,
        (participation_type, member_id)
    )

    conn.commit()
    cur.close()
    conn.close()
def acknowledge_popia(sender: str):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE members
        SET popia_acknowledged = TRUE
        WHERE phone = %s
        """,
        (sender,)
    )

    conn.commit()
    cur.close()
    conn.close()

def opt_out_leaderboard(sender: str):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE members
        SET leaderboard_opt_out = TRUE
        WHERE phone = %s
        """,
        (sender,)
    )

    conn.commit()
    cur.close()
    conn.close()