from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import logging
import os
import time
import uuid

import psycopg
from psycopg.types.json import Json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..approvals import Approval, ApprovalWriter
from .models import Message
from .writer import MessageWriter


HELP_TEXT = (
    "Supported commands: approve <suggestion_id>, deny <suggestion_id>, "
    "status <workflow_id>, mute, unmute, snooze 2h, snooze until YYYY-MM-DD HH:MM, "
    "unsnooze, channels whatsapp,email, help"
)


@dataclass(frozen=True)
class ParsedCommand:
    name: str
    target_id: str | None
    args: dict | None = None


def parse_command(text: str) -> tuple[ParsedCommand | None, str | None]:
    if not isinstance(text, str):
        return None, "missing_text"
    raw = text.strip()
    if not raw:
        return None, "empty_command"
    parts = raw.split()
    command = parts[0].lower()
    if command == "help":
        if len(parts) != 1:
            return None, "unexpected_arguments"
        return ParsedCommand(name="help", target_id=None), None
    if command in ("approve", "deny", "status"):
        if len(parts) != 2:
            return None, "missing_target"
        try:
            target_uuid = str(uuid.UUID(parts[1]))
        except ValueError:
            return None, "invalid_target"
        return ParsedCommand(name=command, target_id=target_uuid), None
    if command in ("mute", "unmute", "unsnooze"):
        if len(parts) != 1:
            return None, "unexpected_arguments"
        return ParsedCommand(name=command, target_id=None), None
    if command == "snooze":
        if len(parts) == 2 and parts[1].lower().endswith("h"):
            value = parts[1].lower()[:-1]
            if not value.isdigit():
                return None, "invalid_snooze"
            hours = int(value)
            if hours <= 0:
                return None, "invalid_snooze"
            return ParsedCommand(name="snooze", target_id=None, args={"duration_hours": hours}), None
        if len(parts) == 4 and parts[1].lower() == "until":
            return ParsedCommand(
                name="snooze",
                target_id=None,
                args={"until_date": parts[2], "until_time": parts[3]},
            ), None
        return None, "invalid_snooze"
    if command == "channels":
        if len(parts) != 2:
            return None, "invalid_channels"
        channels = [segment.strip().lower() for segment in parts[1].split(",") if segment.strip()]
        if not channels:
            return None, "invalid_channels"
        return ParsedCommand(name="channels", target_id=None, args={"channels": channels}), None
    return None, "unknown_command"


def handle_inbound_text(dsn: str, phone: str, text: str) -> tuple[int, str]:
    logger = logging.getLogger("messages.inbound")
    if not phone:
        _audit_rejection_best_effort(dsn, "unknown", "missing_phone", text)
        return 400, "phone is required"

    command, error = parse_command(text)
    if error:
        with psycopg.connect(dsn) as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    _audit_command(
                        cur,
                        actor_id=user_uuid,
                        action_type="command_rejected",
                        entity_type="command",
                        entity_id=None,
                        metadata={"reason": error, "text": text},
                    )
        return 400, "command rejected"

    with psycopg.connect(dsn) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT user_id FROM users WHERE whatsapp_phone = %s",
                    (phone,),
                )
                row = cur.fetchone()
                if not row:
                    _audit_command(
                        cur,
                        actor_id=phone,
                        action_type="command_rejected",
                        entity_type="user",
                        entity_id=None,
                        metadata={"reason": "unknown_whatsapp_user", "phone": phone},
                    )
                    return 404, "user not found"
                user_uuid = str(row[0])

                if command is None:
                    _audit_command(
                        cur,
                        actor_id=user_uuid,
                        action_type="command_rejected",
                        entity_type="command",
                        entity_id=None,
                        metadata={"reason": "parse_error"},
                    )
                    return 400, "command rejected"

                if command.name == "help":
                    _audit_command(
                        cur,
                        actor_id=user_uuid,
                        action_type="command_processed",
                        entity_type="user",
                        entity_id=user_uuid,
                        metadata={"command": "help"},
                    )
                    return 200, HELP_TEXT

                if command.name == "status":
                    return _handle_status(
                        cur=cur,
                        dsn=dsn,
                        user_id=user_uuid,
                        workflow_id=command.target_id or "",
                    )

                if command.name in ("approve", "deny"):
                    return _handle_approval(
                        cur=cur,
                        dsn=dsn,
                        user_id=user_uuid,
                        suggestion_id=command.target_id or "",
                        decision=command.name,
                    )
                if command.name in ("mute", "unmute", "snooze", "unsnooze", "channels"):
                    return _handle_delivery_preferences(
                        cur=cur,
                        user_id=user_uuid,
                        command=command,
                    )

    logger.error("unhandled command")
    return 400, "command rejected"


