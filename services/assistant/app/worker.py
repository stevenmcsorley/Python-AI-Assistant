import hashlib
import json
import logging
import os
import signal
import subprocess
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from dataclasses import dataclass

import psycopg
import requests
from psycopg.rows import dict_row
from psycopg.types.json import Json


REQUIRED_TABLES = ("tasks", "task_attempts", "audit_log")
LEASE_DURATION_SECONDS = 120
LEASE_RENEW_SECONDS = 30
MAX_WEB_FETCH_BYTES = 256 * 1024
WEB_FETCH_TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    allowed_task_types: tuple[str, ...]
    input_schema: dict


_DEFAULT_TOOL_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "task_id": {"type": "string"},
        "task_type": {"type": "string"},
    },
    "required": ["task_id", "task_type"],
    "additionalProperties": False,
}

TOOL_REGISTRY: dict[str, Tool] = {
    "web_fetch": Tool(
        name="web_fetch",
        description="Fetch sources from the web (planned only).",
        allowed_task_types=("fetch_sources",),
        input_schema=_DEFAULT_TOOL_INPUT_SCHEMA,
    ),
    "content_reader": Tool(
        name="content_reader",
        description="Read and parse content (planned only).",
        allowed_task_types=("read_sources",),
        input_schema=_DEFAULT_TOOL_INPUT_SCHEMA,
    ),
    "summarizer": Tool(
        name="summarizer",
        description="Summarize content (planned only).",
        allowed_task_types=("synthesize",),
        input_schema=_DEFAULT_TOOL_INPUT_SCHEMA,
    ),
    "markdown_writer": Tool(
        name="markdown_writer",
        description="Write markdown output (planned only).",
        allowed_task_types=("write_note",),
        input_schema=_DEFAULT_TOOL_INPUT_SCHEMA,
    ),
    "context_collector": Tool(
        name="context_collector",
        description="Collect context (planned only).",
        allowed_task_types=("gather_context",),
        input_schema=_DEFAULT_TOOL_INPUT_SCHEMA,
    ),
    "web_research": Tool(
        name="web_research",
        description="Research context (planned only).",
        allowed_task_types=("research_context",),
        input_schema=_DEFAULT_TOOL_INPUT_SCHEMA,
    ),
    "brief_writer": Tool(
        name="brief_writer",
        description="Draft a brief (planned only).",
        allowed_task_types=("write_brief",),
        input_schema=_DEFAULT_TOOL_INPUT_SCHEMA,
    ),
    "goal_collector": Tool(
        name="goal_collector",
        description="Collect goals (planned only).",
        allowed_task_types=("gather_goals",),
        input_schema=_DEFAULT_TOOL_INPUT_SCHEMA,
    ),
    "calendar_reader": Tool(
        name="calendar_reader",
        description="Review calendar (planned only).",
        allowed_task_types=("review_calendar",),
        input_schema=_DEFAULT_TOOL_INPUT_SCHEMA,
    ),
    "plan_writer": Tool(
        name="plan_writer",
        description="Draft a plan (planned only).",
        allowed_task_types=("write_plan",),
        input_schema=_DEFAULT_TOOL_INPUT_SCHEMA,
    ),
}

TASK_TOOL_MAPPING: dict[str, str] = {
    "fetch_sources": "web_fetch",
    "read_sources": "content_reader",
    "synthesize": "summarizer",
    "write_note": "markdown_writer",
    "gather_context": "context_collector",
    "research_context": "web_research",
    "write_brief": "brief_writer",
    "gather_goals": "goal_collector",
    "review_calendar": "calendar_reader",
    "write_plan": "plan_writer",
}

STUB_TASK_TYPES = set(TASK_TOOL_MAPPING.keys())


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        raise SystemExit(f"invalid integer for {name}: {value}")


