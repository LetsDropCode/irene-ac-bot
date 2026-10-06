"""Add a stable key for retry-safe outbound jobs."""

VERSION = "2026-10-06-outbound-dedupe-v1"


def upgrade(cur):
    cur.execute("""
        ALTER TABLE job_queue ADD COLUMN IF NOT EXISTS dedupe_key TEXT;
    """)
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_job_queue_dedupe_key
        ON job_queue (dedupe_key);
    """)
