from app.db import get_db

def get_member(phone: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM members WHERE phone=%s", (phone,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row

def create_member(phone: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO members (phone, first_name, last_name, popia_acknowledged, leaderboard_opt_out)
        VALUES (%s, NULL, NULL, FALSE, FALSE)
        RETURNING *;
        """,
        (phone,)
    )
    row = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return row

def save_member_name(phone, first, last):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE members SET first_name=%s, last_name=%s WHERE phone=%s",
        (first, last, phone)
    )
    conn.commit()
    cur.close()
    conn.close()

def has_name(member) -> bool:
    return bool(member["first_name"] and member["last_name"])

def acknowledge_popia(phone):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE members SET popia_acknowledged=TRUE WHERE phone=%s",
        (phone,)
    )
    conn.commit()
    cur.close()
    conn.close()

def opt_out_leaderboard(phone):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE members SET leaderboard_opt_out=TRUE WHERE phone=%s",
        (phone,)
    )
    conn.commit()
    cur.close()
    conn.close()