def _handle_status(
    cur: psycopg.Cursor,
    dsn: str,
    user_id: str,
    workflow_id: str,
) -> tuple[int, str]:
    cur.execute(
        """
        SELECT workflow_id, user_id, status, completed_at
        FROM workflows
        WHERE workflow_id = %s
        """,
        (workflow_id,),
    )
    row = cur.fetchone()
    if not row:
        _audit_command(
            cur,
            actor_id=user_id,
            action_type="command_rejected",
            entity_type="workflow",
            entity_id=workflow_id,
            metadata={"command": "status", "reason": "workflow_not_found"},
        )
        return 404, "workflow not found"

    if str(row[1]) != user_id:
        _audit_command(
            cur,
            actor_id=user_id,
            action_type="command_rejected",
            entity_type="workflow",
            entity_id=workflow_id,
            metadata={"command": "status", "reason": "user_mismatch"},
        )
        return 403, "workflow not accessible"

    status = row[2]
    completed_at = row[3]
    body = f"Workflow {workflow_id} status: {status}"
    if completed_at is not None:
        body += f" (completed at {completed_at.isoformat()})"

    message_writer = MessageWriter(dsn, actor_id=f"whatsapp:{user_id}", actor_type="whatsapp")
    message = Message(
        user_id=user_id,
        channel="whatsapp",
        message_type="workflow_status",
        body=body,
        status="queued",
        related_entity_type="workflow",
        related_entity_id=workflow_id,
    )
    message_id, created = message_writer.write(message, cur=cur)
    if message_id:
        message_writer.render_message(message_id, cur=cur)
    if not created:
        _audit_command(
            cur,
            actor_id=user_id,
            action_type="command_noop",
            entity_type="workflow",
            entity_id=workflow_id,
            metadata={"command": "status", "reason": "message_exists"},
        )
    else:
        _audit_command(
            cur,
            actor_id=user_id,
            action_type="command_processed",
            entity_type="workflow",
            entity_id=workflow_id,
            metadata={"command": "status", "message_id": message_id},
        )
    return 200, body


def _handle_approval(
    cur: psycopg.Cursor,
    dsn: str,
    user_id: str,
    suggestion_id: str,
    decision: str,
) -> tuple[int, str]:
    cur.execute(
        """
        SELECT suggestion_id, user_id, status, intent_id
        FROM suggestions
        WHERE suggestion_id = %s
        """,
        (suggestion_id,),
    )
    row = cur.fetchone()
    if not row:
        _audit_command(
            cur,
            actor_id=user_id,
            action_type="command_rejected",
            entity_type="suggestion",
            entity_id=suggestion_id,
            metadata={"command": decision, "reason": "suggestion_not_found"},
        )
        return 404, "suggestion not found"

    if str(row[1]) != user_id:
        _audit_command(
            cur,
            actor_id=user_id,
            action_type="command_rejected",
            entity_type="suggestion",
            entity_id=suggestion_id,
            metadata={"command": decision, "reason": "user_mismatch"},
        )
        return 403, "suggestion not accessible"

    desired_status = "accepted" if decision == "approve" else "dismissed"
    current_status = row[2]
    if current_status == desired_status:
        _audit_command(
            cur,
            actor_id=user_id,
            action_type="command_noop",
            entity_type="suggestion",
            entity_id=suggestion_id,
            metadata={"command": decision, "reason": "already_applied"},
        )
        return 200, f"suggestion already {desired_status}"

    if current_status != "queued":
        _audit_command(
            cur,
            actor_id=user_id,
            action_type="command_rejected",
            entity_type="suggestion",
            entity_id=suggestion_id,
            metadata={"command": decision, "reason": "invalid_status", "status": current_status},
        )
        return 409, f"suggestion status is {current_status}"

    decision_value = "approved" if decision == "approve" else "denied"
    cur.execute(
        """
        SELECT decision
        FROM approvals
        WHERE suggestion_id = %s
        ORDER BY decided_at DESC
        LIMIT 1
        """,
        (suggestion_id,),
    )
    existing = cur.fetchone()
    if existing:
        existing_decision = existing[0]
        if existing_decision != decision_value:
            _audit_command(
                cur,
                actor_id=user_id,
                action_type="command_rejected",
                entity_type="suggestion",
                entity_id=suggestion_id,
                metadata={"command": decision, "reason": "decision_conflict"},
            )
            return 409, "decision conflict"

        cur.execute(
            """
            UPDATE suggestions
            SET status = %s, updated_at = now()
            WHERE suggestion_id = %s
            """,
            (desired_status, suggestion_id),
        )
        _audit_command(
            cur,
            actor_id=user_id,
            action_type="command_noop",
            entity_type="suggestion",
            entity_id=suggestion_id,
            metadata={"command": decision, "reason": "approval_exists"},
        )
        return 200, f"suggestion {desired_status}"

    approval = Approval(
        user_id=user_id,
        suggestion_id=suggestion_id,
        intent_id=str(row[3]) if row[3] else None,
        workflow_id=None,
        decision=decision_value,
        channel="whatsapp",
        reason=None,
    )
    approval_writer = ApprovalWriter(dsn, actor_id=f"whatsapp:{user_id}")
    approval_id = approval_writer.write(approval, cur=cur)
    cur.execute(
        """
        UPDATE suggestions
        SET status = %s, updated_at = now()
        WHERE suggestion_id = %s
        """,
        (desired_status, suggestion_id),
    )
    _audit_command(
        cur,
        actor_id=user_id,
        action_type="command_processed",
        entity_type="suggestion",
        entity_id=suggestion_id,
        metadata={"command": decision, "approval_id": approval_id},
    )
    return 200, f"approval recorded ({approval_id})"


