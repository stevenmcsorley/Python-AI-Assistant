import hashlib
import json
import logging
import os
import signal
import subprocess
import tempfile
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from dataclasses import dataclass
from html.parser import HTMLParser

import psycopg
import requests
from psycopg.rows import dict_row
from psycopg.types.json import Json

from .messages import Message, MessageWriter, deliver_queued_message
from .messages.providers import BaileysProvider, DeliveryProvider, WhatsAppStubProvider
from .llm import DeepSeekError, DeepSeekResponse, run_chat_completion

REQUIRED_TABLES = ("tasks", "task_attempts", "audit_log")
LEASE_DURATION_SECONDS = 120
LEASE_RENEW_SECONDS = 30
MAX_WEB_FETCH_BYTES = 256 * 1024
WEB_FETCH_TIMEOUT_SECONDS = 5
MAX_SYNTHESIS_INPUT_BYTES = 1048576
BRAVE_SEARCH_TIMEOUT_SECONDS = 10
BRAVE_SEARCH_MAX_RESULTS = 5
BRAVE_SEARCH_MAX_QUERY_CHARS = 200
READ_SOURCE_MAX_BYTES = 256 * 1024
READ_SOURCE_MAX_CHARS = 4000
READ_SOURCE_MAX_TOTAL_CHARS = 20000


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


def _select_delivery_provider(logger: logging.Logger) -> DeliveryProvider:
    provider_name = (os.getenv("WHATSAPP_PROVIDER") or "stub").strip().lower()
    if provider_name == "baileys":
        logger.info("message delivery provider: baileys")
        return BaileysProvider()
    if provider_name in ("stub", "whatsapp_stub", ""):
        logger.info("message delivery provider: whatsapp_stub")
        return WhatsAppStubProvider()
    logger.warning("unknown WHATSAPP_PROVIDER '%s'; using whatsapp_stub", provider_name)
    return WhatsAppStubProvider()


def _configure_logging(service: str, worker_id: str) -> None:
    old_factory = logging.getLogRecordFactory()

    def record_factory(*args, **kwargs):  # type: ignore[override]
        record = old_factory(*args, **kwargs)
        if not hasattr(record, "service"):
            record.service = service
        if not hasattr(record, "worker_id"):
            record.worker_id = worker_id
        if not hasattr(record, "entity_id"):
            record.entity_id = "-"
        return record

    logging.setLogRecordFactory(record_factory)
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s service=%(service)s worker_id=%(worker_id)s entity_id=%(entity_id)s message=%(message)s",
    )


def _validate_env() -> dict:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL is required")

    deepseek_key = os.getenv("DEEPSEEK_API_KEY")
    deepseek_base = os.getenv("DEEPSEEK_API_BASE")

    return {
        "database_url_set": True,
        "deepseek_key_set": bool(deepseek_key),
        "deepseek_base_set": bool(deepseek_base),
        "deepseek_enabled": bool(deepseek_key and deepseek_base),
    }


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


def _audit_invariant_violation(
    cur: psycopg.Cursor,
    actor_id: str,
    entity_type: str,
    entity_id: str,
    reason: str,
    metadata: dict | None = None,
) -> None:
    payload = {"reason": reason}
    if metadata:
        payload.update(metadata)
    _audit(
        cur,
        actor_id,
        "invariant_violation",
        entity_type,
        entity_id,
        payload.get("workflow_id"),
        payload.get("step_id"),
        payload.get("task_id"),
        payload,
    )


def _audit_worker_shutdown(conn: psycopg.Connection, worker_id: str) -> None:
    try:
        with conn.transaction():
            with conn.cursor() as cur:
                _audit(
                    cur,
                    worker_id,
                    "worker_shutdown",
                    "worker",
                    worker_id,
                    None,
                    None,
                    None,
                    {},
                )
    except Exception:
        return


