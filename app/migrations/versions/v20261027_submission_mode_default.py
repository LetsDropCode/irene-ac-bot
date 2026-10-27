"""Remove the legacy RUN default that misclassifies walker check-ins."""

VERSION = "2026-10-27-submission-mode-default-v1"


def upgrade(cur):
    # An unselected mode uses the member's participation preference. BOTH
    # members choose their mode explicitly; save_distance/save_workout then
    # persist it.
    cur.execute("ALTER TABLE submissions ALTER COLUMN mode DROP DEFAULT")
    # Recover walkers already stuck before entering any result. Never change
    # a recorded distance, workout note, completed result, or BOTH selection.
    cur.execute("""
        UPDATE submissions AS s
        SET mode = 'WORKOUT'
        FROM members AS m
        WHERE s.member_id = m.id
          AND m.participation_type = 'WALKER'
          AND s.mode = 'RUN'
          AND s.status = 'PENDING'
          AND COALESCE(s.distance_text, '') = ''
          AND COALESCE(s.time_text, '') = ''
          AND COALESCE(s.seconds, 0) = 0
    """)
