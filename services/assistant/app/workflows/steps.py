from __future__ import annotations

import hashlib
import time
from typing import Iterable, List

import psycopg
from psycopg.types.json import Json

_WORKFLOW_STEPS = {
    "research": [
        "collect_sources",
        "read_sources",
        "synthesize_findings",
        "draft_research_note",
    ],
    "event_preparation": [
        "collect_event_context",
        "research_background",
        "draft_prep_brief",
    ],
    "planning_month": [
        "collect_goals",
        "review_calendar",
        "draft_month_plan",
    ],
}


def step_keys_for_workflow_type(workflow_type: str) -> List[str]:
    try:
        return list(_WORKFLOW_STEPS[workflow_type])
    except KeyError as exc:
        raise ValueError(f"no steps defined for workflow type '{workflow_type}'") from exc


def _idempotency_key(workflow_id: str, step_key: str) -> str:
    digest = hashlib.sha256(f"{workflow_id}:{step_key}".encode("utf-8")).hexdigest()
    return digest


class WorkflowStepPlanner:
    def __init__(self, actor_id: str) -> None:
        self._actor_id = actor_id

    def ensure_steps(
        self,
        cur: psycopg.Cursor,
        workflow_id: str,
        workflow_type: str,
        workflow_status: str,
    ) -> List[str]:
        if workflow_status != "pending":
            return []
        cur.execute(
            """
            SELECT 1 FROM workflow_steps
            WHERE workflow_id = %s
            LIMIT 1
            """,
            (workflow_id,),
        )
        if cur.fetchone():
            return []

        step_keys = step_keys_for_workflow_type(workflow_type)
        for index, step_key in enumerate(step_keys):
            cur.execute(
                """
                INSERT INTO workflow_steps (
                    workflow_id,
                    step_key,
                    step_index,
                    status,
                    idempotency_key
                ) VALUES (
                    %s, %s, %s, 'pending', %s
                )
                """,
                (
                    workflow_id,
                    step_key,
                    index,
                    _idempotency_key(workflow_id, step_key),
                ),
            )
        self._audit_steps_created(cur, workflow_id, step_keys)
        return step_keys

    def _audit_steps_created(
        self, cur: psycopg.Cursor, workflow_id: str, step_keys: Iterable[str]
    ) -> None:
        digest = hashlib.sha256(
            f"{self._actor_id}:workflow_steps_created:{workflow_id}:{time.time_ns()}".encode("utf-8")
        ).hexdigest()
        metadata = {"step_keys": list(step_keys)}
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
                'workflow_steps_created',
                'workflow',
                %s,
                %s,
                %s
            )
            """,
            (self._actor_id, workflow_id, digest, Json(metadata)),
        )


def plan_pending_workflows(dsn: str, actor_id: str) -> tuple[int, int]:
    planned = 0
    steps_created = 0
    with psycopg.connect(dsn) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT workflow_id, type, status
                    FROM workflows
                    WHERE status = 'pending'
                      AND type IN ('research', 'event_preparation', 'planning_month')
                    """
                )
                rows = cur.fetchall()
                planner = WorkflowStepPlanner(actor_id=actor_id)
                for workflow_id, workflow_type, workflow_status in rows:
                    created_steps = planner.ensure_steps(
                        cur,
                        workflow_id=str(workflow_id),
                        workflow_type=str(workflow_type),
                        workflow_status=str(workflow_status),
                    )
                    if created_steps:
                        planned += 1
                        steps_created += len(created_steps)
    return planned, steps_created
