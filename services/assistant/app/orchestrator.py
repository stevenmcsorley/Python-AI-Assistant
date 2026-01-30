import json
import logging
import os
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .signals import NullSignalSource, SignalSource, SignalWriter, SyntheticSignalSource
from .intents import IntentWriter, RuleBasedIntentClassifier
from .suggestions import RuleBasedSuggestionGenerator, SuggestionWriter
from .approvals import Approval, ApprovalWriter
from .workflows import WorkflowFactory

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

    def ingest_signals() -> tuple[int, int, list[tuple[object, str]]]:
        writer = SignalWriter(dsn, actor_id="orchestrator")
        ingested = 0
        total = 0
        new_signals: list[tuple[object, str]] = []
        for source in signal_sources:
            signals = source.fetch()
            total += len(signals)
            for signal in signals:
                signal_id, created = writer.write(signal)
                if created:
                    ingested += 1
                    new_signals.append((signal, signal_id))
        return ingested, total, new_signals

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
            if self.path == "/ingest":
                ready, msg = state.get()
                if not ready:
                    self.send_response(503)
                    self.end_headers()
                    self.wfile.write(msg.encode("utf-8"))
                    return
                ingested, total, new_signals = ingest_signals()
                intents_created = 0
                intents_processed = 0
                suggestions_created = 0
                if new_signals:
                    classifier = RuleBasedIntentClassifier()
                    intent_writer = IntentWriter(dsn, actor_id="orchestrator")
                    suggestion_generator = RuleBasedSuggestionGenerator()
                    suggestion_writer = SuggestionWriter(dsn, actor_id="orchestrator")
                    for signal, signal_id in new_signals:
                        intents = classifier.classify(signal, signal_id=signal_id)
                        intents_processed += len(intents)
                        for intent in intents:
                            intent_id, created = intent_writer.write(intent)
                            if created:
                                intents_created += 1
                            suggestion = suggestion_generator.generate(intent, intent_id, signal)
                            if suggestion is not None:
                                _, suggestion_created = suggestion_writer.write(suggestion)
                                if suggestion_created:
                                    suggestions_created += 1
                self.send_response(200)
                self.end_headers()
                logger = logging.getLogger("orchestrator")
                logger.info(
                    "ingest complete: signals_total=%s signals_ingested=%s intents_processed=%s intents_created=%s suggestions_created=%s",
                    total,
                    ingested,
                    intents_processed,
                    intents_created,
                    suggestions_created,
                )
                self.wfile.write(
                    f"ingested={ingested} total={total} intents_created={intents_created} suggestions_created={suggestions_created}".encode(
                        "utf-8"
                    )
                )
                return

            if self.path == "/approve":
                ready, msg = state.get()
                if not ready:
                    self.send_response(503)
                    self.end_headers()
                    self.wfile.write(msg.encode("utf-8"))
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = 0
                raw_body = self.rfile.read(length) if length > 0 else b""
                try:
                    payload = json.loads(raw_body.decode("utf-8") or "{}")
                except json.JSONDecodeError:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"invalid json")
                    return
                suggestion_id = payload.get("suggestion_id")
                decision = payload.get("decision")
                reason = payload.get("reason")
                if not suggestion_id:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"suggestion_id is required")
                    return
                if not isinstance(decision, str):
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"decision is required")
                    return
                decision = decision.lower().strip()
                if decision not in ("approved", "denied"):
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"decision must be 'approved' or 'denied'")
                    return
                if reason is not None and not isinstance(reason, str):
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"reason must be a string")
                    return

                approval_id = None
                new_status = "accepted" if decision == "approved" else "dismissed"
                with psycopg.connect(dsn) as conn:
                    with conn.transaction():
                        with conn.cursor() as cur:
                            cur.execute(
                                """
                                SELECT suggestion_id, user_id, intent_id, status, type
                                FROM suggestions
                                WHERE suggestion_id = %s
                                """,
                                (suggestion_id,),
                            )
                            row = cur.fetchone()
                            if not row:
                                self.send_response(404)
                                self.end_headers()
                                self.wfile.write(b"suggestion not found")
                                return
                            current_status = row[3]
                            if current_status != "queued":
                                self.send_response(409)
                                self.end_headers()
                                self.wfile.write(
                                    f"suggestion status is '{current_status}', expected 'queued'".encode("utf-8")
                                )
                                return
                            suggestion_type = row[4]
                            workflow_id = None
                            if decision == "approved":
                                factory = WorkflowFactory(actor_id="orchestrator")
                                try:
                                    workflow_id = factory.create_pending(
                                        cur, user_id=str(row[1]), suggestion_type=str(suggestion_type)
                                    )
                                except ValueError as exc:
                                    self.send_response(400)
                                    self.end_headers()
                                    self.wfile.write(str(exc).encode("utf-8"))
                                    return
                            approval = Approval(
                                user_id=str(row[1]),
                                suggestion_id=str(row[0]),
                                intent_id=str(row[2]) if row[2] else None,
                                workflow_id=workflow_id,
                                decision=decision,
                                channel="http",
                                reason=reason,
                            )
                            approval_writer = ApprovalWriter(dsn, actor_id="orchestrator")
                            approval_id = approval_writer.write(approval, cur=cur)
                            if workflow_id is not None:
                                factory.audit_workflow_created(
                                    cur,
                                    workflow_id=workflow_id,
                                    approval_id=approval_id,
                                    suggestion_id=str(row[0]),
                                    suggestion_type=str(suggestion_type),
                                )
                            cur.execute(
                                """
                                UPDATE suggestions
                                SET status = %s, updated_at = now()
                                WHERE suggestion_id = %s
                                """,
                                (new_status, suggestion_id),
                            )

                logger = logging.getLogger("orchestrator")
                workflows_created = 1 if workflow_id is not None else 0
                logger.info(
                    "approval recorded: approvals=1 suggestions_updated=1 workflows_created=%s suggestion_id=%s decision=%s approval_id=%s",
                    workflows_created,
                    suggestion_id,
                    decision,
                    approval_id,
                )
                self.send_response(200)
                self.end_headers()
                response_parts = [
                    f"approval_id={approval_id}",
                    f"suggestion_status={new_status}",
                ]
                if workflow_id is not None:
                    response_parts.append(f"workflow_id={workflow_id}")
                self.wfile.write(" ".join(response_parts).encode("utf-8"))
                return

            self.send_response(404)
            self.end_headers()
            return

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
