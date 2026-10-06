"""Explicit, transactional PostgreSQL schema migrations."""

from app.db import get_cursor, get_db
from app.migrations.versions import (
    v20261006_baseline,
    v20261006_outbound_dedupe,
    v20261006_popia_lifecycle,
    v20261006_engagement_preferences,
)

MIGRATIONS = (
    v20261006_baseline,
    v20261006_outbound_dedupe,
    v20261006_popia_lifecycle,
    v20261006_engagement_preferences,
)
_MIGRATION_LOCK = 733120260106


def upgrade_database():
    """Apply unapplied revisions once, under a PostgreSQL advisory lock."""
    conn = get_db()
    cur = conn.cursor()
    applied = []
    try:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (_MIGRATION_LOCK,))
        cur.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                name TEXT PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        for migration in MIGRATIONS:
            cur.execute("SELECT 1 FROM schema_migrations WHERE name = %s", (migration.VERSION,))
            if cur.fetchone():
                continue
            migration.upgrade(cur)
            cur.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (migration.VERSION,))
            applied.append(migration.VERSION)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()
    return applied


def require_current_schema():
    """Fail startup clearly when the release's migrations have not run."""
    expected = {migration.VERSION for migration in MIGRATIONS}
    try:
        with get_cursor(commit=False) as cur:
            cur.execute("SELECT name FROM schema_migrations WHERE name = ANY(%s)", (list(expected),))
            applied = {row["name"] for row in cur.fetchall()}
    except Exception:
        raise RuntimeError(
            "Database schema is unavailable; run python -m app.migrations upgrade"
        ) from None

    if expected - applied:
        raise RuntimeError(
            "Database migrations are pending; run python -m app.migrations upgrade"
        )
