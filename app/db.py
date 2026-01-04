import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path("data.db")

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def now_iso():
    return datetime.utcnow().isoformat()