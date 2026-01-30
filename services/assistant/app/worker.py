import hashlib
import logging
import os
import signal
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import psycopg
from psycopg.types.json import Json


REQUIRED_TABLES = ("tasks", "task_attempts", "audit_log")


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

    while not stop_event.wait(readiness_interval):
        ready, message = check_readiness()
        readiness.set(ready, message)
        if last_ready != ready:
            state = "READY" if ready else "NOT READY"
            logger.info("readiness state: %s (%s)", state, message)
            last_ready = ready

    logger.info("shutting down")
    httpd.shutdown()
    httpd.server_close()
    server_thread.join(timeout=5)
    if conn is not None:
        conn.close()
    logger.info("shutdown complete")


if __name__ == "__main__":
    main()