def _handle_delivery_preferences(
    cur: psycopg.Cursor,
    user_id: str,
    command: ParsedCommand,
) -> tuple[int, str]:
    if not _preferences_table_exists(cur):
        _audit_command(
            cur,
            actor_id=user_id,
            action_type="command_rejected",
            entity_type="user",
            entity_id=user_id,
            metadata={"reason": "preferences_table_missing", "command": command.name},
        )
        return 503, "delivery preferences unavailable"

    current = _fetch_preferences(cur, user_id)
    updated = dict(current)
    action_type = ""
    metadata: dict = {}

    if command.name == "mute":
        updated["muted"] = True
        action_type = "delivery_muted"
        metadata = {"channel": "whatsapp"}
    elif command.name == "unmute":
        updated["muted"] = False
        action_type = "delivery_unmuted"
        metadata = {}
    elif command.name == "unsnooze":
        updated["snoozed_until"] = None
        action_type = "delivery_unsnoozed"
        metadata = {}
    elif command.name == "snooze":
        snoozed_until = _parse_snooze(command)
        if snoozed_until is None:
            _audit_command(
                cur,
                actor_id=user_id,
                action_type="command_rejected",
                entity_type="user",
                entity_id=user_id,
                metadata={"reason": "invalid_snooze", "command": "snooze"},
            )
            return 400, "invalid snooze command"
        updated["snoozed_until"] = snoozed_until
        action_type = "delivery_snoozed"
        metadata = {"until": snoozed_until.isoformat()}
    elif command.name == "channels":
        channels = _parse_channels(command)
        if not channels:
            _audit_command(
                cur,
                actor_id=user_id,
                action_type="command_rejected",
                entity_type="user",
                entity_id=user_id,
                metadata={"reason": "invalid_channels", "command": "channels"},
            )
            return 400, "invalid channels"
        updated["allowed_channels"] = channels
        action_type = "delivery_channel_updated"
        metadata = {"allowed_channels": channels}
    else:
        _audit_command(
            cur,
            actor_id=user_id,
            action_type="command_rejected",
            entity_type="user",
            entity_id=user_id,
            metadata={"reason": "unknown_command", "command": command.name},
        )
        return 400, "command rejected"

    if _preferences_equal(current, updated):
        _audit_command(
            cur,
            actor_id=user_id,
            action_type="command_noop",
            entity_type="user",
            entity_id=user_id,
            metadata={"command": command.name, "reason": "no_change"},
        )
        return 200, "no changes"

    cur.execute(
        """
        INSERT INTO user_delivery_preferences (
            user_id,
            muted,
            snoozed_until,
            allowed_channels,
            updated_at
        ) VALUES (
            %s, %s, %s, %s, now()
        )
        ON CONFLICT (user_id) DO UPDATE SET
            muted = EXCLUDED.muted,
            snoozed_until = EXCLUDED.snoozed_until,
            allowed_channels = EXCLUDED.allowed_channels,
            updated_at = now()
        """,
        (
            user_id,
            updated["muted"],
            updated["snoozed_until"],
            updated["allowed_channels"],
        ),
    )
    _audit_command(
        cur,
        actor_id=user_id,
        action_type=action_type,
        entity_type="user",
        entity_id=user_id,
        metadata=metadata,
    )
    _audit_command(
        cur,
        actor_id=user_id,
        action_type="command_processed",
        entity_type="user",
        entity_id=user_id,
        metadata={"command": command.name},
    )
    return 200, "preferences updated"


