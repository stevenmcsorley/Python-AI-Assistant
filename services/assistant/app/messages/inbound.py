from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
import time
import uuid

import psycopg
from psycopg.types.json import Json

from ..approvals import Approval, ApprovalWriter
from .models import Message
from .writer import MessageWriter


HELP_TEXT = (
    "Supported commands: approve <suggestion_id>, deny <suggestion_id>, "
    "status <workflow_id>, help"
)


@dataclass(frozen=True)
class ParsedCommand:
    name: str
    target_id: str | None


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
    return None, "unknown_command"


def handle_inbound_text(dsn: str, user_id: str, text: str) -> tuple[int, str]:
    logger = logging.getLogger("messages.inbound")
    if not user_id:
        _audit_rejection_best_effort(dsn, "unknown", "missing_user_id", text)
        return 400, "user_id is required"
    try:
        user_uuid = str(uuid.UUID(user_id))
    except ValueError:
        _audit_rejection_best_effort(dsn, "unknown", "invalid_user_id", text)
        return 400, "invalid user_id"

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
                cur.execute("SELECT 1 FROM users WHERE user_id = %s", (user_uuid,))
                if not cur.fetchone():
                    _audit_command(
                        cur,
                        actor_id=user_uuid,
                        action_type="command_rejected",
                        entity_type="user",
                        entity_id=user_uuid,
                        metadata={"reason": "user_not_found"},
                    )
                    return 404, "user not found"

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
    return 200, f"approval recorded ({approval_id})"


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
