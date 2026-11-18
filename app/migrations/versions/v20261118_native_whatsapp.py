"""Add disposable Flow sessions and minimal delivery diagnostics; no TT edits."""

VERSION = "20261118_native_whatsapp"


def upgrade(cur):
    cur.execute("""
        CREATE TABLE whatsapp_flow_sessions (
            token_hash TEXT PRIMARY KEY,
            member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
            flow_key TEXT NOT NULL,
            expected_state TEXT NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            consumed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX whatsapp_flow_sessions_expiry ON whatsapp_flow_sessions(expires_at);
        CREATE TABLE whatsapp_delivery_status (
            message_id TEXT PRIMARY KEY,
            job_id INTEGER NOT NULL REFERENCES job_queue(id) ON DELETE CASCADE,
            status TEXT NOT NULL CHECK (status IN ('accepted','sent','delivered','read','failed')),
            status_rank INTEGER NOT NULL,
            event_timestamp BIGINT,
            error_code INTEGER,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX whatsapp_delivery_status_retention ON whatsapp_delivery_status(created_at);
        CREATE INDEX whatsapp_delivery_status_job ON whatsapp_delivery_status(job_id);
    """)
