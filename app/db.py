# app/db.py
import sqlite3
from pathlib import Path

DB_PATH = Path("data/irene_ac.db")
DB_PATH.parent.mkdir(exist_ok=True)

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    # Members
    cur.execute("""
    CREATE TABLE IF NOT EXISTS members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phone TEXT UNIQUE NOT NULL,
        first_name TEXT NOT NULL,
        last_name TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Submissions
    cur.execute("""
    CREATE TABLE IF NOT EXISTS submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        member_id INTEGER NOT NULL,
        event TEXT NOT NULL,
        distance TEXT NOT NULL,
        time TEXT NOT NULL,
        seconds INTEGER NOT NULL,
        is_pb INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (member_id) REFERENCES members(id)
    )
    """)

    # Event codes
    cur.execute("""""
    CREATE TABLE IF NOT EXISTS event_codes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event TEXT NOT NULL,
        code TEXT NOT NULL,
        valid_date DATE NOT NULL,
        created_at TEXT NOT NULL
    );
    """)
    
            
    conn.commit()
    conn.close()