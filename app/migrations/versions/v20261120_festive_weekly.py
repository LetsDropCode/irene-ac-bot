"""Add only digest revisions and their optional admin delivery receipts."""

VERSION = "2026-11-20-festive-weekly-v1"


def upgrade(cur):
    cur.execute("""
        CREATE TABLE festive_weekly_editions (
            id BIGSERIAL PRIMARY KEY,
            week_start DATE NOT NULL CHECK (week_start IN
                ('2026-12-07','2026-12-14','2026-12-21','2026-12-28')),
            week_end DATE NOT NULL CHECK (week_end = week_start + 6),
            revision INTEGER NOT NULL CHECK (revision > 0),
            content_hash TEXT NOT NULL,
            source_snapshot JSONB NOT NULL,
            messages JSONB NOT NULL,
            correction_messages JSONB NOT NULL DEFAULT '[]',
            changes JSONB NOT NULL DEFAULT '[]',
            status TEXT NOT NULL CHECK (status IN
                ('GENERATED','READY_FOR_REVIEW','APPROVED','POSTED','OUTDATED','FAILED')),
            generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            approved_at TIMESTAMPTZ,
            posted_at TIMESTAMPTZ,
            posted_by INTEGER REFERENCES members(id) ON DELETE SET NULL,
            delivery_status TEXT NOT NULL DEFAULT 'ADMIN_SHARING'
                CHECK (delivery_status IN ('ADMIN_SHARING','ADMIN_CONFIRMED')),
            provider_message_id TEXT,
            last_error TEXT,
            UNIQUE (week_start, revision)
        );
        CREATE TABLE festive_weekly_subscriptions (
            member_id INTEGER PRIMARY KEY REFERENCES members(id) ON DELETE CASCADE,
            opt_in BOOLEAN NOT NULL DEFAULT FALSE,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TABLE festive_weekly_notices (
            id BIGSERIAL PRIMARY KEY,
            edition_id BIGINT NOT NULL REFERENCES festive_weekly_editions(id),
            recipient_member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
            status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN
                ('PENDING','BLOCKED_TEMPLATE','SENDING','ACCEPTED','FAILED','UNCERTAIN','SUPPRESSED','SIMULATED')),
            provider_message_id TEXT,
            last_error TEXT,
            attempted_at TIMESTAMPTZ,
            UNIQUE (edition_id, recipient_member_id)
        );
    """)
