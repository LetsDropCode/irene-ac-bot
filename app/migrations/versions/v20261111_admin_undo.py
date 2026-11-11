"""Version result edits so a confirmed undo cannot overwrite a newer change."""

VERSION = "2026-11-11-admin-undo-v1"


def upgrade(cur):
    cur.execute("ALTER TABLE submissions ADD COLUMN IF NOT EXISTS revision BIGINT NOT NULL DEFAULT 0")
    cur.execute("""
        CREATE OR REPLACE FUNCTION bump_submission_revision() RETURNS trigger AS $$
        BEGIN
            NEW.revision := OLD.revision + 1;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER submissions_revision BEFORE UPDATE ON submissions
        FOR EACH ROW EXECUTE FUNCTION bump_submission_revision();
        ALTER TABLE admin_corrections
            ADD COLUMN IF NOT EXISTS before_state JSONB,
            ADD COLUMN IF NOT EXISTS after_revision BIGINT;
    """)
