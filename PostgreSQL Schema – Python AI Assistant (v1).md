---
title: PostgreSQL Schema – Python AI Assistant (v1)
created: 2026-01-30
updated: 2026-01-30
status: authoritative
source:
  - "PRD – Python AI Assistant (Authoritative)"
  - "Runtime Architecture – Python AI Assistant (Executable)"
  - "Initial Data Model – Python AI Assistant"
---

# PostgreSQL Schema – Python AI Assistant (v1)

This document defines the physical PostgreSQL schema for the Python AI Assistant v1 runtime. It is designed for resumable workflows, strict auditability, and Obsidian‑first knowledge storage. All tables include `created_at` and `updated_at` timestamps unless otherwise noted.

## 1. Core Entities

### users
- **Purpose:** Ownership boundary (single user today, supports expansion).
- **Primary key:** `user_id`
- **Key fields:** `display_name`, `timezone`, `status`

### workflows
- **Purpose:** Durable, resumable processes.
- **Primary key:** `workflow_id`
- **Key fields:** `user_id`, `type` (enum `workflow_type`), `status`, `priority`, `current_step_id`, `checkpoint_id`, `lease_owner`, `lease_expires_at`, `started_at`, `completed_at`, `error_details`
- **Relationships:** `workflows` 1→N `workflow_steps`, `tasks`, `artifacts`, `audit_log`.

### workflow_steps
- **Purpose:** Idempotent logical steps within a workflow.
- **Primary key:** `step_id`
- **Key fields:** `workflow_id`, `step_key`, `step_index`, `status`, `idempotency_key`, `input_json`, `output_json`, `attempts`, `max_attempts`, `lease_owner`, `lease_expires_at`, `started_at`, `completed_at`, `error_details`
- **Constraints:** unique `(workflow_id, step_key)` and `(workflow_id, step_index)`.

### tasks
- **Purpose:** Executable units (jobs) linked to steps.
- **Primary key:** `task_id`
- **Key fields:** `workflow_id`, `step_id`, `task_type`, `status`, `idempotency_key`, `input_json`, `output_json`, `attempts`, `max_attempts`, `lease_owner`, `lease_expires_at`, `started_at`, `completed_at`, `error_details`
- **Relationships:** `tasks` 1→N `task_attempts`, `tool_executions`, `audit_log`.

### task_attempts (immutable)
- **Purpose:** Track retries and outcomes.
- **Primary key:** `task_attempt_id`
- **Key fields:** `task_id`, `attempt_number`, `status`, `started_at`, `ended_at`, `worker_id`, `error_details`

### jobs
- **Purpose:** Scheduled background jobs (polling, periodic plans).
- **Primary key:** `job_id`
- **Key fields:** `user_id`, `job_type`, `status`, `schedule_type`, `schedule_value`, `next_run_at`, `last_run_at`, `payload_json`, `lease_owner`, `lease_expires_at`

## 2. Signals, Intents, Suggestions, Approvals

### signals
- **Purpose:** Raw detected events from email/calendar/Obsidian.
- **Primary key:** `signal_id`
- **Key fields:** `user_id`, `source_type`, `source_ref`, `received_at`, `summary`, `raw_json`, `status`

### intents
- **Purpose:** Classified interpretation of signals.
- **Primary key:** `intent_id`
- **Key fields:** `user_id`, `signal_id`, `intent_type`, `confidence`, `rationale`, `status`

### suggestions
- **Purpose:** User‑facing recommendations (WhatsApp).
- **Primary key:** `suggestion_id`
- **Key fields:** `user_id`, `signal_id`, `intent_id`, `type`, `confidence`, `rationale`, `status`

### approvals (immutable)
- **Purpose:** Explicit user decisions.
- **Primary key:** `approval_id`
- **Key fields:** `user_id`, `suggestion_id`, `intent_id`, `workflow_id`, `decision`, `channel`, `reason`, `decided_at`

