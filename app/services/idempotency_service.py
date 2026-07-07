from app.db import get_cursor


def register_inbound_message(message_id: str | None, sender: str | None = None) -> bool:
    if not message_id:
        return True

    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO inbound_whatsapp_messages (message_id, sender)
            VALUES (%s, %s)
            ON CONFLICT (message_id) DO NOTHING
            RETURNING message_id
        """, (message_id, sender))
        return cur.fetchone() is not None


def mark_inbound_message_processed(message_id: str | None, status: str = "PROCESSED", error: str | None = None):
    if not message_id:
        return

    with get_cursor() as cur:
        cur.execute("""
            UPDATE inbound_whatsapp_messages
            SET status = %s,
                processed_at = CURRENT_TIMESTAMP,
                error = %s
            WHERE message_id = %s
        """, (status, error, message_id))
