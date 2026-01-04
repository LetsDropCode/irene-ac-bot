# app/members.py
import sqlite3
from datetime import datetime

DB_PATH = "data.db"


def get_connection():
    return sqlite3.connect(DB_PATH)


def get_member_by_phone(phone: str):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT id, phone, first_name, last_name FROM members WHERE phone = ?",
        (phone,),
    )
    row = cur.fetchone()
    conn.close()

    if row:
        return {
            "id": row[0],
            "phone": row[1],
            "first_name": row[2],
            "last_name": row[3],
        }

    return None


def create_member(phone: str, first_name: str, last_name: str):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO members (phone, first_name, last_name, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (phone, first_name, last_name, datetime.utcnow()),
    )

    conn.commit()
    member_id = cur.lastrowid
    conn.close()

    return member_id