# app/db.py
import sqlite3
from pathlib import Path

# -------------------------
# Database location
# -------------------------
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "irene_ac.db"


# -------------------------
# Connection helpers
# -------------------------
def get_connection():
    """
    Returns a SQLite connection with row access by column name
    """
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def get_db():
    """
    Unified DB accessor used by services
    """
    return get_connection()


# -------------------------
# DB initialisation
# -------------------------
def init_db():
    """
    Create all required tables if they do not exist.
    Safe to run multiple times.
    """
    conn = get_connection()
    cur = conn.cursor()

    # ---- Members ----
    cur.execute("""
        CREATE TABLE IF NOT EXISTS members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT UNIQUE NOT NULL,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ---- Submissions ----
    cur.execute("""
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER NOT NULL,
            event TEXT NOT NULL,
            distance TEXT NOT NULL,
            time TEXT NOT NULL,
            seconds INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (member_id) REFERENCES members(id)
        )
    """)

    # ---- Event codes (TT / WedLSD / SunSocial) ----
    cur.execute("""
        CREATE TABLE IF NOT EXISTS event_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event TEXT NOT NULL,
            code TEXT NOT NULL,
            valid_from TIMESTAMP NOT NULL,
            valid_to TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()