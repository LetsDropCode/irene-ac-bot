# app/db.py
import os
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("❌ DATABASE_URL not set")

def get_conn():
    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=RealDictCursor
    )

# Alias for service layer
def get_db():
    return get_conn()

def init_db():
    conn = get_conn()
    cur = conn.cursor()

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
            distance_text TEXT NOT NULL,
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

    cur.execute("SELECT COUNT(*) FROM event_config;")
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