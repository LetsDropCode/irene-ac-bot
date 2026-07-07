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
            event_date DATE NOT NULL,
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
        ALTER TABLE submissions
        ADD COLUMN IF NOT EXISTS event_date DATE;
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS admin_corrections (
            id SERIAL PRIMARY KEY,
            admin_member_id INTEGER REFERENCES members(id),
            submission_id INTEGER NOT NULL REFERENCES submissions(id),
            member_id INTEGER NOT NULL REFERENCES members(id),
            old_distance_text TEXT,
            old_time_text TEXT,
            old_seconds INTEGER,
            new_distance_text TEXT,
            new_time_text TEXT,
            new_seconds INTEGER,
            reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS inbound_whatsapp_messages (
            message_id TEXT PRIMARY KEY,
            sender TEXT,
            status TEXT NOT NULL DEFAULT 'RECEIVED',
            received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed_at TIMESTAMP,
            error TEXT
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS job_queue (
            id SERIAL PRIMARY KEY,
            job_type TEXT NOT NULL,
            payload JSONB NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            run_after TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            locked_at TIMESTAMP,
            last_error TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    cur.execute("""
        DELETE FROM event_codes a
        USING event_codes b
        WHERE a.id > b.id
          AND a.event = b.event
          AND a.event_date = b.event_date;
    """)

    cur.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'event_codes_event_date_unique'
            ) THEN
                ALTER TABLE event_codes
                ADD CONSTRAINT event_codes_event_date_unique
                UNIQUE (event, event_date);
            END IF;
        END $$;
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

    cur.execute("""
        UPDATE submissions
        SET event_date = COALESCE(
            (
                created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Johannesburg'
            )::date,
            (CURRENT_TIMESTAMP AT TIME ZONE 'Africa/Johannesburg')::date
        )
        WHERE event_date IS NULL;
    """)

    cur.execute("""
        ALTER TABLE submissions
        ALTER COLUMN event_date SET NOT NULL;
    """)

    cur.execute("""
        WITH ranked_pending AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY member_id, event_date
                    ORDER BY
                        COALESCE(tt_code_verified, FALSE) DESC,
                        (
                            COALESCE(distance_text, '') <> ''
                            OR COALESCE(time_text, '') <> ''
                        ) DESC,
                        created_at DESC,
                        id DESC
                ) AS row_number
            FROM submissions
            WHERE status = 'PENDING'
        )
        UPDATE submissions s
        SET status = 'CANCELLED'
        FROM ranked_pending rp
        WHERE s.id = rp.id
          AND rp.row_number > 1;
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
        CREATE INDEX IF NOT EXISTS idx_submissions_event_date_status
        ON submissions (event_date, status);
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_submissions_member_event_date_status
        ON submissions (member_id, event_date, status);
    """)

    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_submissions_one_pending_per_member_event_date
        ON submissions (member_id, event_date)
        WHERE status = 'PENDING';
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

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_job_queue_status_run_after
        ON job_queue (status, run_after, id);
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
