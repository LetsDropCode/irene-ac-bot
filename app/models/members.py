# app/members.py
from app.database import get_connection

def get_member_by_phone(phone_number: str):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM members WHERE phone_number = ?",
        (phone_number,)
    )

    row = cursor.fetchone()
    conn.close()
    return row

def create_member(phone_number: str, first_name: str, last_name: str):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO members (phone_number, first_name, last_name)
        VALUES (?, ?, ?)
        """,
        (phone_number, first_name, last_name)
    )

    member_id = cursor.lastrowid
    internal_member_id = f"IAC-{member_id:05d}"

    cursor.execute(
        """
        UPDATE members
        SET internal_member_id = ?
        WHERE id = ?
        """,
        (internal_member_id, member_id)
    )

    conn.commit()
    conn.close()

    return internal_member_id