---
title: Runtime Architecture – Python AI Assistant (Executable)
created: 2026-01-30
updated: 2026-01-30
status: authoritative
source: "PRD – Python AI Assistant (Authoritative)"
---

# Runtime Architecture – Python AI Assistant (Executable)

This document translates the PRD into an implementable runtime architecture. It defines concrete processes, data flows, isolation boundaries, and failure recovery paths.

## 1. Process Model (Docker Compose Services)

### Core Services (always on)
- **assistant-orchestrator** (Python service, single instance)
  - Responsibilities: WhatsApp webhook ingress, command routing, background schedule tick, workflow initiation, approval gating, and status queries.
  - Does **not** execute tools directly.
- **assistant-worker** (Python service, N instances)
  - Responsibilities: execute queued tasks, call LLMs, run tools via sandbox runner, write artifacts, update workflow state.
- **postgres** (pgvector enabled)
  - Durable store for workflows, tasks, audit logs, approvals, artifacts metadata, and embeddings.
- **redis**
  - Working memory cache, rate limits, and fast queues for task dispatch.
- **obsidian-vault** (host-mounted volume)
  - Human-readable system of record for knowledge and artifacts.

### Optional Services (enabled via compose profiles)
- **temporal** (Temporal server + UI)
  - Durable workflow orchestration for long-running research flows.
- **monitoring** (Prometheus + Grafana)
  - Metrics and dashboards.
- **vector-db** (Qdrant/Weaviate) 
  - Only when pgvector does not meet scale needs.

### Process Boundaries (inside services)
- **Tool runner subprocess** (spawned by worker per tool execution)
  - No DB credentials, no direct Obsidian access, resource-limited, time-boxed.
- **Obsidian write queue** (single writer per vault)
  - Serialized write operations to prevent concurrent file corruption.

## 2. Background Job Execution Flow

### 2.1 Signal Collection (bounded schedule)
1. Orchestrator scheduler ticks on a bounded cadence (e.g., hourly/day).
2. Orchestrator enqueues `poll_email`, `poll_calendar`, `scan_obsidian` jobs into Redis queue `jobs:signals`.
3. Worker consumes jobs and retrieves new items from connectors.
4. Worker writes each signal to `signals` table and appends `audit_logs` entries.
5. Worker enqueues `intent_eval` tasks for new signals.

### 2.2 Intent Evaluation & Suggestion
1. Worker loads signal + recent context from Postgres and Redis.
2. Worker calls LLM (DeepSeek primary, fallback as configured).
3. Worker writes `suggestions` record with confidence, rationale, and source references.
4. Orchestrator delivers WhatsApp message with quick actions (Approve / Snooze / Dismiss).

### 2.3 User Approval → Action Workflow
1. User taps an approval action in WhatsApp.
2. Orchestrator records an `approval` row and creates a `workflow` with `type=apply_action`.
3. Worker executes workflow steps and writes outputs to Obsidian as draft or approved based on explicit user intent.

### 2.4 Research Workflow (search → fetch → synthesize → write)
1. Orchestrator creates a `workflow` with `type=research` and `status=pending`.
2. Worker claims workflow and writes `task` rows for each step.
3. Worker executes tasks with checkpoints between steps.
4. Final artifact written to Obsidian with `[Prepared]` or `[Draft]` label.

## 3. Workflow Persistence & Checkpoints

### Database-Backed (default, no Temporal)
- **Workflows table**: `id`, `type`, `status`, `current_step`, `checkpoint_json`, `updated_at`, `error_details`.
- **Tasks table**: `id`, `workflow_id`, `type`, `status`, `attempts`, `input_json`, `output_json`.
- **Checkpointing rule**: after every task completion, worker performs a single transaction:
  1) update `tasks.status` + `tasks.output_json`
  2) update `workflows.current_step` + `workflows.checkpoint_json`
  3) append `audit_logs` entry
