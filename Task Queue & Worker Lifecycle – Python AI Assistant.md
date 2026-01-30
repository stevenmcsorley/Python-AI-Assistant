---
title: Task Queue & Worker Lifecycle – Python AI Assistant
created: 2026-01-30
updated: 2026-01-30
status: authoritative
source:
  - "PRD – Python AI Assistant (Authoritative)"
  - "Runtime Architecture – Python AI Assistant (Executable)"
  - "PostgreSQL Schema – Python AI Assistant (v1)"
---

# Task Queue & Worker Lifecycle – Python AI Assistant

This document defines the concrete task queue contract and worker lifecycle. It is directly implementable against the current PostgreSQL schema.

## 1) Task Claiming Protocol

### Lease Model
- **Authoritative state lives in PostgreSQL.** Redis (if used) is advisory only.
- A worker claims a task by acquiring a **lease** on the `tasks` row:
  - `lease_owner = <worker_id>`
  - `lease_expires_at = now() + lease_duration`
  - `status = running`
  - `started_at = now()` when first attempt starts
- A task is claimable if:
  - `status IN ('pending','scheduled')` **or** `status = 'running'` with an expired lease, and
  - `lease_expires_at IS NULL OR lease_expires_at < now()`

### Lease Duration and Renewal
- **Default lease duration:** 120 seconds.
- **Renewal interval:** every 30 seconds while the task is running.
- Renewal updates only `lease_expires_at` and appends an `audit_log` entry with action `task_lease_renewed`.

### Abandoned Lease Reclaim
- A task is **abandoned** when `lease_expires_at < now()`.
- Any worker may reclaim it by acquiring a new lease and incrementing the attempt count.
- Reclaiming must append an `audit_log` entry with action `task_reclaimed`.

## 2) Execution Lifecycle

### Task State Transitions
- `pending → running → completed`
- `pending → running → failed`
- `pending → running → paused` (manual pause or safe shutdown)
- `running → paused` (graceful shutdown)
- `running → failed` (non‑retryable error or max attempts exceeded)
- `failed → pending` **only** by explicit user‑initiated resume

### Attempt Tracking
- On each claim, worker creates a `task_attempts` row:
  - `attempt_number = tasks.attempts + 1`
  - `status = running`
  - `started_at = now()`
- On completion or failure, worker updates the attempt row with `ended_at` and `status`.
- Worker increments `tasks.attempts` in the same transaction that sets task status.

### Idempotency Guarantees
- `tasks.idempotency_key` is unique per workflow.
- Workers MUST ensure that repeated execution of the same task is safe.
- If a task has a prior `completed` state with the same `idempotency_key`, the worker MUST return the stored output without re‑execution.

## 3) Retry & Backoff Policy

### Max Attempts
- Default `tasks.max_attempts = 3`.
- Each retry increments `tasks.attempts` and creates a new `task_attempts` row.

### Backoff Strategy
- **Exponential backoff with jitter** after failure:
  - Base delay: 10 seconds
  - Delay = `min(300s, base * 2^(attempt-1))` + random(0–5s)
- Worker sets `tasks.status = scheduled` and **delays next run** by setting `lease_expires_at = now() + delay`.

### Failure Escalation
- When `attempts >= max_attempts`, set:
  - `tasks.status = failed`
  - `workflow_steps.status = failed`
  - `workflows.status = failed`
- Append `audit_log` entries for all transitions.
- Workflow can be resumed only via explicit user action that resets task state.

## 4) Worker Responsibilities

### On Startup
- Generate a unique `worker_id`.
- Load configuration (DB, Redis, LLM providers).
- **Recovery sweep:**
  - Reclaim abandoned tasks (expired leases).
  - Resume `workflows` in `running` state whose current step’s lease expired.
- Begin polling/consuming queue notifications.

### Heartbeat / Liveness
- While executing a task, renew lease every 30 seconds.
- Write `audit_log` entry on each lease renewal.
- If the worker cannot renew due to DB errors, it MUST stop starting new tasks and attempt graceful shutdown.

### Graceful Shutdown
- Stop claiming new tasks immediately.
- For each running task:
  - Attempt to persist partial state into `workflow_checkpoints` (if applicable).
  - Set `tasks.status = paused`.
  - Clear `lease_owner` and `lease_expires_at`.
  - Update `task_attempts` with `status = failed` and reason `worker_shutdown`.
- Append `audit_log` entries for each state change.

## 5) Crash & Recovery Behavior

### Worker Crash Mid‑Task
- Lease expires.
- Another worker reclaims the task and increments attempt count.
- Task is rerun using idempotency guarantees.

### Orchestrator Crash
- No tasks are lost because task state is in PostgreSQL.
- Background scheduling resumes on restart; missed schedule ticks are recomputed based on `jobs.next_run_at`.

### Database Restart / Unavailability
- Workers must not start new tasks without DB connectivity.
- If DB becomes unavailable mid‑task:
  - Worker stops tool execution if possible.
  - Task is left in `running` until lease expiry; it will be reclaimed once DB returns.
- After DB recovery, workers reclaim abandoned tasks using lease protocol.

## 6) Interaction with Workflows

### Task → Step Advancement
- A workflow step is completed only when **all tasks** linked to that `step_id` are `completed`.
- When the final task in a step completes, worker:
  - sets `workflow_steps.status = completed`
  - updates `workflows.current_step_id` to the next step
  - writes a `workflow_checkpoints` entry
  - appends `audit_log` entries for each change

### Checkpoint Timing
- A checkpoint is written at:
  - end of every workflow step
  - before any transition to the next step
- Checkpoints contain serialized step outputs and are linked via `workflows.checkpoint_id`.

## 7) Safety Constraints

### Workers MUST NEVER
- Execute tools directly in the main process.
- Modify external systems (calendar, email, documents) without a recorded `approvals` entry linked to the workflow.
- Write directly to the Obsidian vault outside the controlled writer flow.
- Skip audit logging for any state transition or tool execution.

### Tool Isolation Enforcement
- Each tool execution runs in an isolated subprocess with:
  - no DB credentials in environment
  - restricted filesystem access to a temp workspace
  - CPU/memory/time limits
- Tool output is validated before use.
- Worker writes tool outputs to storage only after validation and audit logging.

---
This contract is the single source of truth for how tasks are claimed, executed, retried, and recovered.
