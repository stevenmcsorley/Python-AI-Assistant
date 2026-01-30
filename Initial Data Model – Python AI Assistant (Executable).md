---
title: Initial Data Model – Python AI Assistant (Executable)
created: 2026-01-30
updated: 2026-01-30
status: authoritative
source: "PRD – Python AI Assistant (Authoritative)"
---

# Initial Data Model – Python AI Assistant (Executable)

This data model is concrete and implementation-ready. It supports resumable workflows, strict auditability, immutable knowledge history, and Obsidian as the system of record.

## 1. Core Entities (Tables)

### Users
- **Purpose:** Single-user system today; supports future expansion.
- **Primary key:** `user_id`
- **Key fields:** `display_name`, `timezone`, `created_at`, `status`
- **Relationships:** owner of all other entities.

### Workflows
- **Purpose:** Durable, resumable multi-step processes (e.g., research, planning, apply_action).
- **Primary key:** `workflow_id`
- **Key fields:** `user_id`, `type`, `status`, `priority`, `current_step`, `checkpoint_ref`, `started_at`, `updated_at`, `completed_at`, `lease_owner`, `lease_expires_at`, `error_details`
- **Relationships:** has many `tasks`, `audit_logs`, `artifacts`, `approvals`.

### Workflow Checkpoints
- **Purpose:** Explicit, versioned checkpoints for resuming.
- **Primary key:** `checkpoint_id`
- **Key fields:** `workflow_id`, `step_name`, `state_json`, `created_at`, `created_by` (worker id)
- **Relationships:** many checkpoints per workflow; latest referenced by `workflows.checkpoint_ref`.
- **Immutability:** append-only.

### Tasks
- **Purpose:** Executable units within a workflow (search, fetch, synthesize, write).
- **Primary key:** `task_id`
- **Key fields:** `workflow_id`, `type`, `status`, `input_ref`, `output_ref`, `attempts`, `max_attempts`, `started_at`, `updated_at`, `completed_at`, `lease_owner`, `lease_expires_at`, `error_details`
- **Relationships:** belongs to `workflow`; has many `task_attempts`, `tool_executions`, `audit_logs`.

### Task Attempts
- **Purpose:** Immutable history of retries and outcomes.
- **Primary key:** `task_attempt_id`
- **Key fields:** `task_id`, `attempt_number`, `status`, `started_at`, `ended_at`, `error_details`, `worker_id`
- **Immutability:** append-only.

### Signals
- **Purpose:** Raw detected items from email/calendar/Obsidian scans.
- **Primary key:** `signal_id`
- **Key fields:** `user_id`, `source_type` (email/calendar/obsidian), `source_ref`, `received_at`, `summary`, `raw_ref`, `status`
- **Relationships:** generates `suggestions`, linked in `audit_logs`.
- **Immutability:** append-only; status can change.

### Suggestions
- **Purpose:** Proposed actions or drafts to present to user.
- **Primary key:** `suggestion_id`
- **Key fields:** `user_id`, `signal_id`, `type`, `confidence`, `rationale`, `proposed_actions_ref`, `status` (queued/sent/accepted/dismissed/snoozed), `created_at`, `updated_at`
- **Relationships:** may create `approvals` and `workflows`.

### Approvals
- **Purpose:** Explicit user consent records.
- **Primary key:** `approval_id`
- **Key fields:** `user_id`, `suggestion_id`, `workflow_id`, `action_type`, `status` (approved/denied/revoked), `decision_at`, `channel` (whatsapp), `reason`
- **Immutability:** append-only (denials/revocations are new records).

### Commands
- **Purpose:** Inbound user instructions from WhatsApp.
- **Primary key:** `command_id`
- **Key fields:** `user_id`, `channel_message_id`, `received_at`, `text`, `parsed_intent`, `status`, `workflow_id`
- **Immutability:** append-only; status can change.

### Artifacts
- **Purpose:** Logical grouping for a document output (plan, research summary, prep brief).
- **Primary key:** `artifact_id`
- **Key fields:** `user_id`, `type`, `title`, `status` (Prepared/Draft/Approved/Archived), `current_version_id`, `created_at`, `updated_at`, `workflow_id`
- **Relationships:** has many `artifact_versions`.

### Artifact Versions
- **Purpose:** Immutable versions of artifact content.
- **Primary key:** `artifact_version_id`
- **Key fields:** `artifact_id`, `version_number`, `state` (Prepared/Draft/Approved/Archived), `content_ref`, `obsidian_path`, `source_refs`, `model_info`, `confidence`, `created_at`, `created_by` (worker)
- **Immutability:** append-only.

### Obsidian Notes (Index)
- **Purpose:** Index of Obsidian files created/managed by the system.
- **Primary key:** `note_id`
- **Key fields:** `artifact_version_id`, `obsidian_path`, `title`, `frontmatter_hash`, `created_at`, `updated_at`
- **Immutability:** append-only; updates create new artifact version and a new note record or update with version bump depending on file strategy.

### Tool Executions
- **Purpose:** Record each tool call (inputs, outputs, timing, resource usage).
- **Primary key:** `tool_exec_id`
- **Key fields:** `task_id`, `tool_name`, `sandbox_type`, `input_ref`, `output_ref`, `started_at`, `ended_at`, `exit_code`, `resource_usage`, `status`
- **Immutability:** append-only.

