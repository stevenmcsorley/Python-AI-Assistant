---
title: Healthchecks & Readiness – Python AI Assistant
created: 2026-01-30
updated: 2026-01-30
status: authoritative
source:
  - "Runtime Architecture – Python AI Assistant (Executable)"
  - "PostgreSQL Schema – Python AI Assistant (v1)"
  - "Task Queue & Worker Lifecycle – Python AI Assistant"
---

# Healthchecks & Readiness – Python AI Assistant

This document defines liveness and readiness semantics for all services and how they map to Docker Compose healthchecks. It is immediately implementable in Docker Compose.

## 1) Service‑Level Healthchecks

### Orchestrator
- **Liveness:** Process is running and event loop is responsive.
- **Readiness:**
  - PostgreSQL reachable and schema initialized (core tables exist).
  - Redis reachable (PING succeeds).
  - Required runtime config loaded (LLM provider selection, WhatsApp config if enabled).
  - If `WORKFLOW_ENGINE=temporal`, Temporal endpoint reachable.
- **Fail healthcheck if:**
  - Cannot reach PostgreSQL or schema missing.
  - Redis unreachable.
  - Required config missing.
  - Temporal enabled but not reachable.

### Worker
- **Liveness:** Process is running and task loop is responsive.
- **Readiness:**
  - PostgreSQL reachable and schema initialized.
  - Redis reachable (if used for queue notification).
  - Can perform a lightweight DB write (e.g., audit heartbeat) and commit.
  - Tool sandbox runtime available (can spawn a test subprocess).
  - If `WORKFLOW_ENGINE=temporal`, Temporal endpoint reachable.
- **Fail healthcheck if:**
  - PostgreSQL unreachable or write fails.
  - Redis unreachable (when configured).
  - Sandbox spawn fails.
  - Temporal enabled but not reachable.

### PostgreSQL
- **Liveness:** Database process is running.
- **Readiness:**
  - Accepting connections.
  - Required extensions available (`pgcrypto`, `vector`).
  - Core schema tables exist.
- **Fail healthcheck if:**
  - Not accepting connections.
  - Extensions missing.
  - Required tables absent.

### Redis
- **Liveness:** Redis process is running.
- **Readiness:**
  - Responds to PING.
- **Fail healthcheck if:**
  - PING fails or connection times out.

## 2) Readiness vs Liveness

- **Alive:** The process is running and its main loop is responsive.
- **Ready:** The process can safely perform its primary responsibilities without corrupting state or losing work.

Implications:
- A service can be alive but not ready (e.g., DB down). In this case it MUST refuse work.
- Readiness must gate work submission and task claiming.

## 3) Failure Signaling

- Healthcheck failures are reported through Docker Compose health status (healthy/unhealthy).
- Services log a structured error entry for each failed healthcheck cycle with the failing condition.
- Orchestrator and workers must set internal “not ready” state when any readiness condition fails.

Conditions that must fail healthchecks:
- DB unreachable or schema missing.
- Redis unreachable (if configured).
- Temporal enabled but unreachable.
- Worker cannot create a sandboxed subprocess.
- Any failure to perform a small DB write (worker readiness only).

## 4) Docker Compose Mapping

Use Docker Compose `healthcheck` definitions with the following defaults:
- **Interval:** 10s
- **Timeout:** 3s
- **Retries:** 5
- **Start period:** 20s (PostgreSQL), 10s (Redis), 30s (orchestrator/worker)

Mapping guidance:
- **PostgreSQL:** healthcheck uses the native readiness probe (pg_isready) plus a lightweight check for required extensions and tables.
- **Redis:** healthcheck uses PING.
- **Orchestrator/Worker:** healthcheck calls a local readiness endpoint or a local readiness script that verifies DB/Redis/Temporal (if enabled) and tool sandbox spawn.

## 5) Safety Guarantees

- **Workers must not claim tasks unless ready.** Readiness failure forces worker into idle mode (no task claiming, no lease renewals).
- **Orchestrator must not schedule jobs unless DB is healthy.** When not ready, it only accepts inbound commands that are queued but not executed.
- **Any loss of readiness triggers safe pause:**
  - Workers mark running tasks as `paused` if possible.
  - Orchestrator stops emitting new suggestions and scheduling background jobs.

---
These semantics ensure that task claiming and scheduling only happen when core dependencies are healthy, preserving auditability and resumability guarantees.
