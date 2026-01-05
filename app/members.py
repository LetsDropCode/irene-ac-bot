# app/members.py
from app.db import get_db


def get_member_by_phone(phone: str):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM members WHERE phone = %s",
        (phone,)
    )

    member = cur.fetchone()
    cur.close()
    conn.close()
    return member


def create_member(phone: str, first_name: str, last_name: str):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO members (phone, first_name, last_name)
        VALUES (%s, %s, %s)
        RETURNING id
        """,
        (phone, first_name, last_name)
    )

    member_id = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    conn.close()
    return member_id