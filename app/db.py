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
    Used by the migration runner and legacy code.
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
