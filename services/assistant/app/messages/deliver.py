from __future__ import annotations

import hashlib
import logging
import time

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from .providers import DeliveryProvider, WhatsAppStubProvider

_LOGGER = logging.getLogger("messages.delivery")


def deliver_queued_message(
    conn: psycopg.Connection,
    worker_id: str,
    provider: DeliveryProvider | None = None,
) -> bool:
    if conn.closed:
        return False
    provider = provider or WhatsAppStubProvider()
    with conn.transaction():
        with conn.cursor(row_factory=dict_row) as cur:
            if not _messages_table_exists(cur):
                _LOGGER.warning("messages table missing; skipping delivery")
                return False

            columns = _message_columns(cur)
            select_columns = [
                "message_id",
                "user_id",
                "channel",
                "message_type",
                "body",
                "status",
                "related_entity_type",
                "related_entity_id",
            ]
            if columns["rendered_text"]:
                select_columns.append("rendered_text")
            cur.execute(
                f"""
                SELECT {', '.join(select_columns)}
                FROM messages
                WHERE status = 'queued'
                ORDER BY created_at ASC
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """
            )
            message = cur.fetchone()
            if not message:
                return False

            if message.get("channel") != "whatsapp":
                _mark_failed(
                    cur,
                    worker_id,
                    message_id=str(message["message_id"]),
                    provider=provider.name,
                    message_type=str(message.get("message_type") or ""),
                    channel=str(message.get("channel") or ""),
                    error_details="unsupported_channel",
                    columns=columns,
                )
                return True

            _LOGGER.info(
                "message delivery intent (message_id=%s message_type=%s)",
                message["message_id"],
                message.get("message_type"),
            )

            success, error = provider.deliver(message)
            if success:
                _mark_sent(
                    cur,
                    worker_id,
                    message_id=str(message["message_id"]),
                    provider=provider.name,
                    message_type=str(message.get("message_type") or ""),
                    channel=str(message.get("channel") or ""),
                    columns=columns,
                )
                _LOGGER.info(
                    "message delivered (message_id=%s message_type=%s)",
                    message["message_id"],
                    message.get("message_type"),
                )
            else:
                _mark_failed(
                    cur,
                    worker_id,
                    message_id=str(message["message_id"]),
                    provider=provider.name,
                    message_type=str(message.get("message_type") or ""),
                    channel=str(message.get("channel") or ""),
                    error_details=error or "delivery_failed",
                    columns=columns,
                )
                _LOGGER.warning(
                    "message delivery failed (message_id=%s message_type=%s error=%s)",
                    message["message_id"],
                    message.get("message_type"),
                    error,
                )
            return True


def _messages_table_exists(cur: psycopg.Cursor) -> bool:
    cur.execute("SELECT to_regclass('public.messages')")
    row = cur.fetchone()
    if not row:
        return False
    value = next(iter(row.values()))
    return value is not None


def _message_columns(cur: psycopg.Cursor) -> dict[str, bool]:
    def has_column(name: str) -> bool:
        cur.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'messages'
              AND column_name = %s
            """,
            (name,),
        )
        return cur.fetchone() is not None

    return {
        "rendered_text": has_column("rendered_text"),
        "sent_at": has_column("sent_at"),
        "error_details": has_column("error_details"),
        "updated_at": has_column("updated_at"),
    }


def _mark_sent(
    cur: psycopg.Cursor,
    worker_id: str,
    message_id: str,
    provider: str,
    message_type: str,
    channel: str,
    columns: dict[str, bool],
) -> None:
    set_clauses = ["status = 'sent'"]
    if columns["sent_at"]:
        set_clauses.append("sent_at = now()")
    if columns["updated_at"]:
        set_clauses.append("updated_at = now()")
    cur.execute(
        f"""
        UPDATE messages
        SET {', '.join(set_clauses)}
        WHERE message_id = %s
          AND status = 'queued'
        """,
        (message_id,),
    )
    if cur.rowcount == 0:
        return
    _audit_message(
        cur,
        actor_id=worker_id,
        action_type="message_sent",
        message_id=message_id,
        metadata={"channel": channel, "message_type": message_type, "provider": provider},
    )


def _mark_failed(
    cur: psycopg.Cursor,
    worker_id: str,
    message_id: str,
    provider: str,
    message_type: str,
    channel: str,
    error_details: str,
    columns: dict[str, bool],
) -> None:
    set_clauses = ["status = 'failed'"]
    params = []
    if columns["error_details"]:
        set_clauses.append("error_details = %s")
        params.append(error_details)
    if columns["updated_at"]:
        set_clauses.append("updated_at = now()")
    params.append(message_id)
    cur.execute(
        f"""
        UPDATE messages
        SET {', '.join(set_clauses)}
        WHERE message_id = %s
          AND status = 'queued'
        """,
        params,
    )
    if cur.rowcount == 0:
        return
    _audit_message(
        cur,
        actor_id=worker_id,
        action_type="message_failed",
        message_id=message_id,
        metadata={
            "channel": channel,
            "message_type": message_type,
            "provider": provider,
            "error": error_details,
        },
    )


def _audit_message(
    cur: psycopg.Cursor,
    actor_id: str,
    action_type: str,
    message_id: str,
    metadata: dict,
) -> None:
    digest = hashlib.sha256(
        f"{actor_id}:{action_type}:{message_id}:{time.time_ns()}".encode("utf-8")
    ).hexdigest()
    cur.execute(
        """
        INSERT INTO audit_log (
            actor_type,
            actor_id,
            action_type,
            entity_type,
            entity_id,
            audit_hash,
            metadata
        ) VALUES (
            'worker',
            %s,
            %s,
            'message',
            %s,
            %s,
            %s
        )
        """,
        (actor_id, action_type, message_id, digest, Json(metadata)),
    )
