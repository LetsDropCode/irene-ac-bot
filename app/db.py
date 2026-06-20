# app/db.py

import os
import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("❌ DATABASE_URL not set")


# --------------------------------------------------
# Connection helpers
# --------------------------------------------------

def get_db():
    """
    Returns a raw psycopg2 connection.
    Used by init_db and any legacy code.
    """
    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=RealDictCursor
        )


@contextmanager
def get_cursor(commit: bool = True):
    """
    Context-managed cursor with safe commit/rollback.

    Use:
        with get_cursor() as cur:
            ... reads/writes ...
    or:
        with get_cursor(commit=True) as cur:
            ... writes ...
    or:
        with get_cursor(commit=False) as cur:
            ... read only ...
    """
    conn = get_db()
    cur = conn.cursor()

    try:
        yield cur
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()
        

# --------------------------------------------------
# Database initialisation & migrations
# --------------------------------------------------

def init_db():
    print("🚀 Initialising database...")

    conn = get_db()
    cur = conn.cursor()

    # ----------------------------
    # Core tables (minimal schema)
    # ----------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS members (
            id SERIAL PRIMARY KEY,
            phone TEXT UNIQUE NOT NULL,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS submissions (
            id SERIAL PRIMARY KEY,
            member_id INTEGER NOT NULL REFERENCES members(id),
            activity TEXT NOT NULL,
            distance_text TEXT,
            time_text TEXT NOT NULL,
            seconds INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS event_codes (
            id SERIAL PRIMARY KEY,
            event TEXT NOT NULL,
            code TEXT NOT NULL,
            event_date DATE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS event_config (
            id SERIAL PRIMARY KEY,
            event TEXT NOT NULL,
            day_of_week INTEGER NOT NULL,
            open_time TEXT NOT NULL,
            close_time TEXT NOT NULL,
            active INTEGER DEFAULT 1
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id SERIAL PRIMARY KEY,
            member_id INTEGER NOT NULL REFERENCES members(id),
            event TEXT NOT NULL,
            event_date DATE NOT NULL,
            source TEXT NOT NULL DEFAULT 'whatsapp',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT attendance_member_event_date_unique
                UNIQUE (member_id, event, event_date)
        );
    """)

    # ----------------------------
    # SAFE migrations
    # ----------------------------
    cur.execute("""
        ALTER TABLE members
        ADD COLUMN IF NOT EXISTS participation_type TEXT;
    """)

    cur.execute("""
        ALTER TABLE members
        ADD COLUMN IF NOT EXISTS profile_state TEXT;
    """)

    cur.execute("""
        ALTER TABLE members
        ADD COLUMN IF NOT EXISTS popia_acknowledged BOOLEAN DEFAULT FALSE;
    """)

    cur.execute("""
        ALTER TABLE members
        ADD COLUMN IF NOT EXISTS leaderboard_opt_out BOOLEAN DEFAULT FALSE;
    """)

    cur.execute("""
        ALTER TABLE members
        ADD COLUMN IF NOT EXISTS last_seen_whats_new_version TEXT;
    """)

    cur.execute("""
        ALTER TABLE submissions
        ADD COLUMN IF NOT EXISTS mode TEXT;
    """)

    cur.execute("""
        ALTER TABLE submissions
        ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'PENDING';
    """)

    cur.execute("""
        ALTER TABLE submissions
        ADD COLUMN IF NOT EXISTS tt_code TEXT;
    """)

    cur.execute("""
        ALTER TABLE submissions
        ADD COLUMN IF NOT EXISTS tt_code_verified BOOLEAN DEFAULT FALSE;
    """)

    cur.execute("""
        ALTER TABLE submissions
        ADD COLUMN IF NOT EXISTS confirmed BOOLEAN DEFAULT FALSE;
    """)

    cur.execute("""
        ALTER TABLE attendance
        ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'whatsapp';
    """)

    cur.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'attendance_member_event_date_unique'
            ) THEN
                ALTER TABLE attendance
                ADD CONSTRAINT attendance_member_event_date_unique
                UNIQUE (member_id, event, event_date);
            END IF;
        END $$;
    """)

    # Backfills (idempotent)
    cur.execute("""
        UPDATE members
        SET participation_type = 'RUNNER'
        WHERE participation_type IS NULL;
    """)

    cur.execute("""
        UPDATE submissions
        SET mode = 'RUN'
        WHERE mode IS NULL;
    """)

    cur.execute("""
        UPDATE submissions
        SET status = 'PENDING'
        WHERE status IS NULL;
    """)

    # ----------------------------
    # Performance indexes
    # ----------------------------
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_submissions_member_created_at
        ON submissions (member_id, created_at DESC);
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_submissions_status_created_at
        ON submissions (status, created_at DESC);
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_submissions_distance_seconds_complete
        ON submissions (distance_text, seconds)
        WHERE status = 'COMPLETE'
          AND seconds IS NOT NULL
          AND distance_text IS NOT NULL
          AND distance_text <> '';
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_event_codes_event_date_code
        ON event_codes (event_date, code);
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_attendance_event_date
        ON attendance (event, event_date);
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_attendance_member_event_date
        ON attendance (member_id, event, event_date);
    """)

    # ----------------------------
    # Seed events (safe)
    # ----------------------------
    cur.execute("SELECT COUNT(*) AS count FROM event_config;")
    if cur.fetchone()["count"] == 0:
        cur.executemany("""
            INSERT INTO event_config (event, day_of_week, open_time, close_time)
            VALUES (%s, %s, %s, %s)
        """, [
            ("TT", 1, "17:00", "22:00"),
            ("WEDLSD", 2, "17:00", "22:00"),
            ("SUNSOCIAL", 6, "05:30", "22:00"),
        ])

    conn.commit()
    cur.close()
    conn.close()

    print("✅ Database ready")
