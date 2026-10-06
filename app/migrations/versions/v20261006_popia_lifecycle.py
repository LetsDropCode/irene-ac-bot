"""Record consent transitions without altering existing member choices."""

VERSION = "2026-10-06-popia-lifecycle-v1"


def upgrade(cur):
    cur.execute("""
        ALTER TABLE members
        ADD COLUMN IF NOT EXISTS popia_consented_at TIMESTAMP;
    """)
    cur.execute("""
        ALTER TABLE members
        ADD COLUMN IF NOT EXISTS popia_withdrawn_at TIMESTAMP;
    """)
    # Historical acknowledgements have no trustworthy original timestamp.
    # Leave those NULL instead of inventing one.