def _check_required_tables(conn: psycopg.Connection) -> tuple[bool, str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                to_regclass('public.tasks') IS NOT NULL,
                to_regclass('public.task_attempts') IS NOT NULL,
                to_regclass('public.audit_log') IS NOT NULL
            """
        )
        exists = cur.fetchone()
    if not exists or not all(exists):
        return False, "required tables missing"
    return True, "tables present"


def _write_heartbeat(conn: psycopg.Connection, worker_id: str) -> tuple[bool, str]:
    digest = hashlib.sha256(f"{worker_id}:{time.time_ns()}".encode("utf-8")).hexdigest()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audit_log (
                    actor_type,
                    actor_id,
                    action_type,
                    entity_type,
                    audit_hash,
                    metadata
                ) VALUES (
                    'worker',
                    %s,
                    'heartbeat',
                    'worker',
                    %s,
                    %s
                )
                """,
                (worker_id, digest, Json({"note": "readiness_check"})),
            )
        conn.commit()
        return True, "heartbeat ok"
    except Exception as exc:
        conn.rollback()
        return False, f"heartbeat failed: {exc}"


def _sandbox_check() -> tuple[bool, str]:
    try:
        subprocess.run(["/bin/true"], check=True, timeout=2)
        return True, "sandbox ok"
    except Exception as exc:
        return False, f"sandbox failed: {exc}"


class _ReadinessState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.ready = False
        self.message = "starting"

    def set(self, ready: bool, message: str) -> None:
        with self._lock:
            self.ready = ready
            self.message = message

    def get(self) -> tuple[bool, str]:
        with self._lock:
            return self.ready, self.message


def _make_handler(state: _ReadinessState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib signature
            if self.path in ("/healthz", "/health"):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"alive")
                return
            if self.path in ("/readyz", "/ready"):
                ready, msg = state.get()
                if ready:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"ready")
                else:
                    self.send_response(503)
                    self.end_headers()
                    self.wfile.write(msg.encode("utf-8"))
                return
            self.send_response(404)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler


def _recovery_scan(conn: psycopg.Connection, logger: logging.Logger) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT task_id
            FROM tasks
            WHERE status = 'running'
              AND lease_expires_at IS NOT NULL
              AND lease_expires_at < now()
            ORDER BY lease_expires_at ASC
            """
        )
        rows = cur.fetchall()
    if not rows:
        logger.info("recovery scan: no reclaimable tasks")
        return
    task_ids = [str(r[0]) for r in rows]
    logger.info("recovery scan: %d reclaimable tasks", len(task_ids))
    logger.info("recovery scan: reclaimable task_ids=%s", ",".join(task_ids))


def _audit(
    cur: psycopg.Cursor,
    actor_id: str,
    action_type: str,
    entity_type: str,
    entity_id: str | None,
    workflow_id: str | None,
    step_id: str | None,
    task_id: str | None,
    metadata: dict | None = None,
    timestamp: datetime | None = None,
) -> None:
    ts = timestamp or datetime.now(timezone.utc)
    digest = hashlib.sha256(
        f"{actor_id}:{action_type}:{entity_type}:{entity_id}:{time.time_ns()}".encode("utf-8")
    ).hexdigest()
    cur.execute(
        """
        INSERT INTO audit_log (
            timestamp,
            actor_type,
            actor_id,
            action_type,
            entity_type,
            entity_id,
            workflow_id,
            step_id,
            task_id,
            audit_hash,
            metadata
        ) VALUES (
            %s,
            'worker',
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s
        )
        """,
        (
            ts,
            actor_id,
            action_type,
            entity_type,
            entity_id,
            workflow_id,
            step_id,
            task_id,
            digest,
            Json(metadata or {}),
        ),
    )


def _claim_task(conn: psycopg.Connection, worker_id: str, logger: logging.Logger) -> dict | None:
    with conn.transaction():
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                WITH candidate AS (
                    SELECT task_id
                    FROM tasks
                    WHERE (
                        status IN ('pending','scheduled')
                        OR (status = 'running' AND lease_expires_at IS NOT NULL AND lease_expires_at < now())
                    )
                    ORDER BY updated_at NULLS LAST, created_at ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE tasks
                SET status = 'running',
                    lease_owner = %s,
                    lease_expires_at = now() + (%s || ' seconds')::interval,
                    attempts = attempts + 1,
                    started_at = COALESCE(started_at, now()),
                    updated_at = now()
                WHERE task_id IN (SELECT task_id FROM candidate)
                RETURNING *
                """,
                (worker_id, LEASE_DURATION_SECONDS),
            )
            task = cur.fetchone()
            if not task:
                return None

            ts_claim = datetime.now(timezone.utc)
            ts_start = ts_claim + timedelta(microseconds=1)

            attempt_number = task["attempts"]
            cur.execute(
                """
                INSERT INTO task_attempts (
                    task_id,
                    attempt_number,
                    status,
                    worker_id,
                    started_at
                ) VALUES (%s, %s, 'running', %s, now())
                """,
                (task["task_id"], attempt_number, worker_id),
            )
            _audit(
                cur,
                worker_id,
                "task_claimed",
                "task",
                str(task["task_id"]),
                str(task["workflow_id"]) if task["workflow_id"] else None,
                str(task["step_id"]) if task["step_id"] else None,
                str(task["task_id"]),
                timestamp=ts_claim,
            )
            _audit(
                cur,
                worker_id,
                "task_started",
                "task",
                str(task["task_id"]),
                str(task["workflow_id"]) if task["workflow_id"] else None,
                str(task["step_id"]) if task["step_id"] else None,
                str(task["task_id"]),
                timestamp=ts_start,
            )
            logger.info("task claimed (task_id=%s)", task["task_id"])
            logger.info("task started (task_id=%s)", task["task_id"])
            return task


