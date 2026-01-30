from __future__ import annotations

import hashlib
import logging
import time
import uuid

import psycopg
from psycopg.types.json import Json

from .models import Message


class MessageWriter:
    def __init__(self, dsn: str, actor_id: str, actor_type: str) -> None:
        self._dsn = dsn
        self._actor_id = actor_id
        self._actor_type = actor_type
        self._logger = logging.getLogger("messages")

    def write(self, message: Message, cur: psycopg.Cursor | None = None) -> tuple[str | None, bool]:
        message.validate()
        if cur is None:
            with psycopg.connect(self._dsn) as conn:
                with conn.transaction():
                    with conn.cursor() as inner_cur:
                        return self._write_with_cursor(message, inner_cur)
        return self._write_with_cursor(message, cur)

    def _write_with_cursor(self, message: Message, cur: psycopg.Cursor) -> tuple[str | None, bool]:
        cur.execute("SELECT to_regclass('public.messages')")
        if cur.fetchone()[0] is None:
            self._logger.warning("messages table missing; skipping message queue")
            return None, False

        cur.execute(
            """
            SELECT message_id
            FROM messages
            WHERE message_type = %s AND related_entity_id = %s
            LIMIT 1
            """,
            (message.message_type, message.related_entity_id),
        )
        existing = cur.fetchone()
        if existing:
            return str(existing[0]), False

        message_id = message.message_id or str(uuid.uuid4())
        cur.execute(
            """
            INSERT INTO messages (
                message_id,
                user_id,
                channel,
                message_type,
                body,
                status,
                related_entity_type,
                related_entity_id,
                created_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, now()
            )
            """,
            (
                message_id,
                message.user_id,
                message.channel,
                message.message_type,
                message.body,
                message.status,
                message.related_entity_type,
                message.related_entity_id,
            ),
        )
        self._audit_message_queued(cur, message_id, message)
        return message_id, True

    def _audit_message_queued(self, cur: psycopg.Cursor, message_id: str, message: Message) -> None:
        digest = hashlib.sha256(
            f"{self._actor_id}:message_queued:{message_id}:{time.time_ns()}".encode("utf-8")
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
                %s,
                %s,
                'message_queued',
                'message',
                %s,
                %s,
                %s
            )
            """,
            (
                self._actor_type,
                self._actor_id,
                message_id,
                digest,
                Json(
                    {
                        "channel": message.channel,
                        "message_type": message.message_type,
                        "related_entity_type": message.related_entity_type,
                        "related_entity_id": message.related_entity_id,
                    }
                ),
            ),
        )