- **Resume rule**: on startup, workers re-claim `workflows` with `status=running` and `updated_at` older than a lease timeout, then resume from `checkpoint_json`.

### Temporal-Backed (enabled via profile)
- Orchestrator starts a Temporal workflow with `workflow_id` and stores `temporal_run_id` in Postgres.
- Activities map to task types; each Activity writes task results to Postgres for auditability.
- Postgres remains the system of record for `audit_logs` and artifact metadata.
- Temporal is **not** used for:
  - WhatsApp inbound command handling
  - short, synchronous requests (< 1 minute)
  - simple memory lookups

## 4. Tool Execution Isolation Boundaries

### Minimum Isolation (Phase 0–1)
- Worker spawns tool subprocess with:
  - dedicated temp working directory
  - CPU/memory/time limits (ulimit or `resource` module)
  - no DB credentials in env
  - sanitized, validated inputs only
- Tool output returned via JSON on stdout; worker validates schema before use.
- No direct filesystem write outside temp directory; worker performs validated writes to Obsidian via write queue.

### Enhanced Isolation (Phase 2)
- High-risk tools run in Docker containers with:
  - read-only filesystem
  - restricted network namespace
  - fixed mount to temp working directory only

## 5. Data Flow Between Services

1. **WhatsApp inbound** → Orchestrator → `commands` table → Worker
2. **Email/Calendar/Obsidian signals** → Worker → `signals` table → `suggestions` table → Orchestrator → WhatsApp outbound
3. **Workflow tasks** → Worker → Tool runner → `artifacts` table + Obsidian vault
4. **Memory updates** → Worker → Postgres (episodic/semantic) + Redis (working)
5. **Audit logs** → Every component → `audit_logs` table (append-only)

## 6. Failure and Recovery Paths

- **Orchestrator crash**
  - Docker restarts process; scheduler replays pending cadence ticks.
  - No tasks lost (jobs in Redis, state in Postgres).

- **Worker crash mid-task**
  - Task lease expires; workflow is re-claimed by another worker.
  - Idempotency enforced by task `attempts` counter and checkpointing.

- **Tool subprocess failure**
  - Worker marks task failed; retries with backoff if retryable.
  - Failure recorded in `audit_logs` and `tasks.error_details`.

- **LLM provider outage**
  - Worker routes to fallback provider; if none available, task is queued with `status=paused`.

- **Postgres unavailable**
  - Orchestrator and workers enter read-only degraded mode; no state mutations.
  - Background jobs paused until DB returns.

- **Obsidian write conflict**
  - Obsidian write queue serializes writes; if file changed, create new version with incremented suffix and log discrepancy.

## 7. Temporal Usage vs Deferred

### Used (when enabled)
- Long-running research workflows (> 5 minutes)
- Multi-step synthesis pipelines (search → fetch → parse → synthesize → write)
- Any workflow requiring automatic retries and durable state across crashes

### Deferred / Not Used
- WhatsApp message handling and approvals
- Short, synchronous responses
- Simple memory lookups and cached queries
- Obsidian file writes (handled via single writer queue)

### Runtime Switch
- `WORKFLOW_ENGINE=temporal|db`
  - `temporal`: start workflows in Temporal, activities handle steps.
  - `db`: use Postgres-backed workflow runner with explicit checkpoints.

## 8. Concrete Implementation Notes (v1 defaults)

- **Queues**: Redis lists or streams: `jobs:signals`, `jobs:workflows`, `jobs:obsidian`.
- **Task states**: `pending → running → completed | failed | paused | cancelled`.
- **Artifact states**: `Prepared → Draft → Approved → Archived` (user-initiated transitions only).
- **Cadence**: signal polling runs hourly by default; daily plan at 06:00 local; weekly plan on Monday 07:00.

---
This architecture is implementable in the current Docker Compose stack and preserves the PRD’s safety, auditability, and long-running guarantees.
