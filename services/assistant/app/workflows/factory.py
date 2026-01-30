from __future__ import annotations

import hashlib
import time
from typing import Optional

import psycopg
from psycopg.types.json import Json

_WORKFLOW_TYPE_BY_SUGGESTION = {
    "clarify_job_search": "research",
    "offer_interview_prep": "event_preparation",
    "offer_goal_planning": "planning_month",
}


def workflow_type_for_suggestion(suggestion_type: str) -> str:
    try:
        return _WORKFLOW_TYPE_BY_SUGGESTION[suggestion_type]
    except KeyError as exc:
        raise ValueError(f"no workflow mapping for suggestion type '{suggestion_type}'") from exc


class WorkflowFactory:
    def __init__(self, actor_id: str) -> None:
        self._actor_id = actor_id

    def create_pending(
        self, cur: psycopg.Cursor, user_id: str, suggestion_type: str
    ) -> str:
        workflow_type = workflow_type_for_suggestion(suggestion_type)
        cur.execute(
            """
            INSERT INTO workflows (
                user_id,
                type,
                status,
                priority,
                started_at,
                created_at,
                updated_at
            ) VALUES (
                %s, %s, 'pending', 0, now(), now(), now()
            )
            RETURNING workflow_id
            """,
            (user_id, workflow_type),
        )
        return str(cur.fetchone()[0])

    def audit_workflow_created(
        self,
        cur: psycopg.Cursor,
        workflow_id: str,
        approval_id: str,
        suggestion_id: str,
        suggestion_type: str,
    ) -> None:
        digest = hashlib.sha256(
            f"{self._actor_id}:workflow_created:{workflow_id}:{time.time_ns()}".encode("utf-8")
        ).hexdigest()
        metadata = {
            "source": "approval",
            "approval_id": approval_id,
            "suggestion_id": suggestion_id,
            "suggestion_type": suggestion_type,
        }
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
                'workflow_created',
                'workflow',
                %s,
                %s,
                %s
            )
            """,
            (self._actor_id, workflow_id, digest, Json(metadata)),
        )
