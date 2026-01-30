from __future__ import annotations

import hashlib
import time
from typing import Optional

import psycopg
from psycopg.types.json import Json

from .models import Approval


class ApprovalWriter:
    def __init__(self, dsn: str, actor_id: str) -> None:
        self._dsn = dsn
        self._actor_id = actor_id

    def write(self, approval: Approval, cur: Optional[psycopg.Cursor] = None) -> str:
        approval.validate()
        if cur is not None:
            return self._write_with_cursor(cur, approval)
        with psycopg.connect(self._dsn) as conn:
            with conn.transaction():
                with conn.cursor() as inner_cur:
                    return self._write_with_cursor(inner_cur, approval)

    def _write_with_cursor(self, cur: psycopg.Cursor, approval: Approval) -> str:
        cur.execute(
            """
            INSERT INTO approvals (
                user_id,
                suggestion_id,
                intent_id,
                workflow_id,
                decision,
                channel,
                reason,
                decided_at,
                created_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, now(), now()
            )
            RETURNING approval_id
            """,
            (
                approval.user_id,
                approval.suggestion_id,
                approval.intent_id,
                approval.workflow_id,
                approval.decision,
                approval.channel,
                approval.reason,
            ),
        )
        approval_id = str(cur.fetchone()[0])
        self._audit_approval_recorded(cur, approval_id, approval)
        return approval_id

    def _audit_approval_recorded(
        self, cur: psycopg.Cursor, approval_id: str, approval: Approval
    ) -> None:
        digest = hashlib.sha256(
            f"{self._actor_id}:approval_recorded:{approval_id}:{time.time_ns()}".encode("utf-8")
        ).hexdigest()
        metadata = {
            "source": "approval",
            "decision": approval.decision,
            "suggestion_id": approval.suggestion_id,
            "intent_id": approval.intent_id,
            "workflow_id": approval.workflow_id,
        }
        if approval.reason:
            metadata["reason"] = approval.reason
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
                'orchestrator',
                %s,
                'approval_recorded',
                'approval',
                %s,
                %s,
                %s
            )
            """,
            (self._actor_id, approval_id, digest, Json(metadata)),
        )