def _preferences_table_exists(cur: psycopg.Cursor) -> bool:
    cur.execute("SELECT to_regclass('public.user_delivery_preferences')")
    row = cur.fetchone()
    if not row:
        return False
    value = row[0] if not isinstance(row, dict) else next(iter(row.values()))
    return value is not None


def _fetch_preferences(cur: psycopg.Cursor, user_id: str) -> dict:
    cur.execute(
        """
        SELECT muted, snoozed_until, allowed_channels
        FROM user_delivery_preferences
        WHERE user_id = %s
        """,
        (user_id,),
    )
    row = cur.fetchone()
    if not row:
        return {
            "muted": False,
            "snoozed_until": None,
            "allowed_channels": ["whatsapp"],
        }
    if isinstance(row, dict):
        muted = bool(row.get("muted"))
        snoozed_until = row.get("snoozed_until")
        channels = row.get("allowed_channels") or []
    else:
        muted, snoozed_until, channels = row
    return {
        "muted": bool(muted),
        "snoozed_until": snoozed_until,
        "allowed_channels": [str(ch).lower() for ch in (channels or [])],
    }


def _parse_snooze(command: ParsedCommand) -> datetime | None:
    args = command.args or {}
    now_utc = datetime.now(timezone.utc)
    if "duration_hours" in args:
        hours = int(args["duration_hours"])
        return now_utc + timedelta(hours=hours)
    if "until_date" in args and "until_time" in args:
        try:
            target = datetime.strptime(
                f"{args['until_date']} {args['until_time']}", "%Y-%m-%d %H:%M"
            )
        except ValueError:
            return None
        tz_name = os.getenv("USER_TIMEZONE", "UTC")
        try:
            tz = ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            tz = timezone.utc
        target = target.replace(tzinfo=tz)
        return target.astimezone(timezone.utc)
    return None


def _parse_channels(command: ParsedCommand) -> list[str]:
    args = command.args or {}
    channels = args.get("channels") or []
    normalized = []
    for channel in channels:
        value = str(channel).strip().lower()
        if value and value not in normalized:
            normalized.append(value)
    return normalized


def _preferences_equal(current: dict, updated: dict) -> bool:
    if bool(current.get("muted")) != bool(updated.get("muted")):
        return False
    if current.get("snoozed_until") != updated.get("snoozed_until"):
        return False
    current_channels = [str(ch).lower() for ch in (current.get("allowed_channels") or [])]
    updated_channels = [str(ch).lower() for ch in (updated.get("allowed_channels") or [])]
    return current_channels == updated_channels


def _audit_command(
    cur: psycopg.Cursor,
    actor_id: str,
    action_type: str,
    entity_type: str,
    entity_id: str | None,
    metadata: dict,
) -> None:
    digest = hashlib.sha256(
        f"{actor_id}:{action_type}:{entity_type}:{entity_id}:{time.time_ns()}".encode("utf-8")
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
            'whatsapp',
            %s,
            %s,
            %s,
            %s,
            %s,
            %s
        )
        """,
        (actor_id, action_type, entity_type, entity_id, digest, Json(metadata)),
    )


def _audit_rejection_best_effort(dsn: str, actor_id: str, reason: str, text: str) -> None:
    try:
        with psycopg.connect(dsn) as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    _audit_command(
                        cur,
                        actor_id=actor_id,
                        action_type="command_rejected",
                        entity_type="command",
                        entity_id=None,
                        metadata={"reason": reason, "text": text},
                    )
    except Exception:
        return
