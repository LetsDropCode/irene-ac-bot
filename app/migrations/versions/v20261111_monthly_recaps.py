"""Monthly recaps are a separate, default-off message preference."""

VERSION = "2026-11-11-monthly-recaps-v1"


def upgrade(cur):
    cur.execute("""
        ALTER TABLE members
        ADD COLUMN IF NOT EXISTS recaps_opt_in BOOLEAN NOT NULL DEFAULT FALSE
    """)