def _renew_lease(conn: psycopg.Connection, worker_id: str, task: dict) -> None:
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE tasks
                SET lease_expires_at = now() + (%s || ' seconds')::interval,
                    updated_at = now()
                WHERE task_id = %s
                  AND lease_owner = %s
                  AND status = 'running'
                """,
                (LEASE_DURATION_SECONDS, task["task_id"], worker_id),
            )
            _audit(
                cur,
                worker_id,
                "lease_renewed",
                "task",
                str(task["task_id"]),
                str(task["workflow_id"]) if task["workflow_id"] else None,
                str(task["step_id"]) if task["step_id"] else None,
                str(task["task_id"]),
            )


def _mark_failed(
    conn: psycopg.Connection,
    worker_id: str,
    task: dict,
    error_details: str,
) -> None:
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE tasks
                SET status = 'failed',
                    error_details = %s,
                    completed_at = now(),
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    updated_at = now()
                WHERE task_id = %s
                """,
                (error_details, task["task_id"]),
            )
            cur.execute(
                """
                UPDATE task_attempts
                SET status = 'failed',
                    ended_at = now(),
                    error_details = %s
                WHERE task_id = %s
                  AND attempt_number = %s
                """,
                (error_details, task["task_id"], task["attempts"]),
            )
            _audit(
                cur,
                worker_id,
                "task_failed",
                "task",
                str(task["task_id"]),
                str(task["workflow_id"]) if task["workflow_id"] else None,
                str(task["step_id"]) if task["step_id"] else None,
                str(task["task_id"]),
                {"error": error_details},
            )

            if task["step_id"] is not None:
                cur.execute(
                    """
                    UPDATE workflow_steps
                    SET status = 'failed',
                        completed_at = now(),
                        error_details = %s,
                        updated_at = now()
                    WHERE step_id = %s
                    """,
                    (error_details, task["step_id"]),
                )
                _audit(
                    cur,
                    worker_id,
                    "workflow_step_failed",
                    "workflow_step",
                    str(task["step_id"]),
                    str(task["workflow_id"]) if task["workflow_id"] else None,
                    str(task["step_id"]),
                    str(task["task_id"]),
                )

            if task["workflow_id"] is not None:
                cur.execute(
                    """
                    UPDATE workflows
                    SET status = 'failed',
                        completed_at = now(),
                        error_details = %s,
                        updated_at = now()
                    WHERE workflow_id = %s
                    """,
                    (error_details, task["workflow_id"]),
                )
                _audit(
                    cur,
                    worker_id,
                    "workflow_failed",
                    "workflow",
                    str(task["workflow_id"]),
                    str(task["workflow_id"]),
                    str(task["step_id"]) if task["step_id"] else None,
                    str(task["task_id"]),
                )


