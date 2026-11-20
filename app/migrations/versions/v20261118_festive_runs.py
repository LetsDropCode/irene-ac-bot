"""Isolated festive programme; never writes TT results or member preferences."""

VERSION = "2026-11-18-festive-runs-v1"
DATES = (
    "2026-12-13",
    "2026-12-15",
    "2026-12-16",
    "2026-12-17",
    "2026-12-19",
    "2026-12-20",
    "2026-12-22",
    "2026-12-23",
    "2026-12-24",
    "2026-12-27",
    "2026-12-29",
    "2026-12-30",
    "2027-01-02",
    "2027-01-03",
)


def upgrade(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS festive_run_slots (
            id SERIAL PRIMARY KEY,
            run_date DATE NOT NULL UNIQUE CHECK (run_date IN (
                '2026-12-13','2026-12-15','2026-12-16','2026-12-17','2026-12-19',
                '2026-12-20','2026-12-22','2026-12-23','2026-12-24','2026-12-27',
                '2026-12-29','2026-12-30','2027-01-02','2027-01-03')),
            status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN
                ('OPEN','HOST_ASSIGNED','DETAILS_PENDING','PENDING_APPROVAL','PUBLISHED','COMPLETED','CANCELLED')),
            revision INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS festive_run_hosts (
            id SERIAL PRIMARY KEY,
            run_slot_id INTEGER NOT NULL REFERENCES festive_run_slots(id),
            member_id INTEGER REFERENCES members(id) ON DELETE SET NULL,
            host_role TEXT NOT NULL CHECK (host_role IN ('LEAD','COHOST')),
            status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','WITHDRAWN')),
            reminder_opt_in BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CHECK (member_id IS NOT NULL OR status = 'WITHDRAWN')
        );
        CREATE UNIQUE INDEX IF NOT EXISTS festive_one_host_role
            ON festive_run_hosts(run_slot_id, host_role) WHERE status = 'ACTIVE';
        CREATE UNIQUE INDEX IF NOT EXISTS festive_one_member_role
            ON festive_run_hosts(run_slot_id, member_id) WHERE status = 'ACTIVE';
        CREATE TABLE IF NOT EXISTS festive_run_details (
            run_slot_id INTEGER PRIMARY KEY REFERENCES festive_run_slots(id),
            draft JSONB NOT NULL DEFAULT '{}',
            published JSONB,
            approval_status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (approval_status IN ('DRAFT','PENDING','APPROVED')),
            approved_by INTEGER REFERENCES members(id) ON DELETE SET NULL,
            approved_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS festive_run_rsvps (
            id SERIAL PRIMARY KEY,
            run_slot_id INTEGER NOT NULL REFERENCES festive_run_slots(id),
            member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
            selected_distance TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','WITHDRAWN')),
            reminder_opt_in BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(run_slot_id, member_id)
        );
        CREATE TABLE IF NOT EXISTS festive_run_sessions (
            token_hash TEXT PRIMARY KEY,
            member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
            kind TEXT NOT NULL CHECK (kind IN ('HOST','JOIN','MANAGE','ADMIN')),
            state JSONB NOT NULL DEFAULT '{}',
            revision INTEGER NOT NULL DEFAULT 0,
            receipts JSONB NOT NULL DEFAULT '{}',
            expires_at TIMESTAMPTZ NOT NULL DEFAULT (now() + interval '2 hours'),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS festive_sessions_member ON festive_run_sessions(member_id);
        CREATE TABLE IF NOT EXISTS festive_chat_sessions (
            member_id INTEGER PRIMARY KEY REFERENCES members(id) ON DELETE CASCADE,
            data JSONB NOT NULL DEFAULT '{}',
            expires_at TIMESTAMPTZ NOT NULL DEFAULT (now() + interval '2 hours')
        );
        CREATE TABLE IF NOT EXISTS festive_run_notifications (
            id SERIAL PRIMARY KEY,
            run_slot_id INTEGER NOT NULL REFERENCES festive_run_slots(id),
            recipient_member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
            notification_type TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN
                ('PENDING','SENDING','SENT','UNCERTAIN','SUPPRESSED','BLOCKED_TEMPLATE','SIMULATED')),
            scheduled_for TIMESTAMPTZ NOT NULL,
            sent_at TIMESTAMPTZ,
            error_details TEXT,
            provider_message_id TEXT
        );
        CREATE INDEX IF NOT EXISTS festive_notifications_due ON festive_run_notifications(status, scheduled_for);
        CREATE TABLE IF NOT EXISTS festive_run_audit (
            id BIGSERIAL PRIMARY KEY,
            run_slot_id INTEGER REFERENCES festive_run_slots(id),
            actor_member_id INTEGER REFERENCES members(id) ON DELETE SET NULL,
            action TEXT NOT NULL,
            revision INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    for day in DATES:
        cur.execute(
            "INSERT INTO festive_run_slots(run_date) VALUES (%s) ON CONFLICT (run_date) DO NOTHING",
            (day,),
        )
    # Erasure must release hosting before the FK is set null. Preserve anonymous audit.
    cur.execute("""
        CREATE OR REPLACE FUNCTION festive_member_erasure() RETURNS trigger AS $$
        BEGIN
            INSERT INTO festive_run_notifications(run_slot_id,recipient_member_id,
                notification_type,idempotency_key,scheduled_for)
                SELECT s.id,r.member_id,'CANCELLED',
                    'festive:' || s.id || ':CANCELLED:' || (s.revision + 1) || ':' || r.member_id,now()
                FROM festive_run_slots s JOIN festive_run_hosts h ON h.run_slot_id=s.id
                JOIN festive_run_rsvps r ON r.run_slot_id=s.id
                WHERE h.member_id=OLD.id AND h.host_role='LEAD' AND h.status='ACTIVE'
                AND s.status='PUBLISHED' AND r.status='ACTIVE' AND r.reminder_opt_in
                ON CONFLICT(idempotency_key) DO NOTHING;
            UPDATE festive_run_slots SET status = 'CANCELLED', revision = revision + 1,
                updated_at = now() WHERE id IN (
                SELECT run_slot_id FROM festive_run_hosts WHERE member_id = OLD.id
                AND status = 'ACTIVE' AND host_role = 'LEAD');
            UPDATE festive_run_hosts SET status = 'WITHDRAWN', updated_at = now()
                WHERE member_id = OLD.id;
            IF TG_OP = 'UPDATE' THEN
                RETURN NEW;
            END IF;
            RETURN OLD;
        END; $$ LANGUAGE plpgsql;
        DROP TRIGGER IF EXISTS festive_member_erasure_trigger ON members;
        CREATE TRIGGER festive_member_erasure_trigger BEFORE DELETE ON members
            FOR EACH ROW EXECUTE FUNCTION festive_member_erasure();
        DROP TRIGGER IF EXISTS festive_member_consent_trigger ON members;
        CREATE TRIGGER festive_member_consent_trigger
            BEFORE UPDATE OF popia_acknowledged, popia_withdrawn_at ON members
            FOR EACH ROW WHEN (OLD.popia_acknowledged AND
                (NOT NEW.popia_acknowledged OR NEW.popia_withdrawn_at IS NOT NULL))
            EXECUTE FUNCTION festive_member_erasure();
    """)
