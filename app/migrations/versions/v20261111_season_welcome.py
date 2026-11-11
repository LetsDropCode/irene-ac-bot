"""Track the last season introduced to a member; preserve all result data."""

VERSION = "2026-11-11-season-welcome-v1"


def upgrade(cur):
    cur.execute("ALTER TABLE members ADD COLUMN IF NOT EXISTS last_seen_season INTEGER")