def _mark_task_failed_only(
    conn: psycopg.Connection,
    worker_id: str,
    task: dict,
    error_details: str,
) -> None:
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE tasks
                SET status = 'failed',
                    error_details = %s,
                    completed_at = now(),
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    updated_at = now()
                WHERE task_id = %s
                """,
                (error_details, task["task_id"]),
            )
            cur.execute(
                """
                UPDATE task_attempts
                SET status = 'failed',
                    ended_at = now(),
                    error_details = %s
                WHERE task_id = %s
                  AND attempt_number = %s
                """,
                (error_details, task["task_id"], task["attempts"]),
            )
            _audit(
                cur,
                worker_id,
                "task_failed",
                "task",
                str(task["task_id"]),
                str(task["workflow_id"]) if task["workflow_id"] else None,
                str(task["step_id"]) if task["step_id"] else None,
                str(task["task_id"]),
                {"error": error_details},
            )


def _complete_task_and_advance(
    conn: psycopg.Connection,
    worker_id: str,
    task: dict,
    logger: logging.Logger,
    output_json: dict | None = None,
) -> None:
    payload = output_json if output_json is not None else {"status": "ok"}
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE tasks
                SET status = 'completed',
                    output_json = %s,
                    completed_at = now(),
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    updated_at = now()
                WHERE task_id = %s
                """,
                (Json(payload), task["task_id"]),
            )
            cur.execute(
                """
                UPDATE task_attempts
                SET status = 'completed',
                    ended_at = now()
                WHERE task_id = %s
                  AND attempt_number = %s
                """,
                (task["task_id"], task["attempts"]),
            )
            _audit(
                cur,
                worker_id,
                "task_completed",
                "task",
                str(task["task_id"]),
                str(task["workflow_id"]) if task["workflow_id"] else None,
                str(task["step_id"]) if task["step_id"] else None,
                str(task["task_id"]),
            )

            if task["workflow_id"] is None:
                return

            if task["step_id"] is None:
                return

            cur.execute(
                """
                SELECT COUNT(*) FROM tasks
                WHERE step_id = %s AND status != 'completed'
                """,
                (task["step_id"],),
            )
            remaining = cur.fetchone()[0]
            if remaining != 0:
                return

            cur.execute(
                """
                UPDATE workflow_steps
                SET status = 'completed',
                    completed_at = now(),
                    updated_at = now()
                WHERE step_id = %s
                  AND status != 'completed'
                RETURNING step_key
                """,
                (task["step_id"],),
            )
            row = cur.fetchone()
            if not row:
                return
            step_key = row[0]
            _audit(
                cur,
                worker_id,
                "workflow_step_completed",
                "workflow_step",
                str(task["step_id"]),
                str(task["workflow_id"]),
                str(task["step_id"]),
                str(task["task_id"]),
                {"workflow_id": str(task["workflow_id"]), "step_key": str(step_key)},
            )
            logger.info("workflow step completed (step_id=%s)", task["step_id"])

            cur.execute(
                """
                SELECT COUNT(*) FROM workflow_steps
                WHERE workflow_id = %s AND status != 'completed'
                """,
                (task["workflow_id"],),
            )
            remaining_steps = cur.fetchone()[0]
            if remaining_steps == 0:
                cur.execute(
                    """
                    UPDATE workflows
                    SET status = 'completed',
                        completed_at = now(),
                        updated_at = now()
                    WHERE workflow_id = %s
                      AND status IN ('pending','running')
                    RETURNING workflow_id
                    """,
                    (task["workflow_id"],),
                )
                if cur.fetchone():
                    cur.execute(
                        """
                        SELECT COUNT(*) FROM workflow_steps
                        WHERE workflow_id = %s
                        """,
                        (task["workflow_id"],),
                    )
                    step_count = cur.fetchone()[0]
                    _audit(
                        cur,
                        worker_id,
                        "workflow_completed",
                        "workflow",
                        str(task["workflow_id"]),
                        str(task["workflow_id"]),
                        str(task["step_id"]),
                        str(task["task_id"]),
                        {"final_step_id": str(task["step_id"]), "step_count": step_count},
                    )
                    logger.info("workflow completed (workflow_id=%s)", task["workflow_id"])


