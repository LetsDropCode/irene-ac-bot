from app.db import get_cursor


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


def save_member_name(member_id: int, first: str, last: str):
    with get_cursor() as cur:
        cur.execute("""
            UPDATE members
            SET first_name=%s, last_name=%s
            WHERE id=%s
        """, (first, last, member_id))


def save_participation_type(member_id: int, ptype: str):
    with get_cursor() as cur:
        cur.execute("""
            UPDATE members
            SET participation_type=%s
            WHERE id=%s
        """, (ptype, member_id))