## 3. Artifacts & Obsidian Outputs

### artifacts
- **Purpose:** Logical artifact containers (plan, research, prep brief).
- **Primary key:** `artifact_id`
- **Key fields:** `user_id`, `workflow_id`, `type`, `title`, `status`, `current_version_id`

### artifact_versions (immutable)
- **Purpose:** Immutable versions of artifact outputs.
- **Primary key:** `artifact_version_id`
- **Key fields:** `artifact_id`, `version_number`, `state`, `obsidian_path`, `content_ref`, `content_hash`, `frontmatter_hash`, `model_provider`, `model_name`, `model_version`, `confidence`, `created_by`, `workflow_id`, `task_id`

### sources (immutable)
- **Purpose:** Source references used by artifacts.
- **Primary key:** `source_id`
- **Key fields:** `source_type`, `source_ref`, `retrieved_at`, `content_hash`, `snapshot_ref`, `metadata`

### artifact_sources (immutable)
- **Purpose:** Many‑to‑many link between artifacts and sources.
- **Primary key:** composite `(artifact_version_id, source_id)`

## 4. Memory & Embeddings

### memory_items (immutable content; status transitions allowed)
- **Purpose:** Episodic and semantic memory entries with provenance.
- **Primary key:** `memory_id`
- **Key fields:** `user_id`, `memory_type`, `source_id`, `artifact_version_id`, `content_ref`, `summary`, `confidence`, `status`, `supersedes_memory_id`

### memory_embeddings (immutable)
- **Purpose:** Semantic index for retrieval.
- **Primary key:** `embedding_id`
- **Key fields:** `memory_id`, `artifact_version_id`, `model_name`, `dims`, `embedding`, `chunk_index`, `chunk_hash`

## 5. Audit & Tool Execution

### audit_log (immutable)
- **Purpose:** Full, append‑only audit trail.
- **Primary key:** `audit_id`
- **Key fields:** `timestamp`, `actor_type`, `actor_id`, `action_type`, `entity_type`, `entity_id`, `workflow_id`, `step_id`, `task_id`, `job_id`, `tool_exec_id`, `input_ref`, `output_ref`, `reasoning_ref`, `before_hash`, `after_hash`, `prev_audit_hash`, `audit_hash`, `metadata`
- **Immutability:** enforced at DB level.

### tool_executions (immutable)
- **Purpose:** Tool call traceability.
- **Primary key:** `tool_exec_id`
- **Key fields:** `task_id`, `tool_name`, `sandbox_type`, `status`, `input_ref`, `output_ref`, `started_at`, `ended_at`, `exit_code`, `resource_usage`

## 6. Immutability & Mutability Rules

### Immutable (append‑only)
- `workflow_checkpoints`
- `task_attempts`
- `tool_executions`
- `artifact_versions`
- `sources`
- `artifact_sources`
- `memory_embeddings`
- `approvals`
- `audit_log`

### Mutable subset for `memory_items`
- `memory_items.status`
- `memory_items.supersedes_memory_id`

### Mutable
- `workflows`, `workflow_steps`, `tasks`, `jobs`
- `signals`, `intents`, `suggestions`
- `artifacts` (pointer to latest version)

## 7. Indexing Strategy (v1)

Resumable workflow execution
- `workflows(status, lease_expires_at)`
- `workflow_steps(status, lease_expires_at)`
- `tasks(status, lease_expires_at)`
- `jobs(status, next_run_at)`

Recent activity / status
- `workflows(updated_at DESC)`
- `tasks(updated_at DESC)`
- `signals(received_at DESC)`
- `suggestions(created_at DESC)`

End‑to‑end traceability
- `audit_log(workflow_id, timestamp DESC)`
- `audit_log(task_id, timestamp DESC)`
- `audit_log(entity_type, entity_id)`
- `tool_executions(task_id, started_at DESC)`

---
This schema is designed to be implemented immediately using PostgreSQL 15+ with pgvector enabled.