def _expire_lease(conn: psycopg.Connection, worker_id: str, task_id: str) -> None:
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE tasks
                SET lease_expires_at = now(),
                    updated_at = now()
                WHERE task_id = %s
                  AND lease_owner = %s
                  AND status = 'running'
                """,
                (task_id, worker_id),
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
            if cur.rowcount == 0:
                _audit_invariant_violation(
                    cur,
                    worker_id,
                    "task",
                    str(task["task_id"]),
                    "lease_renew_rejected",
                    {
                        "workflow_id": str(task["workflow_id"]) if task["workflow_id"] else None,
                        "step_id": str(task["step_id"]) if task["step_id"] else None,
                        "task_id": str(task["task_id"]),
                    },
                )
                return
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
    audit_metadata: dict | None = None,
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
                  AND status = 'running'
                  AND lease_owner = %s
                  AND EXISTS (
                      SELECT 1
                      FROM task_attempts
                      WHERE task_id = %s
                        AND attempt_number = %s
                        AND status = 'running'
                        AND worker_id = %s
                  )
                """,
                (
                    error_details,
                    task["task_id"],
                    worker_id,
                    task["task_id"],
                    task["attempts"],
                    worker_id,
                ),
            )
            if cur.rowcount == 0:
                _audit_invariant_violation(
                    cur,
                    worker_id,
                    "task",
                    str(task["task_id"]),
                    "task_fail_rejected",
                    {
                        "workflow_id": str(task["workflow_id"]) if task["workflow_id"] else None,
                        "step_id": str(task["step_id"]) if task["step_id"] else None,
                        "task_id": str(task["task_id"]),
                    },
                )
                return
            cur.execute(
                """
                UPDATE task_attempts
                SET status = 'failed',
                    ended_at = now(),
                    error_details = %s
                WHERE task_id = %s
                  AND attempt_number = %s
                  AND status = 'running'
                  AND worker_id = %s
                """,
                (error_details, task["task_id"], task["attempts"], worker_id),
            )
            if cur.rowcount == 0:
                _audit_invariant_violation(
                    cur,
                    worker_id,
                    "task_attempt",
                    str(task["task_id"]),
                    "task_attempt_fail_rejected",
                    {"task_id": str(task["task_id"]), "attempt": task["attempts"]},
                )
                return
            metadata = {"error": error_details}
            if audit_metadata:
                metadata.update(audit_metadata)
            _audit(
                cur,
                worker_id,
                "task_failed",
                "task",
                str(task["task_id"]),
                str(task["workflow_id"]) if task["workflow_id"] else None,
                str(task["step_id"]) if task["step_id"] else None,
                str(task["task_id"]),
                metadata,
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
                      AND status != 'failed'
                    """,
                    (error_details, task["step_id"]),
                )
                if cur.rowcount:
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
                      AND status != 'failed'
                    """,
                    (error_details, task["workflow_id"]),
                )
                if cur.rowcount:
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
    audit_metadata: dict | None = None,
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
                  AND status = 'running'
                  AND lease_owner = %s
                  AND EXISTS (
                      SELECT 1
                      FROM task_attempts
                      WHERE task_id = %s
                        AND attempt_number = %s
                        AND status = 'running'
                        AND worker_id = %s
                  )
                """,
                (
                    error_details,
                    task["task_id"],
                    worker_id,
                    task["task_id"],
                    task["attempts"],
                    worker_id,
                ),
            )
            if cur.rowcount == 0:
                _audit_invariant_violation(
                    cur,
                    worker_id,
                    "task",
                    str(task["task_id"]),
                    "task_fail_rejected",
                    {
                        "workflow_id": str(task["workflow_id"]) if task["workflow_id"] else None,
                        "step_id": str(task["step_id"]) if task["step_id"] else None,
                        "task_id": str(task["task_id"]),
                    },
                )
                return
            cur.execute(
                """
                UPDATE task_attempts
                SET status = 'failed',
                    ended_at = now(),
                    error_details = %s
                WHERE task_id = %s
                  AND attempt_number = %s
                  AND status = 'running'
                  AND worker_id = %s
                """,
                (error_details, task["task_id"], task["attempts"], worker_id),
            )
            if cur.rowcount == 0:
                _audit_invariant_violation(
                    cur,
                    worker_id,
                    "task_attempt",
                    str(task["task_id"]),
                    "task_attempt_fail_rejected",
                    {"task_id": str(task["task_id"]), "attempt": task["attempts"]},
                )
                return
            metadata = {"error": error_details}
            if audit_metadata:
                metadata.update(audit_metadata)
            _audit(
                cur,
                worker_id,
                "task_failed",
                "task",
                str(task["task_id"]),
                str(task["workflow_id"]) if task["workflow_id"] else None,
                str(task["step_id"]) if task["step_id"] else None,
                str(task["task_id"]),
                metadata,
            )


def _complete_task_and_advance(
    conn: psycopg.Connection,
    worker_id: str,
    task: dict,
    logger: logging.Logger,
    output_json: dict | None = None,
    audit_metadata: dict | None = None,
) -> None:
    payload = output_json if output_json is not None else {"status": "ok"}
    workflow_completed = False
    workflow_id = None
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
                  AND status = 'running'
                  AND lease_owner = %s
                  AND EXISTS (
                      SELECT 1
                      FROM task_attempts
                      WHERE task_id = %s
                        AND attempt_number = %s
                        AND status = 'running'
                        AND worker_id = %s
                  )
                """,
                (
                    Json(payload),
                    task["task_id"],
                    worker_id,
                    task["task_id"],
                    task["attempts"],
                    worker_id,
                ),
            )
            if cur.rowcount == 0:
                _audit_invariant_violation(
                    cur,
                    worker_id,
                    "task",
                    str(task["task_id"]),
                    "task_complete_rejected",
                    {
                        "workflow_id": str(task["workflow_id"]) if task["workflow_id"] else None,
                        "step_id": str(task["step_id"]) if task["step_id"] else None,
                        "task_id": str(task["task_id"]),
                    },
                )
                return
            cur.execute(
                """
                UPDATE task_attempts
                SET status = 'completed',
                    ended_at = now()
                WHERE task_id = %s
                  AND attempt_number = %s
                  AND status = 'running'
                  AND worker_id = %s
                """,
                (task["task_id"], task["attempts"], worker_id),
            )
            if cur.rowcount == 0:
                _audit_invariant_violation(
                    cur,
                    worker_id,
                    "task_attempt",
                    str(task["task_id"]),
                    "task_attempt_complete_rejected",
                    {"task_id": str(task["task_id"]), "attempt": task["attempts"]},
                )
                return
            _audit(
                cur,
                worker_id,
                "task_completed",
                "task",
                str(task["task_id"]),
                str(task["workflow_id"]) if task["workflow_id"] else None,
                str(task["step_id"]) if task["step_id"] else None,
                str(task["task_id"]),
                audit_metadata or {},
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
                  AND status = 'pending'
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
                    workflow_completed = True
                    workflow_id = str(task["workflow_id"])

    if workflow_completed and workflow_id:
        _finalize_workflow_output_and_note(conn, worker_id, workflow_id, logger)


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


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def _collect_synthesis_inputs(conn: psycopg.Connection, task: dict) -> tuple[list[str], list[dict]]:
    if task.get("workflow_id") is None:
        return [], []
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT t.task_id, t.task_type, t.output_json, ws.step_key, ws.step_index
            FROM tasks t
            JOIN workflow_steps ws ON ws.step_id = t.step_id
            WHERE t.workflow_id = %s
              AND t.task_id != %s
              AND t.status = 'completed'
              AND t.output_json IS NOT NULL
            ORDER BY ws.step_index ASC, t.created_at ASC
            """,
            (task["workflow_id"], task["task_id"]),
        )
        rows = cur.fetchall()
    input_task_ids = [str(row["task_id"]) for row in rows]
    inputs = [
        {
            "step_key": str(row["step_key"]),
            "task_type": str(row["task_type"]),
            "output": row["output_json"],
        }
        for row in rows
    ]
    return input_task_ids, inputs


def _execute_synthesize_llm(
    conn: psycopg.Connection,
    task: dict,
    logger: logging.Logger,
) -> tuple[dict | None, str | None, int, int]:
    start = time.monotonic()
    input_task_ids, inputs = _collect_synthesis_inputs(conn, task)
    input_count = len(inputs)
    if not inputs:
        return None, "missing_inputs", _elapsed_ms(start), input_count

    try:
        payload = {
            "workflow_id": str(task["workflow_id"]) if task.get("workflow_id") else None,
            "inputs": inputs,
        }
        inputs_json = json.dumps(payload, sort_keys=True)
    except (TypeError, ValueError):
        return None, "input_serialization_failed", _elapsed_ms(start), input_count

    if len(inputs_json.encode("utf-8")) > MAX_SYNTHESIS_INPUT_BYTES:
        return None, "input_too_large", _elapsed_ms(start), input_count

    api_key = os.getenv("DEEPSEEK_API_KEY")
    api_base = os.getenv("DEEPSEEK_API_BASE")
    try:
        response: DeepSeekResponse = run_chat_completion(api_key, api_base, inputs_json)
    except DeepSeekError as exc:
        logger.error("deepseek request failed (task_id=%s reason=%s)", task["task_id"], exc.reason)
        return None, exc.reason, _elapsed_ms(start), input_count

    summary = response.summary.strip()
    if not summary:
        return None, "empty_response", _elapsed_ms(start), input_count

    output = {
        "model": "deepseek-chat",
        "summary": summary,
        "input_task_ids": input_task_ids,
        "token_usage": {
            "prompt": response.prompt_tokens,
            "completion": response.completion_tokens,
        },
    }
    return output, None, _elapsed_ms(start), input_count


def _create_workflow_output(
    conn: psycopg.Connection,
    worker_id: str,
    workflow_id: str,
    logger: logging.Logger,
) -> str | None:
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.workflow_outputs')")
            if cur.fetchone()[0] is None:
                logger.warning("workflow_outputs table missing; skipping output aggregation")
                return None

            cur.execute(
                """
                SELECT workflow_output_id
                FROM workflow_outputs
                WHERE workflow_id = %s
                LIMIT 1
                """,
                (workflow_id,),
            )
            row = cur.fetchone()
            if row:
                return str(row[0])

            cur.execute(
                """
                SELECT type, completed_at
                FROM workflows
                WHERE workflow_id = %s
                """,
                (workflow_id,),
            )
            workflow_row = cur.fetchone()
            if not workflow_row:
                return None
            workflow_type, completed_at = workflow_row

            cur.execute(
                """
                SELECT step_id, step_key
                FROM workflow_steps
                WHERE workflow_id = %s
                ORDER BY step_index ASC
                """,
                (workflow_id,),
            )
            steps = []
            task_count = 0
            for step_id, step_key in cur.fetchall():
                cur.execute(
                    """
                    SELECT task_type, output_json
                    FROM tasks
                    WHERE step_id = %s
                    ORDER BY created_at ASC
                    """,
                    (step_id,),
                )
                task_rows = cur.fetchall()
                task_count += len(task_rows)
                tasks = [
                    {"task_type": task_type, "output_json": output_json}
                    for task_type, output_json in task_rows
                ]
                steps.append({"step_key": step_key, "tasks": tasks})

            output = {
                "workflow_id": workflow_id,
                "workflow_type": workflow_type,
                "completed_at": completed_at.isoformat() if completed_at else None,
                "steps": steps,
                "summary": {"step_count": len(steps), "task_count": task_count},
            }

            cur.execute(
                """
                INSERT INTO workflow_outputs (
                    workflow_id,
                    output_json,
                    created_at
                ) VALUES (%s, %s, now())
                RETURNING workflow_output_id
                """,
                (workflow_id, Json(output)),
            )
            workflow_output_id = cur.fetchone()[0]
            _audit(
                cur,
                worker_id,
                "workflow_output_created",
                "workflow_output",
                str(workflow_output_id),
                workflow_id,
                None,
                None,
            )
            return str(workflow_output_id)


def _render_obsidian_note(
    workflow_type: str,
    workflow_id: str,
    created_at: datetime,
    summary: dict,
) -> str:
    summary_json = json.dumps(summary, indent=2, sort_keys=True)
    title = f"{workflow_type} - {workflow_id}"
    return (
        "---\n"
        "status: draft\n"
        "---\n\n"
        f"# {title}\n\n"
        f"Workflow Type: {workflow_type}\n\n"
        f"Created: {created_at.isoformat()}\n\n"
        "## Summary (JSON)\n\n"
        "```json\n"
        f"{summary_json}\n"
        "```\n"
    )


def _atomic_write(path: str, content: str) -> None:
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", suffix=".md", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _write_obsidian_note(
    conn: psycopg.Connection,
    worker_id: str,
    workflow_id: str,
    workflow_output_id: str,
    logger: logging.Logger,
) -> None:
    vault_path = os.getenv("OBSIDIAN_VAULT_PATH")
    if not vault_path:
        logger.warning("OBSIDIAN_VAULT_PATH not set; skipping note creation")
        return

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT w.type, w.completed_at, w.user_id, wo.output_json, wo.created_at
            FROM workflow_outputs wo
            JOIN workflows w ON w.workflow_id = wo.workflow_id
            WHERE wo.workflow_id = %s
            """,
            (workflow_id,),
        )
        row = cur.fetchone()

    if not row:
        return

    workflow_type = row["type"]
    completed_at = row["completed_at"]
    user_id = row["user_id"]
    created_at = row["created_at"] or completed_at or datetime.now(timezone.utc)
    output_json = row["output_json"]
    if isinstance(output_json, str):
        try:
            output_json = json.loads(output_json)
        except json.JSONDecodeError:
            output_json = {}
    summary = {}
    if isinstance(output_json, dict):
        summary = output_json.get("summary") or {}

    file_date = (completed_at or created_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    filename = f"{file_date} -- {workflow_type} -- {workflow_id}.md"
    file_path = os.path.join(vault_path, filename)

    if os.path.exists(file_path):
        return

    note_content = _render_obsidian_note(workflow_type, workflow_id, created_at, summary)
    try:
        _atomic_write(file_path, note_content)
    except Exception as exc:
        logger.error("failed to write obsidian note (workflow_id=%s error=%s)", workflow_id, exc)
        return

    with conn.transaction():
        with conn.cursor() as cur:
            _audit(
                cur,
                worker_id,
                "obsidian_note_created",
                "workflow",
                workflow_id,
                workflow_id,
                None,
                None,
                {"file_path": file_path, "workflow_output_id": workflow_output_id},
            )
            message_writer = MessageWriter("", actor_id=worker_id, actor_type="worker")
            message = Message(
                user_id=str(user_id),
                channel="whatsapp",
                message_type="workflow_completed",
                body="Your preparation is ready. I've created a draft note for you.",
                status="queued",
                related_entity_type="workflow",
                related_entity_id=workflow_id,
            )
            message_writer.write(message, cur=cur)
    logger.info("obsidian note created (workflow_id=%s path=%s)", workflow_id, file_path)


def _finalize_workflow_output_and_note(
    conn: psycopg.Connection,
    worker_id: str,
    workflow_id: str,
    logger: logging.Logger,
) -> None:
    workflow_output_id = _create_workflow_output(conn, worker_id, workflow_id, logger)
    if workflow_output_id:
        _write_obsidian_note(conn, worker_id, workflow_id, workflow_output_id, logger)


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


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []

    def handle_data(self, data: str) -> None:
        if data and data.strip():
            self._chunks.append(data.strip())

    def get_text(self) -> str:
        return " ".join(self._chunks)


def _extract_text_from_html(content: bytes, max_chars: int) -> str:
    try:
        text = content.decode("utf-8", errors="replace")
    except Exception:
        text = content.decode("latin-1", errors="replace")
    parser = _HTMLTextExtractor()
    parser.feed(text)
    raw = parser.get_text()
    collapsed = " ".join(raw.split())
    if len(collapsed) > max_chars:
        return collapsed[:max_chars]
    return collapsed


def _fetch_page_text(url: str) -> tuple[dict | None, str | None]:
    try:
        response = requests.get(
            url,
            timeout=WEB_FETCH_TIMEOUT_SECONDS,
            allow_redirects=False,
            stream=True,
            headers={"User-Agent": "Python-AI-Assistant/1.0"},
        )
    except requests.RequestException as exc:
        return None, f"request_error:{exc}"

    if response.status_code != 200:
        return None, f"bad_status:{response.status_code}"
    content_type = response.headers.get("Content-Type") or ""
    if content_type and not content_type.startswith("text/"):
        return {
            "url": url,
            "content_type": content_type,
            "content_length": response.headers.get("Content-Length"),
            "text": "",
            "error": "unsupported_content_type",
        }, None

    data = response.raw.read(READ_SOURCE_MAX_BYTES, decode_content=True)
    text = _extract_text_from_html(data, READ_SOURCE_MAX_CHARS)
    return {
        "url": url,
        "content_type": content_type,
        "content_length": len(data),
        "text": text,
    }, None


def _get_step_query(conn: psycopg.Connection, step_id: str | None) -> str | None:
    if not step_id:
        return None
    with conn.cursor() as cur:
        cur.execute(
            "SELECT input_json FROM workflow_steps WHERE step_id = %s",
            (step_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    value = row[0]
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    if isinstance(value, dict):
        query = value.get("query")
        if isinstance(query, str) and query.strip():
            return query.strip()
    return None


def _brave_search(query: str, max_results: int) -> tuple[list[dict], str | None]:
    api_key = os.getenv("BRAVE_SEARCH_API_KEY")
    if not api_key:
        return [], "missing_brave_api_key"
    base_url = os.getenv("BRAVE_SEARCH_API_BASE", "https://api.search.brave.com/res/v1/web/search")
    params = {
        "q": query,
        "count": max_results,
    }
    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": api_key,
    }
    try:
        response = requests.get(
            base_url,
            headers=headers,
            params=params,
            timeout=BRAVE_SEARCH_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        return [], f"request_error:{exc}"
    if response.status_code != 200:
        return [], f"bad_status:{response.status_code}"
    try:
        payload = response.json()
    except ValueError:
        return [], "invalid_json"
    results = payload.get("web", {}).get("results", [])
    if not isinstance(results, list):
        return [], "invalid_results"
    normalized: list[dict] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        url = item.get("url") or item.get("link")
        if not isinstance(url, str) or not url:
            continue
        entry = {
            "url": url,
            "title": str(item.get("title") or ""),
            "description": str(item.get("description") or ""),
        }
        normalized.append(entry)
        if len(normalized) >= max_results:
            break
    return normalized, None


def _collect_fetch_sources_results(conn: psycopg.Connection, workflow_id: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT output_json
            FROM tasks
            WHERE workflow_id = %s
              AND task_type = 'fetch_sources'
              AND status = 'completed'
            ORDER BY created_at ASC
            """,
            (workflow_id,),
        )
        rows = cur.fetchall()
    results: list[dict] = []
    for (output_json,) in rows:
        if not output_json:
            continue
        payload = output_json
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                continue
        if isinstance(payload, dict):
            items = payload.get("results") or []
            if isinstance(items, list):
                results.extend([item for item in items if isinstance(item, dict)])
    return results


def _execute_fetch_sources(
    conn: psycopg.Connection,
    task: dict,
    logger: logging.Logger,
) -> tuple[dict | None, str | None, dict]:
    query = _get_step_query(conn, str(task.get("step_id")))
    if not query:
        return None, "missing_query", {"reason": "missing_query"}
    if len(query) > BRAVE_SEARCH_MAX_QUERY_CHARS:
        return None, "query_too_long", {"reason": "query_too_long"}
    max_results = _env_int("BRAVE_SEARCH_MAX_RESULTS", BRAVE_SEARCH_MAX_RESULTS)
    max_results = max(1, min(max_results, 10))
    results, error = _brave_search(query, max_results)
    if error:
        logger.error("brave search failed (task_id=%s reason=%s)", task["task_id"], error)
        return None, error, {"reason": error}
    output = {
        "query": query,
        "results": results,
        "result_count": len(results),
    }
    metadata = {"source_count": len(results)}
    return output, None, metadata


def _execute_read_sources(
    conn: psycopg.Connection,
    task: dict,
    logger: logging.Logger,
) -> tuple[dict | None, str | None, dict]:
    workflow_id = str(task.get("workflow_id") or "")
    if not workflow_id:
        return None, "missing_workflow", {"reason": "missing_workflow"}
    results = _collect_fetch_sources_results(conn, workflow_id)
    if not results:
        output = {"sources": [], "source_count": 0}
        return output, None, {"source_count": 0}

    sources: list[dict] = []
    total_chars = 0
    for item in results:
        url = item.get("url")
        if not isinstance(url, str) or not url:
            continue
        if total_chars >= READ_SOURCE_MAX_TOTAL_CHARS:
            break
        page_data, error = _fetch_page_text(url)
        if error:
            sources.append({"url": url, "error": error})
            continue
        if not page_data:
            continue
        text = page_data.get("text") or ""
        if isinstance(text, str):
            remaining = READ_SOURCE_MAX_TOTAL_CHARS - total_chars
            if len(text) > remaining:
                text = text[:remaining]
            total_chars += len(text)
            page_data["text"] = text
        page_data["title"] = item.get("title") or ""
        sources.append(page_data)

    output = {"sources": sources, "source_count": len(sources)}
    metadata = {"source_count": len(sources)}
    return output, None, metadata


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
    if task_type == "fetch_sources":
        output, failure_reason, metadata = _execute_fetch_sources(conn, task, logger)
        if failure_reason:
            _mark_task_failed_only(
                conn,
                worker_id,
                task,
                failure_reason,
                audit_metadata={"reason": failure_reason},
            )
            logger.error("fetch_sources failed (task_id=%s reason=%s)", task["task_id"], failure_reason)
            return
        _complete_task_and_advance(conn, worker_id, task, logger, output_json=output, audit_metadata=metadata)
        logger.info("task completed (task_id=%s)", task["task_id"])
        return

    if task_type == "read_sources":
        output, failure_reason, metadata = _execute_read_sources(conn, task, logger)
        if failure_reason:
            _mark_task_failed_only(
                conn,
                worker_id,
                task,
                failure_reason,
                audit_metadata={"reason": failure_reason},
            )
            logger.error("read_sources failed (task_id=%s reason=%s)", task["task_id"], failure_reason)
            return
        _complete_task_and_advance(conn, worker_id, task, logger, output_json=output, audit_metadata=metadata)
        logger.info("task completed (task_id=%s)", task["task_id"])
        return

    if task_type == "synthesize":
        output, failure_reason, duration_ms, input_count = _execute_synthesize_llm(
            conn, task, logger
        )
        if failure_reason:
            _mark_task_failed_only(
                conn,
                worker_id,
                task,
                failure_reason,
                audit_metadata={
                    "model": "deepseek-chat",
                    "reason": failure_reason,
                    "duration_ms": duration_ms,
                    "input_count": input_count,
                },
            )
            logger.error("synthesize failed (task_id=%s reason=%s)", task["task_id"], failure_reason)
            return
        _complete_task_and_advance(
            conn,
            worker_id,
            task,
            logger,
            output_json=output,
            audit_metadata={
                "model": "deepseek-chat",
                "duration_ms": duration_ms,
                "input_count": input_count,
            },
        )
        logger.info("task completed (task_id=%s)", task["task_id"])
        return

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
    config = _validate_env()
    worker_id = os.getenv("WORKER_ID") or str(uuid.uuid4())
    _configure_logging("worker", worker_id)
    logger = logging.getLogger("worker")

    dsn = os.getenv("DATABASE_URL") or ""
    logger.info(
        "config validated: deepseek_enabled=%s deepseek_key_set=%s deepseek_base_set=%s",
        config["deepseek_enabled"],
        config["deepseek_key_set"],
        config["deepseek_base_set"],
    )
    listen_host = os.getenv("WORKER_HOST", "0.0.0.0")
    listen_port = _env_int("WORKER_PORT", 8001)
    readiness_interval = _env_int("READINESS_CHECK_SECONDS", 10)
    delivery_interval = _env_int("MESSAGE_DELIVERY_INTERVAL_SECONDS", 5)
    delivery_provider = _select_delivery_provider(logger)

    stop_event = threading.Event()
    shutdown_requested = {"value": False}
    current_task_id = {"value": None}
    processing_task = {"value": False}
    readiness = _ReadinessState()

    def handle_signal(signum: int, _frame: object) -> None:
        logger.info("shutdown signal received: %s", signum)
        shutdown_requested["value"] = True
        readiness.set(False, "shutdown")
        if processing_task["value"]:
            logger.info("shutdown requested: finishing current task")
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
    ready_logged = False
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
    if ready and not ready_logged:
        logger.info("ready")
        ready_logged = True

    poll_interval = _env_int("WORKER_POLL_SECONDS", 5)
    last_ready_check = 0.0
    last_delivery_check = 0.0

    while not stop_event.is_set():
        now = time.monotonic()
        if now - last_ready_check >= readiness_interval:
            ready, message = check_readiness()
            readiness.set(ready, message)
            if last_ready != ready:
                state = "READY" if ready else "NOT READY"
                logger.info("readiness state: %s (%s)", state, message)
                last_ready = ready
            if ready and not ready_logged:
                logger.info("ready")
                ready_logged = True
            last_ready_check = now

        if readiness.get()[0] and now - last_delivery_check >= delivery_interval:
            if conn is not None:
                try:
                    deliver_queued_message(conn, worker_id, delivery_provider)
                except Exception as exc:
                    logger.error("message delivery failed: %s", exc)
            last_delivery_check = now

        if readiness.get()[0]:
            try:
                task = _claim_task(conn, worker_id, logger) if conn is not None else None
            except Exception as exc:
                logger.error("task claim failed: %s", exc)
                task = None

            if task is not None:
                current_task_id["value"] = str(task["task_id"])
                processing_task["value"] = True
                try:
                    _process_task(conn, worker_id, task, logger)
                except Exception as exc:
                    logger.error("task execution failed: %s", exc)
                    try:
                        _mark_failed(conn, worker_id, task, f"execution_error: {exc}")
                    except Exception as inner_exc:
                        logger.error("failed to mark task failed: %s", inner_exc)
                finally:
                    processing_task["value"] = False
                    current_task_id["value"] = None
                continue

        stop_event.wait(poll_interval)

    if shutdown_requested["value"] and conn is not None:
        if current_task_id["value"] and not processing_task["value"]:
            try:
                _expire_lease(conn, worker_id, current_task_id["value"])
            except Exception as exc:
                logger.error("failed to release lease on shutdown: %s", exc)
        _audit_worker_shutdown(conn, worker_id)

    logger.info("shutting down")
    httpd.shutdown()
    httpd.server_close()
    server_thread.join(timeout=5)
    if conn is not None:
        conn.close()
    logger.info("shutdown complete")


if __name__ == "__main__":
    main()
