from __future__ import annotations

import hashlib
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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

            quiet_blocked, quiet_retry = _quiet_hours_blocked()
            if quiet_blocked:
                _audit_delay_once(
                    cur,
                    worker_id=worker_id,
                    action_type="message_delayed_quiet_hours",
                    message_id=str(message["message_id"]),
                    metadata={
                        "channel": "whatsapp",
                        "message_type": str(message.get("message_type") or ""),
                        "reason": "quiet_hours",
                        "retry_after_seconds": quiet_retry,
                    },
                )
                _LOGGER.info(
                    "message delayed (quiet hours) (message_id=%s message_type=%s)",
                    message["message_id"],
                    message.get("message_type"),
                )
                return True

            rate_blocked, rate_retry = _rate_limit_blocked(
                cur,
                user_id=str(message["user_id"]),
            )
            if rate_blocked:
                _audit_delay_once(
                    cur,
                    worker_id=worker_id,
                    action_type="message_delayed_rate_limit",
                    message_id=str(message["message_id"]),
                    metadata={
                        "channel": "whatsapp",
                        "message_type": str(message.get("message_type") or ""),
                        "reason": "rate_limit",
                        "retry_after_seconds": rate_retry,
                    },
                )
                _LOGGER.info(
                    "message delayed (rate limit) (message_id=%s message_type=%s)",
                    message["message_id"],
                    message.get("message_type"),
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


def _quiet_hours_blocked() -> tuple[bool, int]:
    enabled = os.getenv("QUIET_HOURS_ENABLED", "false").lower() == "true"
    if not enabled:
        return False, 0
    try:
        start_hour = int(os.getenv("QUIET_HOURS_START", "22"))
        end_hour = int(os.getenv("QUIET_HOURS_END", "8"))
    except ValueError:
        return False, 0
    if not (0 <= start_hour <= 23 and 0 <= end_hour <= 23):
        return False, 0

    tz_name = os.getenv("USER_TIMEZONE", "UTC")
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        tz = timezone.utc

    now_local = datetime.now(tz)
    if start_hour == end_hour:
        return False, 0

    if start_hour < end_hour:
        in_quiet = start_hour <= now_local.hour < end_hour
        if not in_quiet:
            return False, 0
        end_time = now_local.replace(hour=end_hour, minute=0, second=0, microsecond=0)
        if end_time <= now_local:
            end_time = end_time + timedelta(days=1)
    else:
        in_quiet = now_local.hour >= start_hour or now_local.hour < end_hour
        if not in_quiet:
            return False, 0
        if now_local.hour >= start_hour:
            end_time = (now_local + timedelta(days=1)).replace(
                hour=end_hour, minute=0, second=0, microsecond=0
            )
        else:
            end_time = now_local.replace(hour=end_hour, minute=0, second=0, microsecond=0)

    retry_after = int((end_time - now_local).total_seconds())
    return True, max(retry_after, 0)


def _rate_limit_blocked(cur: psycopg.Cursor, user_id: str) -> tuple[bool, int]:
    try:
        limit = int(os.getenv("MESSAGE_RATE_LIMIT_COUNT", "3"))
        window_seconds = int(os.getenv("MESSAGE_RATE_LIMIT_WINDOW_SECONDS", "300"))
    except ValueError:
        return False, 0
    if limit <= 0 or window_seconds <= 0:
        return False, 0

    now_utc = datetime.now(timezone.utc)
    window_start = now_utc - timedelta(seconds=window_seconds)
    cur.execute(
        """
        SELECT COUNT(*) AS message_count, MIN(a.timestamp) AS earliest_sent
        FROM audit_log a
        JOIN messages m ON a.entity_id = m.message_id
        WHERE a.action_type = 'message_sent'
          AND a.entity_type = 'message'
          AND m.user_id = %s
          AND a.timestamp >= %s
        """,
        (user_id, window_start),
    )
    row = cur.fetchone()
    if isinstance(row, dict):
        count = row.get("message_count")
        earliest = row.get("earliest_sent")
    else:
        count, earliest = row
    if count is None or int(count) < limit:
        return False, 0
    retry_after = window_seconds
    if earliest is not None:
        delta = (now_utc - earliest).total_seconds()
        retry_after = max(window_seconds - int(delta), 0)
    return True, retry_after


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


def _audit_delay_once(
    cur: psycopg.Cursor,
    worker_id: str,
    action_type: str,
    message_id: str,
    metadata: dict,
) -> None:
    cur.execute(
        """
        SELECT 1
        FROM audit_log
        WHERE action_type = %s
          AND entity_type = 'message'
          AND entity_id = %s
        LIMIT 1
        """,
        (action_type, message_id),
    )
    if cur.fetchone():
        return
    _audit_message(cur, worker_id, action_type, message_id, metadata)