def _execute_noop(conn: psycopg.Connection, worker_id: str, task: dict) -> None:
    duration = _env_int("NOOP_DURATION_SECONDS", 2)
    start_time = time.monotonic()
    next_renew = start_time + LEASE_RENEW_SECONDS
    while True:
        elapsed = time.monotonic() - start_time
        if elapsed >= duration:
            break
        time.sleep(min(0.5, duration - elapsed))
        if time.monotonic() >= next_renew:
            _renew_lease(conn, worker_id, task)
            next_renew = time.monotonic() + LEASE_RENEW_SECONDS


def _execute_stub(task: dict, logger: logging.Logger) -> dict:
    logger.info("stub handler executed (task_id=%s task_type=%s)", task["task_id"], task["task_type"])
    return {
        "stub": True,
        "task_type": task["task_type"],
        "note": "stub execution only",
    }


def _consume_web_fetch_results(
    conn: psycopg.Connection,
    worker_id: str,
    task: dict,
) -> dict:
    workflow_id = task.get("workflow_id")
    summary = {"sources_found": 0, "content_types": [], "total_bytes": 0}
    if workflow_id is None:
        with conn.transaction():
            with conn.cursor() as cur:
                _audit(
                    cur,
                    worker_id,
                    "tool_results_consumed",
                    "task",
                    str(task["task_id"]),
                    None,
                    str(task["step_id"]) if task.get("step_id") else None,
                    str(task["task_id"]),
                    summary,
                )
        return summary

    content_types = set()
    total_bytes = 0
    sources_found = 0

    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT te.output_ref
                FROM tool_executions te
                JOIN tasks t ON te.task_id = t.task_id
                WHERE t.workflow_id = %s
                  AND te.tool_name = 'web_fetch'
                  AND te.status = 'completed'
                ORDER BY te.started_at ASC
                """,
                (workflow_id,),
            )
            rows = cur.fetchall()
            for (output_ref,) in rows:
                if not output_ref:
                    continue
                try:
                    payload = json.loads(output_ref)
                except (TypeError, json.JSONDecodeError):
                    continue
                sources_found += 1
                content_type = payload.get("content_type")
                if isinstance(content_type, str) and content_type:
                    content_types.add(content_type)
                content_length = payload.get("content_length")
                if isinstance(content_length, int) and content_length >= 0:
                    total_bytes += content_length

            summary = {
                "sources_found": sources_found,
                "content_types": sorted(content_types),
                "total_bytes": total_bytes,
            }
            _audit(
                cur,
                worker_id,
                "tool_results_consumed",
                "task",
                str(task["task_id"]),
                str(task["workflow_id"]),
                str(task["step_id"]) if task.get("step_id") else None,
                str(task["task_id"]),
                summary,
            )
    return summary


def _plan_tool_invocation(
    conn: psycopg.Connection,
    worker_id: str,
    task: dict,
    tool: Tool,
    logger: logging.Logger,
) -> tuple[str, str, dict]:
    payload = {
        "task_id": str(task["task_id"]),
        "task_type": task["task_type"],
        "tool_name": tool.name,
    }
    if tool.name == "web_fetch":
        payload["url"] = os.getenv("WEB_FETCH_URL", "https://example.com")
    input_ref = json.dumps(payload, sort_keys=True)
    sandbox_type = os.getenv("TOOL_SANDBOX_TYPE", "none").lower()
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tool_executions (
                    task_id,
                    tool_name,
                    sandbox_type,
                    status,
                    input_ref,
                    output_ref
                ) VALUES (
                    %s, %s, %s, %s, %s, NULL
                )
                RETURNING tool_exec_id
                """,
                (task["task_id"], tool.name, sandbox_type, "running", input_ref),
            )
            tool_exec_id = cur.fetchone()[0]
            _audit(
                cur,
                worker_id,
                "tool_planned",
                "task",
                str(task["task_id"]),
                str(task["workflow_id"]) if task["workflow_id"] else None,
                str(task["step_id"]) if task["step_id"] else None,
                str(task["task_id"]),
                {"tool_name": tool.name, "tool_exec_id": str(tool_exec_id)},
            )
    logger.info("tool planned (task_id=%s tool_name=%s)", task["task_id"], tool.name)
    return str(tool_exec_id), sandbox_type, payload


