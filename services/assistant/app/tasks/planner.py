from __future__ import annotations

import hashlib
import time
from typing import Iterable, List

import psycopg
from psycopg.types.json import Json

_STEP_TASKS = {
    "collect_sources": ["fetch_sources"],
    "read_sources": ["read_sources"],
    "synthesize_findings": ["synthesize"],
    "draft_research_note": ["write_note"],
    "collect_event_context": ["gather_context"],
    "research_background": ["research_context"],
    "draft_prep_brief": ["write_brief"],
    "collect_goals": ["gather_goals"],
    "review_calendar": ["review_calendar"],
    "draft_month_plan": ["write_plan"],
}


def task_types_for_step_key(step_key: str) -> List[str]:
    try:
        return list(_STEP_TASKS[step_key])
    except KeyError as exc:
        raise ValueError(f"no task mapping for step '{step_key}'") from exc


def _idempotency_key(step_id: str, task_type: str) -> str:
    digest = hashlib.sha256(f"{step_id}:{task_type}".encode("utf-8")).hexdigest()
    return digest


class TaskPlanner:
    def __init__(self, actor_id: str) -> None:
        self._actor_id = actor_id

    def ensure_tasks(
        self,
        cur: psycopg.Cursor,
        step_id: str,
        workflow_id: str,
        step_key: str,
        step_status: str,
    ) -> List[str]:
        if step_status != "pending":
            return []
        cur.execute(
            """
            SELECT 1 FROM tasks
            WHERE step_id = %s
            LIMIT 1
            """,
            (step_id,),
        )
        if cur.fetchone():
            return []

        task_types = task_types_for_step_key(step_key)
        for task_type in task_types:
            cur.execute(
                """
                INSERT INTO tasks (
                    workflow_id,
                    step_id,
                    task_type,
                    status,
                    idempotency_key,
                    attempts
                ) VALUES (
                    %s, %s, %s, 'pending', %s, 0
                )
                """,
                (
                    workflow_id,
                    step_id,
                    task_type,
                    _idempotency_key(step_id, task_type),
                ),
            )
        self._audit_tasks_created(cur, step_id, task_types)
        return task_types

    def _audit_tasks_created(
        self, cur: psycopg.Cursor, step_id: str, task_types: Iterable[str]
    ) -> None:
        digest = hashlib.sha256(
            f"{self._actor_id}:tasks_created:{step_id}:{time.time_ns()}".encode("utf-8")
        ).hexdigest()
        metadata = {"task_types": list(task_types)}
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
                'tasks_created',
                'workflow_step',
                %s,
                %s,
                %s
            )
            """,
            (self._actor_id, step_id, digest, Json(metadata)),
        )


def plan_pending_tasks(dsn: str, actor_id: str) -> tuple[int, int]:
    planned = 0
    tasks_created = 0
    with psycopg.connect(dsn) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT step_id, workflow_id, step_key, status
                    FROM workflow_steps
                    WHERE status = 'pending'
                      AND step_key IN (
                        'collect_sources',
                        'read_sources',
                        'synthesize_findings',
                        'draft_research_note',
                        'collect_event_context',
                        'research_background',
                        'draft_prep_brief',
                        'collect_goals',
                        'review_calendar',
                        'draft_month_plan'
                      )
                    """
                )
                rows = cur.fetchall()
                planner = TaskPlanner(actor_id=actor_id)
                for step_id, workflow_id, step_key, status in rows:
                    created = planner.ensure_tasks(
                        cur,
                        step_id=str(step_id),
                        workflow_id=str(workflow_id),
                        step_key=str(step_key),
                        step_status=str(status),
                    )
                    if created:
                        planned += 1
                        tasks_created += len(created)
    return planned, tasks_created
