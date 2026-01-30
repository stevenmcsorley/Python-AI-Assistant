from __future__ import annotations

import hashlib
import logging
import time
import uuid

import psycopg
from psycopg.types.json import Json

from .models import Message
from .renderers import render_message_text


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

    def render_message(self, message_id: str, cur: psycopg.Cursor | None = None) -> bool:
        if cur is None:
            with psycopg.connect(self._dsn) as conn:
                with conn.transaction():
                    with conn.cursor() as inner_cur:
                        return self._render_with_cursor(message_id, inner_cur)
        return self._render_with_cursor(message_id, cur)

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

    def _render_with_cursor(self, message_id: str, cur: psycopg.Cursor) -> bool:
        cur.execute("SELECT to_regclass('public.messages')")
        if cur.fetchone()[0] is None:
            self._logger.warning("messages table missing; skipping render")
            return False
        if not self._has_rendered_text_column(cur):
            self._logger.warning("messages.rendered_text missing; skipping render")
            return False

        cur.execute(
            """
            SELECT message_type, body, related_entity_type, related_entity_id, rendered_text
            FROM messages
            WHERE message_id = %s
            """,
            (message_id,),
        )
        row = cur.fetchone()
        if not row:
            return False
        message_type, body, related_entity_type, related_entity_id, rendered_text = row
        if rendered_text:
            return False

        payload = {
            "message_type": message_type,
            "body": body,
            "related_entity_type": related_entity_type,
            "related_entity_id": str(related_entity_id) if related_entity_id else "",
        }
        rendered = render_message_text(payload)
        cur.execute(
            """
            UPDATE messages
            SET rendered_text = %s
            WHERE message_id = %s
              AND rendered_text IS NULL
            """,
            (rendered, message_id),
        )
        if cur.rowcount == 0:
            return False
        self._audit_message_rendered(cur, message_id, str(message_type))
        return True

    def _has_rendered_text_column(self, cur: psycopg.Cursor) -> bool:
        cur.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'messages'
              AND column_name = 'rendered_text'
            """
        )
        return cur.fetchone() is not None

    def _audit_message_rendered(self, cur: psycopg.Cursor, message_id: str, message_type: str) -> None:
        digest = hashlib.sha256(
            f"{self._actor_id}:message_rendered:{message_id}:{time.time_ns()}".encode("utf-8")
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
                'message_rendered',
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
                Json({"message_type": message_type}),
            ),
        )
