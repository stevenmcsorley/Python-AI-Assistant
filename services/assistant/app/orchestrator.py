import json
import logging
import os
import signal
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .signals import NullSignalSource, SignalSource, SignalWriter, SyntheticSignalSource
from .intents import IntentWriter, RuleBasedIntentClassifier
from .suggestions import RuleBasedSuggestionGenerator, SuggestionWriter
from .approvals import Approval, ApprovalWriter
from .messages import Message, MessageWriter
from .messages.inbound import handle_inbound_text
from .workflows import WorkflowFactory, WorkflowStepPlanner, plan_pending_workflows
from .tasks import TaskPlanner, plan_pending_tasks

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


def _configure_logging(service: str, orchestrator_id: str) -> None:
    old_factory = logging.getLogRecordFactory()

    def record_factory(*args, **kwargs):  # type: ignore[override]
        record = old_factory(*args, **kwargs)
        if not hasattr(record, "service"):
            record.service = service
        if not hasattr(record, "orchestrator_id"):
            record.orchestrator_id = orchestrator_id
        if not hasattr(record, "entity_id"):
            record.entity_id = "-"
        return record

    logging.setLogRecordFactory(record_factory)
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s service=%(service)s orchestrator_id=%(orchestrator_id)s entity_id=%(entity_id)s message=%(message)s",
    )


def _validate_env() -> dict:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL is required")

    use_synthetic = os.getenv("INGEST_SYNTHETIC_SIGNALS", "false").lower() == "true"
    user_id = os.getenv("DEFAULT_USER_ID", "")
    if use_synthetic and not user_id:
        raise SystemExit("DEFAULT_USER_ID is required when INGEST_SYNTHETIC_SIGNALS=true")

    return {
        "database_url_set": True,
        "ingest_synthetic_signals": use_synthetic,
        "default_user_id_set": bool(user_id),
    }


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
                    message_writer = MessageWriter(dsn, actor_id="orchestrator", actor_type="orchestrator")
                    for signal, signal_id in new_signals:
                        intents = classifier.classify(signal, signal_id=signal_id)
                        intents_processed += len(intents)
                        for intent in intents:
                            intent_id, created = intent_writer.write(intent)
                            if created:
                                intents_created += 1
                            suggestion = suggestion_generator.generate(intent, intent_id, signal)
                            if suggestion is not None:
                                suggestion_id, suggestion_created = suggestion_writer.write(suggestion)
                                if suggestion_created:
                                    suggestions_created += 1
                                    message = Message(
                                        user_id=suggestion.user_id,
                                        channel="whatsapp",
                                        message_type="suggestion_ready",
                                        body="I found something you may want to review. Would you like me to proceed?",
                                        status="queued",
                                        related_entity_type="suggestion",
                                        related_entity_id=str(suggestion_id),
                                    )
                                    with psycopg.connect(dsn) as msg_conn:
                                        with msg_conn.transaction():
                                            with msg_conn.cursor() as msg_cur:
                                                message_id, _ = message_writer.write(message, cur=msg_cur)
                                                if message_id:
                                                    message_writer.render_message(message_id, cur=msg_cur)
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
                                planner = WorkflowStepPlanner(actor_id="orchestrator")
                                try:
                                    planner.ensure_steps(
                                        cur,
                                        workflow_id=workflow_id,
                                        workflow_type=str(row[4]),
                                        workflow_status="pending",
                                    )
                                except ValueError as exc:
                                    self.send_response(400)
                                    self.end_headers()
                                    self.wfile.write(str(exc).encode("utf-8"))
                                    return
                                task_planner = TaskPlanner(actor_id="orchestrator")
                                cur.execute(
                                    """
                                    SELECT step_id, step_key, status
                                    FROM workflow_steps
                                    WHERE workflow_id = %s
                                    """,
                                    (workflow_id,),
                                )
                                for step_id, step_key, step_status in cur.fetchall():
                                    try:
                                        task_planner.ensure_tasks(
                                            cur,
                                            step_id=str(step_id),
                                            workflow_id=workflow_id,
                                            step_key=str(step_key),
                                            step_status=str(step_status),
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
                                message_writer = MessageWriter(
                                    dsn, actor_id="orchestrator", actor_type="orchestrator"
                                )
                                message = Message(
                                    user_id=str(row[1]),
                                    channel="whatsapp",
                                    message_type="workflow_started",
                                    body="I've started preparing this for you. I'll update you when there's something to review.",
                                    status="queued",
                                    related_entity_type="workflow",
                                    related_entity_id=workflow_id,
                                )
                                message_id, _ = message_writer.write(message, cur=cur)
                                if message_id:
                                    message_writer.render_message(message_id, cur=cur)
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
            if self.path == "/whatsapp":
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
                user_id = payload.get("user_id")
                text = payload.get("text")
                if not isinstance(user_id, str) or not user_id:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"user_id is required")
                    return
                if not isinstance(text, str) or not text:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"text is required")
                    return
                status_code, response_text = handle_inbound_text(dsn, user_id, text)
                self.send_response(status_code)
                self.end_headers()
                self.wfile.write(response_text.encode("utf-8"))
                return

            self.send_response(404)
            self.end_headers()
            return

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler


