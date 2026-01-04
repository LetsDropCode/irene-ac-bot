# app/db.py
import sqlite3
from pathlib import Path

# 🔒 Hard-pinned DB location
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_db():
    return get_conn()


def init_db():
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
    # Event codes
    # ----------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS event_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event TEXT NOT NULL,
            code TEXT NOT NULL,
            event_date TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    # ----------------------------
    # Event configuration
    # ----------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS event_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event TEXT NOT NULL,
            day_of_week INTEGER NOT NULL,
            open_time TEXT NOT NULL,
            close_time TEXT NOT NULL,
            active INTEGER DEFAULT 1
        )
    """)

    # Seed defaults
    cur.execute("SELECT COUNT(*) FROM event_config")
    if cur.fetchone()[0] == 0:
        cur.executemany("""
            INSERT INTO event_config (event, day_of_week, open_time, close_time)
            VALUES (?, ?, ?, ?)
        """, [
            ("TT", 1, "17:00", "22:00"),
            ("WEDLSD", 2, "17:00", "22:00"),
            ("SUNSOCIAL", 6, "05:30", "22:00")
        ])

    conn.commit()
    conn.close()