# app/db.py

import sqlite3
from pathlib import Path

# -------------------------------------------------
# Persistent database location (Railway Volume)
# -------------------------------------------------
DATA_DIR = Path("/data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "data.db"


def get_conn():
    """
    Returns a SQLite connection with row access by column name.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ✅ Alias for service-layer consistency
def get_db():
    return get_conn()


def init_db():
    """
    Creates required tables if they do not exist.
    Safe to run multiple times.
    """
    conn = get_conn()
    cur = conn.cursor()

    # ----------------------------
    # Members
    # ----------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT UNIQUE NOT NULL,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ----------------------------
    # Submissions
    # ----------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER NOT NULL,
            activity TEXT NOT NULL,
            distance_text TEXT NOT NULL,
            time_text TEXT NOT NULL,
            seconds INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (member_id) REFERENCES members(id)
        )
    """)

    # ----------------------------
    # Event Codes (admin-generated)
    # ----------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS event_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event TEXT NOT NULL,              -- TT, WEDLSD, SUNSOCIAL
            code TEXT NOT NULL,
            event_date TEXT NOT NULL,         -- YYYY-MM-DD
            created_at TEXT NOT NULL
        )
    """)

    # ----------------------------
    # Event Configuration
    # ----------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS event_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event TEXT NOT NULL,               -- TT, WEDLSD, SUNSOCIAL
            day_of_week INTEGER NOT NULL,      -- Monday=0 ... Sunday=6
            open_time TEXT NOT NULL,           -- HH:MM
            close_time TEXT NOT NULL,          -- HH:MM
            active INTEGER DEFAULT 1
        )
    """)

    # ----------------------------
    # Seed default events (once)
    # ----------------------------
    cur.execute("SELECT COUNT(*) FROM event_config")
    count = cur.fetchone()[0]

    if count == 0:
        cur.executemany("""
            INSERT INTO event_config (event, day_of_week, open_time, close_time)
            VALUES (?, ?, ?, ?)
        """, [
            ("TT", 1, "17:00", "22:00"),        # Tuesday
            ("WEDLSD", 2, "17:00", "22:00"),    # Wednesday
            ("SUNSOCIAL", 6, "05:30", "22:00")  # Sunday
        ])

    conn.commit()
    conn.close()