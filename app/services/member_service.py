# app/services/member_service.py
from app.db import get_cursor


# ─────────────────────────────────────────────
# FETCH MEMBER
# ─────────────────────────────────────────────
def get_member(phone: str):
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM members WHERE phone = %s",
            (phone,)
        )
        return cur.fetchone()


# ─────────────────────────────────────────────
# CREATE MEMBER (SAFE DEFAULTS)
# ─────────────────────────────────────────────
def create_member(phone: str):
    """
    Creates a new member with safe placeholders.
    Prevents NOT NULL constraint failures.
    """

    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO members (phone, first_name, last_name)
            VALUES (%s, %s, %s)
            RETURNING *
            """,
            (phone, "Unknown", "Member")
        )
        return cur.fetchone()


# ─────────────────────────────────────────────
# SAVE MEMBER NAME
# ─────────────────────────────────────────────
def save_member_name(member_id: int, first_name: str, last_name: str):
    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE members
            SET first_name = %s,
                last_name = %s
            WHERE id = %s
            """,
            (first_name.strip(), last_name.strip(), member_id)
        )


# ─────────────────────────────────────────────
# PARTICIPATION TYPE
# ─────────────────────────────────────────────
def save_participation_type(member_id: int, participation_type: str):
    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE members
            SET participation_type = %s
            WHERE id = %s
            """,
            (participation_type, member_id)
        )


# ─────────────────────────────────────────────
# POPIA ACKNOWLEDGEMENT
# ─────────────────────────────────────────────
def acknowledge_popia(sender: str):
    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE members
            SET popia_acknowledged = TRUE
            WHERE phone = %s
            """,
            (sender,)
        )


# ─────────────────────────────────────────────
# LEADERBOARD OPT OUT
# ─────────────────────────────────────────────
def opt_out_leaderboard(sender: str):
    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE members
            SET leaderboard_opt_out = TRUE
            WHERE phone = %s
            """,
            (sender,)
        )


# ─────────────────────────────────────────────
# PROFILE COMPLETION CHECK (NEW)
# ─────────────────────────────────────────────
def is_profile_incomplete(member: dict) -> bool:
    """
    Central logic so webhook + campaigns use same rule.
    """

    if not member:
        return True

    first = member.get("first_name")
    last = member.get("last_name")

    if not first or not last:
        return True

    if first.lower() == "unknown" or last.lower() in {"unknown", "member"}:
        return True

    return False


# ─────────────────────────────────────────────
# GET MEMBERS NEEDING PROFILE COMPLETION (NEW)
# ─────────────────────────────────────────────
def get_members_needing_profile_update():
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, phone, first_name, last_name
            FROM members
            WHERE
                first_name IS NULL
                OR last_name IS NULL
                OR first_name = 'Unknown'
                OR last_name IN ('Unknown', 'Member')
            """
        )
        return cur.fetchall()