### Sources
- **Purpose:** Source documents or URLs referenced by outputs.
- **Primary key:** `source_id`
- **Key fields:** `source_type` (url/email/calendar/note), `source_ref`, `retrieved_at`, `content_hash`, `snapshot_ref`, `license_info`
- **Immutability:** append-only.

### Audit Logs
- **Purpose:** Full, append-only audit trail for every action.
- **Primary key:** `audit_id`
- **Key fields:** `timestamp`, `actor_type` (user/system/worker), `actor_id`, `action_type`, `entity_type`, `entity_id`, `workflow_id`, `task_id`, `tool_exec_id`, `before_hash`, `after_hash`, `input_ref`, `output_ref`, `reasoning_ref`, `prev_audit_hash`, `audit_hash`
- **Immutability:** append-only, hash-chained.

### Memory Items
- **Purpose:** Persistent knowledge entries with provenance.
- **Primary key:** `memory_id`
- **Key fields:** `user_id`, `memory_type` (episodic/semantic), `source_ref`, `content_ref`, `confidence`, `created_at`, `status`
- **Immutability:** append-only; status can change (e.g., deprecated).

### Embeddings / Memory Index
- **Purpose:** Semantic lookup and RAG retrieval.
- **Primary key:** `embedding_id`
- **Key fields:** `memory_id`, `artifact_version_id`, `model_name`, `vector_ref`, `created_at`, `chunk_index`, `chunk_hash`
- **Relationships:** links memory to artifacts and sources.
- **Immutability:** append-only (new embeddings for new versions).

### Working Memory (Redis)
- **Purpose:** Short-lived session context and caches.
- **Key fields (by key):** `session_id`, `context_blob`, `ttl`, `rate_limit_counters`.
- **Immutability:** ephemeral; not persisted.

## 2. Primary Relationships (Explicit)

- `users` 1→N `workflows`, `signals`, `suggestions`, `approvals`, `commands`, `artifacts`, `memory_items`.
- `workflows` 1→N `tasks` → 1→N `task_attempts` and `tool_executions`.
- `workflows` 1→N `workflow_checkpoints` (latest referenced in workflow row).
- `signals` 1→N `suggestions`.
- `suggestions` 1→N `approvals`.
- `artifacts` 1→N `artifact_versions`.
- `artifact_versions` 1→1 `obsidian_notes` index (or N→1 if multiple notes per version).
- `artifact_versions` N→N `sources` (via `source_refs` mapping).
- `memory_items` 1→N `embeddings`.
- `audit_logs` references any entity by (`entity_type`, `entity_id`) and optionally links to `workflow_id`, `task_id`, `tool_exec_id`.

## 3. Immutable vs Mutable Data

### Immutable (append-only)
- `audit_logs`
- `workflow_checkpoints`
- `task_attempts`
- `tool_executions`
- `artifact_versions`
- `sources`
- `memory_items` (content never changes; status can be deprecated)
- `embeddings`
- `approvals` (new rows for changes)
- `commands` (content immutable; status mutable)

### Mutable (stateful)
- `workflows` (status, current_step, lease, checkpoint_ref)
- `tasks` (status, lease, attempts count)
- `signals` (status)
- `suggestions` (status)
- `artifacts` (current_version_id, status)
- `obsidian_notes` index (updated when file path changes, otherwise append-only)

## 4. Audit Log Structure (Required Fields)

Each audit entry must include:
- `timestamp` (microsecond precision)
- `actor_type`, `actor_id`
- `action_type` (e.g., workflow_start, task_complete, tool_exec, artifact_write)
- `entity_type`, `entity_id`
- `workflow_id` and `task_id` when applicable
- `input_ref` and `output_ref` (pointers to stored payloads)
- `reasoning_ref` (LLM prompt + rationale snapshot)
- `before_hash` and `after_hash` for mutated entities
- `prev_audit_hash` and `audit_hash` for chain integrity

Audit logs are queryable by workflow, task, tool, time range, and actor.

## 5. Artifact Metadata (Required Fields)

For each artifact version:
- `type` (plan, research_summary, prep_brief, decision_log)
- `state` (Prepared/Draft/Approved/Archived)
- `obsidian_path` and `content_ref`
- `source_refs` (list of `source_id`)
- `created_by` (worker id)
- `model_info` (provider, model, version)
- `confidence` (0–1)
- `workflow_id` and `task_id` provenance
- `frontmatter_hash` (to detect changes)

## 6. Memory Indices (Retrieval Model)

- **Episodic Memory:** derived from `audit_logs` + `task_attempts`; stored as `memory_items` with type `episodic` and pointers to the relevant `audit_id` range.
- **Semantic Memory:** `memory_items` with type `semantic` linked to `artifact_versions` and `embeddings`.
- **Indexing fields:** `memory_id`, `artifact_version_id`, `embedding_id`, `source_id`, `created_at`.

## 7. Resumable Workflow Guarantees

To resume safely after crashes:
- `workflows.lease_owner` and `lease_expires_at` enable re-claiming.
- `workflow_checkpoints` store the latest durable state.
- `tasks` and `task_attempts` provide idempotent re-run logic.
- `audit_logs` provide full replay context for debugging.

---
This model is designed to be implemented directly with Postgres + pgvector and Redis, while maintaining explicit auditability and resumable workflows.
