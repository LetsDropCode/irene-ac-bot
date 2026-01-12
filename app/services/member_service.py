# app/services/member_service.py

from app.db import get_db


def get_member(phone: str):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM members WHERE phone = %s LIMIT 1",
        (phone,),
    )
    member = cur.fetchone()

    cur.close()
    conn.close()
    return member


def create_member(phone: str):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO members (phone, first_name, last_name)
        VALUES (%s, NULL, NULL)
        RETURNING *;
        """,
        (phone,),
    )

    member = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return member


def save_member_name(phone: str, first_name: str, last_name: str):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE members
        SET first_name = %s,
            last_name = %s
        WHERE phone = %s;
        """,
        (first_name, last_name, phone),
    )

    conn.commit()
    cur.close()
    conn.close()


def has_name(member: dict) -> bool:
    return bool(member.get("first_name") and member.get("last_name"))