def _execute_web_fetch(
    conn: psycopg.Connection,
    worker_id: str,
    task: dict,
    planned_tool_exec_id: str,
    input_payload: dict,
    logger: logging.Logger,
) -> None:
    url = input_payload.get("url")
    if not isinstance(url, str) or not url:
        _record_tool_execution_result(
            conn,
            worker_id,
            task,
            planned_tool_exec_id,
            status="failed",
            output_metadata={"error_details": "missing_url"},
            exit_code=1,
            input_payload=input_payload,
        )
        return
    try:
        response = requests.get(
            url,
            timeout=WEB_FETCH_TIMEOUT_SECONDS,
            allow_redirects=False,
            stream=True,
        )
        content_length_header = response.headers.get("Content-Length")
        if content_length_header is not None:
            try:
                content_length_val = int(content_length_header)
            except ValueError as exc:
                raise ValueError("invalid_content_length") from exc
            if content_length_val > MAX_WEB_FETCH_BYTES:
                raise ValueError("response_too_large")

        bytes_read = 0
        for chunk in response.iter_content(chunk_size=65536):
            if not chunk:
                continue
            bytes_read += len(chunk)
            if bytes_read > MAX_WEB_FETCH_BYTES:
                raise ValueError("response_too_large")

        metadata = {
            "status_code": response.status_code,
            "content_length": bytes_read,
            "content_type": response.headers.get("Content-Type"),
        }
        _record_tool_execution_result(
            conn,
            worker_id,
            task,
            planned_tool_exec_id,
            status="completed",
            output_metadata=metadata,
            exit_code=0,
            input_payload=input_payload,
        )
        logger.info("tool executed (task_id=%s tool_name=web_fetch)", task["task_id"])
    except Exception as exc:
        _record_tool_execution_result(
            conn,
            worker_id,
            task,
            planned_tool_exec_id,
            status="failed",
            output_metadata={"error_details": str(exc)},
            exit_code=1,
            input_payload=input_payload,
        )
        logger.error(
            "tool execution failed (task_id=%s tool_name=web_fetch error=%s)",
            task["task_id"],
            exc,
        )


