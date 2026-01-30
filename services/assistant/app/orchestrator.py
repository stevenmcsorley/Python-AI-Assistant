import logging
import os
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .signals import NullSignalSource, SignalSource, SignalWriter, SyntheticSignalSource

import psycopg


REQUIRED_TABLES = ("workflows", "tasks", "audit_log")


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        raise SystemExit(f"invalid integer for {name}: {value}")


def _check_db_ready(dsn: str) -> tuple[bool, str]:
    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
                cur.execute(
                    """
                    SELECT
                        to_regclass('public.workflows') IS NOT NULL,
                        to_regclass('public.tasks') IS NOT NULL,
                        to_regclass('public.audit_log') IS NOT NULL
                    """
                )
                exists = cur.fetchone()
        if not exists or not all(exists):
            return False, "required tables missing"
        return True, "ready"
    except Exception as exc:
        return False, f"db check failed: {exc}"


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
    dsn = os.getenv("DATABASE_URL", "")
    user_id = os.getenv("DEFAULT_USER_ID", "")
    use_synthetic = os.getenv("INGEST_SYNTHETIC_SIGNALS", "false").lower() == "true"
    if use_synthetic:
        if not user_id:
            raise SystemExit("DEFAULT_USER_ID is required when INGEST_SYNTHETIC_SIGNALS=true")
        signal_sources: list[SignalSource] = [SyntheticSignalSource(user_id=user_id)]
    else:
        signal_sources = [NullSignalSource()]

    def ingest_signals() -> tuple[int, int]:
        writer = SignalWriter(dsn, actor_id="orchestrator")
        ingested = 0
        total = 0
        for source in signal_sources:
            signals = source.fetch()
            total += len(signals)
            for signal in signals:
                _, created = writer.write(signal)
                if created:
                    ingested += 1
        return ingested, total

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

        def do_POST(self) -> None:  # noqa: N802 - stdlib signature
            if self.path != "/ingest":
                self.send_response(404)
                self.end_headers()
                return
            ready, msg = state.get()
            if not ready:
                self.send_response(503)
                self.end_headers()
                self.wfile.write(msg.encode("utf-8"))
                return
            ingested, total = ingest_signals()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(f\"ingested={ingested} total={total}\".encode(\"utf-8\"))

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
    logger = logging.getLogger("orchestrator")

    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL is required")

    listen_host = os.getenv("ORCHESTRATOR_HOST", "0.0.0.0")
    listen_port = _env_int("ORCHESTRATOR_PORT", 8000)
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

    last_ready = None
    logger.info("orchestrator started, readiness checks every %ss", readiness_interval)

    ready, message = _check_db_ready(dsn)
    readiness.set(ready, message)
    state = "READY" if ready else "NOT READY"
    logger.info("readiness state: %s (%s)", state, message)
    last_ready = ready

    while not stop_event.wait(readiness_interval):
        ready, message = _check_db_ready(dsn)
        readiness.set(ready, message)
        if last_ready != ready:
            state = "READY" if ready else "NOT READY"
            logger.info("readiness state: %s (%s)", state, message)
            last_ready = ready

    logger.info("shutting down")
    httpd.shutdown()
    httpd.server_close()
    server_thread.join(timeout=5)
    logger.info("shutdown complete")


if __name__ == "__main__":
    main()