def main() -> None:
    config = _validate_env()
    orchestrator_id = os.getenv("ORCHESTRATOR_ID") or str(uuid.uuid4())
    _configure_logging("orchestrator", orchestrator_id)
    logger = logging.getLogger("orchestrator")

    dsn = os.getenv("DATABASE_URL") or ""
    logger.info(
        "config validated: ingest_synthetic_signals=%s default_user_id_set=%s",
        config["ingest_synthetic_signals"],
        config["default_user_id_set"],
    )

    listen_host = os.getenv("ORCHESTRATOR_HOST", "0.0.0.0")
    listen_port = _env_int("ORCHESTRATOR_PORT", 8000)
    readiness_interval = _env_int("READINESS_CHECK_SECONDS", 10)

    stop_event = threading.Event()
    readiness = _ReadinessState()
    httpd_ref: dict[str, ThreadingHTTPServer | None] = {"server": None}

    def handle_signal(signum: int, _frame: object) -> None:
        logger.info("shutdown signal received: %s", signum)
        readiness.set(False, "shutdown")
        if httpd_ref["server"] is not None:
            httpd_ref["server"].shutdown()
        stop_event.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    handler_cls = _make_handler(readiness)
    httpd = ThreadingHTTPServer((listen_host, listen_port), handler_cls)
    httpd_ref["server"] = httpd
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()

    last_ready = None
    ready_logged = False
    logger.info("orchestrator started, readiness checks every %ss", readiness_interval)

    ready, message = _check_db_ready(dsn)
    readiness.set(ready, message)
    state = "READY" if ready else "NOT READY"
    logger.info("readiness state: %s (%s)", state, message)
    last_ready = ready
    if ready and not ready_logged:
        logger.info("ready")
        ready_logged = True
    if ready:
        planned, steps_created = plan_pending_workflows(dsn, actor_id="orchestrator")
        if planned:
            logger.info(
                "workflow step planning: workflows_planned=%s steps_created=%s",
                planned,
                steps_created,
            )
        task_planned, tasks_created = plan_pending_tasks(dsn, actor_id="orchestrator")
        if task_planned:
            logger.info(
                "task materialization: steps_planned=%s tasks_created=%s",
                task_planned,
                tasks_created,
            )

    while not stop_event.wait(readiness_interval):
        ready, message = _check_db_ready(dsn)
        readiness.set(ready, message)
        if last_ready != ready:
            state = "READY" if ready else "NOT READY"
            logger.info("readiness state: %s (%s)", state, message)
            last_ready = ready
        if ready and not ready_logged:
            logger.info("ready")
            ready_logged = True

    logger.info("shutting down")
    httpd.shutdown()
    httpd.server_close()
    server_thread.join(timeout=5)
    logger.info("shutdown complete")


if __name__ == "__main__":
    main()
