"""Allow check-ins to wait for the member's activity selection on legacy DBs."""

VERSION = "2026-10-27-submission-mode-nullable-v1"


def upgrade(cur):
    # The older production schema required a mode even though the current
    # check-in flow inserts NULL until the activity is selected. Removing the
    # RUN default alone did not remove that independent legacy constraint.
    cur.execute("ALTER TABLE submissions ALTER COLUMN mode DROP NOT NULL")
