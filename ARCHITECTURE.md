ARCHITECTURE — Python AI Assistant v1 (Alpha)

Purpose
- Build a long-running personal assistant that is safe, auditable, and resumable.
- Provide planning and preparation support with explicit user approval gates.

What This System Is
- A durable planning and execution engine with human approval boundaries.
- A pipeline that turns signals into structured outputs and draft artifacts.
- A system of record that favors append-only, auditable state.

What This System Is NOT
- Not an autonomous agent that acts without approval.
- Not a chat-first assistant with hidden side effects.
- Not a background scheduler that continuously polls external systems.

Closed-Loop Execution Graph (v1)
1. Signals ingested (manual/explicit ingest)
2. Intents proposed (deterministic rules)
3. Suggestions queued (non-directive, human-facing)
4. Approvals recorded (explicit user decision)
5. Workflows created (pending only)
6. Steps planned (deterministic, idempotent)
7. Tasks materialized (deterministic, idempotent)
8. Tools planned (auditable, no execution unless gated)
9. Tasks executed (worker-driven, lease-based)
10. Steps completed (only when tasks completed)
11. Workflow completed
12. Workflow output aggregated
13. Obsidian draft note created
14. WhatsApp notifications queued (not sent)

Authority Boundaries
- Suggestions are informational only.
- Approvals are the sole trigger for workflow creation.
- Execution only occurs inside worker leasing rules.
- No task executes external tools unless explicitly gated.

Durability & Auditability
- All critical state is persisted in PostgreSQL.
- Append-only audit log records every state transition.
- Idempotency keys prevent duplicate creation.
- Leases protect task execution under crash/restart.

Runtime Roles
- Orchestrator: ingress (signals), classification (intents), suggestions, approvals, planning.
- Worker: task execution, step/workflow completion, output aggregation, draft artifact creation.

Tool Boundary
- Tools are declared and planned, not executed by default.
- Tool execution is gated by sandbox type and explicit mapping.
- Tool outputs are metadata-only unless expanded later.

Safety Guarantees
- No automatic external I/O without explicit enablement.
- All user-visible effects are draft or queued.
- Failures never silently mutate or erase history.

Data Artifacts
- Workflow outputs are a single, canonical JSON aggregation per workflow.
- Obsidian notes are created as drafts with frontmatter status.
- WhatsApp messages are queued records only; delivery is out of scope.

Extension Rules
- New task types must preserve idempotency and audit logging.
- New tools must be gated and auditable.
- New automation must preserve explicit user approval boundaries.

This file is the architectural contract for v1.