def _record_tool_execution_result(
    conn: psycopg.Connection,
    worker_id: str,
    task: dict,
    planned_tool_exec_id: str,
    status: str,
    output_metadata: dict,
    exit_code: int,
    input_payload: dict,
) -> None:
    payload = dict(output_metadata)
    payload["planned_tool_exec_id"] = planned_tool_exec_id
    input_ref = json.dumps(input_payload, sort_keys=True)
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tool_executions (
                    task_id,
                    tool_name,
                    sandbox_type,
                    status,
                    input_ref,
                    output_ref,
                    started_at,
                    ended_at,
                    exit_code
                ) VALUES (
                    %s, %s, 'local', %s, %s, %s, now(), now(), %s
                )
                RETURNING tool_exec_id
                """,
                (
                    task["task_id"],
                    "web_fetch",
                    status,
                    input_ref,
                    json.dumps(payload, sort_keys=True),
                    exit_code,
                ),
            )
            tool_exec_id = cur.fetchone()[0]
            _audit(
                cur,
                worker_id,
                "tool_executed",
                "tool_execution",
                str(tool_exec_id),
                str(task["workflow_id"]) if task["workflow_id"] else None,
                str(task["step_id"]) if task["step_id"] else None,
                str(task["task_id"]),
                {"planned_tool_exec_id": planned_tool_exec_id, "tool_exec_id": str(tool_exec_id)},
            )


def _process_task(conn: psycopg.Connection, worker_id: str, task: dict, logger: logging.Logger) -> None:
    if task["attempts"] > task["max_attempts"]:
        _mark_failed(conn, worker_id, task, "max_attempts_exceeded")
        return

    task_type = task["task_type"]
    if task_type == "noop":
        _execute_noop(conn, worker_id, task)
        _complete_task_and_advance(conn, worker_id, task, logger)
        logger.info("task completed (task_id=%s)", task["task_id"])
        return

    if task_type in STUB_TASK_TYPES:
        tool_name = TASK_TOOL_MAPPING.get(task_type)
        if tool_name is None:
            logger.error("no tool mapping for task_type (task_id=%s task_type=%s)", task["task_id"], task_type)
            _mark_task_failed_only(conn, worker_id, task, "missing_tool_mapping")
            return
        tool = TOOL_REGISTRY.get(tool_name)
        if tool is None:
            logger.error("tool not registered (task_id=%s tool_name=%s)", task["task_id"], tool_name)
            _mark_task_failed_only(conn, worker_id, task, "tool_not_registered")
            return
        tool_exec_id, sandbox_type, input_payload = _plan_tool_invocation(
            conn, worker_id, task, tool, logger
        )
        if tool.name == "web_fetch" and sandbox_type == "local":
            _execute_web_fetch(conn, worker_id, task, tool_exec_id, input_payload, logger)
        output = _execute_stub(task, logger)
        if task_type == "read_sources":
            summary = _consume_web_fetch_results(conn, worker_id, task)
            output["summary"] = summary
        _complete_task_and_advance(conn, worker_id, task, logger, output_json=output)
        logger.info("task completed (task_id=%s)", task["task_id"])
        return

    logger.error("unknown task_type encountered (task_id=%s task_type=%s)", task["task_id"], task_type)
    _mark_task_failed_only(conn, worker_id, task, "unknown_task_type")


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
    logger = logging.getLogger("worker")

    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL is required")

    worker_id = os.getenv("WORKER_ID") or str(uuid.uuid4())
    listen_host = os.getenv("WORKER_HOST", "0.0.0.0")
    listen_port = _env_int("WORKER_PORT", 8001)
    readiness_interval = _env_int("READINESS_CHECK_SECONDS", 10)

    stop_event = threading.Event()
    readiness = _ReadinessState()

    def handle_signal(signum: int, _frame: object) -> None:
        logger.info("shutdown signal received: %s", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    handler_cls = _make_handler(readiness)
    httpd = ThreadingHTTPServer((listen_host, listen_port), handler_cls)
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()

    conn = None
    try:
        conn = psycopg.connect(dsn)
        _recovery_scan(conn, logger)
    except Exception as exc:
        logger.error("db connection failed on startup: %s", exc)

    last_ready = None
    logger.info("worker started (worker_id=%s), readiness checks every %ss", worker_id, readiness_interval)

    def check_readiness() -> tuple[bool, str]:
        nonlocal conn
        try:
            if conn is None or conn.closed:
                conn = psycopg.connect(dsn)
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            ok, msg = _check_required_tables(conn)
            if not ok:
                return False, msg
            ok, msg = _write_heartbeat(conn, worker_id)
            if not ok:
                return False, msg
            ok, msg = _sandbox_check()
            if not ok:
                return False, msg
            return True, "ready"
        except Exception as exc:
            return False, f"db check failed: {exc}"

    ready, message = check_readiness()
    readiness.set(ready, message)
    state = "READY" if ready else "NOT READY"
    logger.info("readiness state: %s (%s)", state, message)
    last_ready = ready

    poll_interval = _env_int("WORKER_POLL_SECONDS", 5)
    last_ready_check = 0.0

    while not stop_event.is_set():
        now = time.monotonic()
        if now - last_ready_check >= readiness_interval:
            ready, message = check_readiness()
            readiness.set(ready, message)
            if last_ready != ready:
                state = "READY" if ready else "NOT READY"
                logger.info("readiness state: %s (%s)", state, message)
                last_ready = ready
            last_ready_check = now

        if readiness.get()[0]:
            try:
                task = _claim_task(conn, worker_id, logger) if conn is not None else None
            except Exception as exc:
                logger.error("task claim failed: %s", exc)
                task = None

            if task is not None:
                try:
                    _process_task(conn, worker_id, task, logger)
                except Exception as exc:
                    logger.error("task execution failed: %s", exc)
                    try:
                        _mark_failed(conn, worker_id, task, f"execution_error: {exc}")
                    except Exception as inner_exc:
                        logger.error("failed to mark task failed: %s", inner_exc)
                continue

        stop_event.wait(poll_interval)

    logger.info("shutting down")
    httpd.shutdown()
    httpd.server_close()
    server_thread.join(timeout=5)
    if conn is not None:
        conn.close()
    logger.info("shutdown complete")


if __name__ == "__main__":
    main()
