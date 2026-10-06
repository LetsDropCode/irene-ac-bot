"""Separate opt-ins for proactive TT reminders and attendance messages."""

VERSION = "2026-10-06-engagement-preferences-v1"


def upgrade(cur):
    cur.execute("""
        ALTER TABLE members
        ADD COLUMN IF NOT EXISTS reminders_opt_in BOOLEAN NOT NULL DEFAULT FALSE;
    """)
    cur.execute("""
        ALTER TABLE members
        ADD COLUMN IF NOT EXISTS milestones_opt_in BOOLEAN NOT NULL DEFAULT FALSE;
    """)
