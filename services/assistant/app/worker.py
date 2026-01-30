import hashlib
import logging
import os
import signal
import subprocess
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json


REQUIRED_TABLES = ("tasks", "task_attempts", "audit_log")
LEASE_DURATION_SECONDS = 120
LEASE_RENEW_SECONDS = 30

STUB_TASK_TYPES = {
    "fetch_sources",
    "read_sources",
    "synthesize",
    "write_note",
    "gather_context",
    "research_context",
    "write_brief",
    "gather_goals",
    "review_calendar",
    "write_plan",
}


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
                cur.execute(
                    """
                    SELECT COUNT(*) FROM workflow_steps
                    WHERE workflow_id = %s
                    """,
                    (task["workflow_id"],),
                )
                step_count = cur.fetchone()[0]
                if step_count != 0:
                    return

                cur.execute(
                    """
                    INSERT INTO workflow_checkpoints (
                        workflow_id,
                        step_name,
                        state_json,
                        created_by
                    ) VALUES (%s, %s, %s, %s)
                    RETURNING checkpoint_id
                    """,
                    (
                        task["workflow_id"],
                        "implicit_task_completion",
                        Json({"completed_task_id": str(task["task_id"])}),
                        worker_id,
                    ),
                )
                checkpoint_id = cur.fetchone()[0]
                _audit(
                    cur,
                    worker_id,
                    "workflow_checkpointed",
                    "workflow",
                    str(task["workflow_id"]),
                    str(task["workflow_id"]),
                    None,
                    str(task["task_id"]),
                )
                logger.info("workflow checkpoint written (workflow_id=%s)", task["workflow_id"])

                cur.execute(
                    """
                    UPDATE workflows
                    SET status = 'completed',
                        completed_at = now(),
                        checkpoint_id = %s,
                        updated_at = now()
                    WHERE workflow_id = %s
                    """,
                    (checkpoint_id, task["workflow_id"]),
                )
                _audit(
                    cur,
                    worker_id,
                    "workflow_completed",
                    "workflow",
                    str(task["workflow_id"]),
                    str(task["workflow_id"]),
                    None,
                    str(task["task_id"]),
                )
                logger.info("workflow marked completed (workflow_id=%s)", task["workflow_id"])
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
                RETURNING step_index, step_key
                """,
                (task["step_id"],),
            )
            row = cur.fetchone()
            if not row:
                return
            step_index, step_key = row
            _audit(
                cur,
                worker_id,
                "workflow_step_completed",
                "workflow_step",
                str(task["step_id"]),
                str(task["workflow_id"]),
                str(task["step_id"]),
                str(task["task_id"]),
            )
            logger.info("workflow step completed (step_id=%s)", task["step_id"])

            cur.execute(
                """
                SELECT step_id FROM workflow_steps
                WHERE workflow_id = %s AND step_index > %s
                ORDER BY step_index ASC
                LIMIT 1
                """,
                (task["workflow_id"], step_index),
            )
            next_step = cur.fetchone()

            cur.execute(
                """
                INSERT INTO workflow_checkpoints (
                    workflow_id,
                    step_name,
                    state_json,
                    created_by
                ) VALUES (%s, %s, %s, %s)
                RETURNING checkpoint_id
                """,
                (task["workflow_id"], step_key, Json({"completed_step_id": str(task["step_id"])}), worker_id),
            )
            checkpoint_id = cur.fetchone()[0]
            _audit(
                cur,
                worker_id,
                "workflow_checkpointed",
                "workflow",
                str(task["workflow_id"]),
                str(task["workflow_id"]),
                str(task["step_id"]),
                str(task["task_id"]),
            )
            logger.info("workflow checkpoint written (workflow_id=%s)", task["workflow_id"])

            if next_step is None:
                cur.execute(
                    """
                    UPDATE workflows
                    SET status = 'completed',
                        completed_at = now(),
                        checkpoint_id = %s,
                        updated_at = now()
                    WHERE workflow_id = %s
                    """,
                    (checkpoint_id, task["workflow_id"]),
                )
                _audit(
                    cur,
                    worker_id,
                    "workflow_completed",
                    "workflow",
                    str(task["workflow_id"]),
                    str(task["workflow_id"]),
                    str(task["step_id"]),
                    str(task["task_id"]),
                )
                logger.info("workflow marked completed (workflow_id=%s)", task["workflow_id"])
            else:
                cur.execute(
                    """
                    UPDATE workflows
                    SET current_step_id = %s,
                        checkpoint_id = %s,
                        updated_at = now()
                    WHERE workflow_id = %s
                    """,
                    (next_step[0], checkpoint_id, task["workflow_id"]),
                )
                _audit(
                    cur,
                    worker_id,
                    "workflow_advanced",
                    "workflow",
                    str(task["workflow_id"]),
                    str(task["workflow_id"]),
                    str(task["step_id"]),
                    str(task["task_id"]),
                    {"next_step_id": str(next_step[0])},
                )


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
        output = _execute_stub(task, logger)
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
