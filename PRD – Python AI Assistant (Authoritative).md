---
title: PRD – Python AI Assistant (Authoritative)
created: 2026-01-30
updated: 2026-01-30
status: authoritative
version: 1.0
---

PRD – Python AI Assistant (Authoritative)

Executive Summary
The Python AI Assistant is a long-running, background personal chief‑of‑staff system that plans, prepares, and supports execution across day/week/month/future horizons. It detects intent and signals from email, calendar, and Obsidian notes, conducts background research and preparation, and delivers structured artifacts into an Obsidian vault. WhatsApp is the primary interaction channel for approvals and updates. The system is containerized with Docker Compose, uses DeepSeek as the primary LLM, supports Ollama and smaller HuggingFace models as fallbacks, maintains durable state and full auditability, and must survive crashes with resumable workflows.

Product Vision & Promise
The assistant is a persistent, proactive planning and preparation system, not a chat toy. It reduces cognitive load and prevents oversights by preparing draft plans, research, and reminders, while preserving user control and transparency. It is not a general‑purpose autonomous agent; it operates within explicit boundaries, never mutates user data without approval, and always explains its reasoning.

Core Use Cases

- Planning (day/week/month/future): Create draft plans from calendar, known goals, and confirmed intentions; surface preparation items; propose time blocks and checklists; store as Obsidian notes.
- Job search assistance: Detect job‑related signals, confirm intent, compile application tracking notes, suggest CV changes, prepare interview research bundles, and generate interview prep checklists.
- Research support: Run approved research workflows (search → fetch → extract → synthesize) and produce structured Obsidian artifacts with provenance.
- Preparation for events: Identify upcoming meetings/trips/deadlines; create prep briefs with agenda, open questions, and needed materials.

Assistant Behavior Model

- Runs continuously as a service/daemon; processes background tasks independently of chat sessions.
- Suggestion‑first behavior: all proactive outputs are drafts or recommendations with an explicit rationale.
- By default, the assistant optimizes for preparation over interruption and prefers to produce drafts rather than messages.
- Explicit approval required for any action that mutates calendar, files, notes, or external systems.
- Background work is read‑only by default; writes create labeled draft artifacts only.
- Background checks run on a bounded schedule (e.g., hourly or daily) and never continuously poll external systems.
- Messages are queued and respect quiet hours, frequency limits, and a global proactive toggle.
- The user can always request status, stop work, or see recent activity.

Planning & Time Horizons

- Daily plan: generated each morning or on request; includes schedule, prep tasks, and risks.
- Weekly plan: generated once per week; summarizes commitments and prep needs.
- Monthly plan: generated once per month; tracks milestones and long‑range prep.
- Event‑based plans: generated when a future event is detected and confirmed.
- Each plan is a structured Obsidian note with timestamps, sources, and a “Draft/Proposed” label.

Intent & Signal Detection Model

- Inputs: email, calendar events, Obsidian notes, explicit user messages.
- Pipeline: ingestion → entity/date extraction → intent classification → confidence scoring.
- Clarification‑first: if intent is not explicitly confirmed, the assistant asks before planning or storing memory.
- Signal thresholds: only high‑confidence signals can trigger proactive suggestions; low confidence requires explicit user confirmation.
- Every detected intent is logged with source references.

Autonomy Levels & Safety Guarantees

- Level 0 (Observe): no proactive messages; only responds on request.
- Level 1 (Suggest): detects signals and asks clarifying questions; no background research.
- Level 2 (Prepare Drafts): runs background research and produces draft artifacts; no external mutations.
- Level 3 (Execute with Approval): performs user‑approved actions (calendar changes, document updates) only after explicit consent.
  Safety guarantees (non‑negotiable):
- No silent actions or knowledge changes.
- All actions and decisions are auditable and replayable.
- Tool execution is isolated and resource‑limited.
- Failures must not corrupt state; workflows are resumable.

Memory & Knowledge Model (Product Level)

- Memory types: working (short‑term context), episodic (chronological action records), semantic (long‑term knowledge).
- Memory creation requires explicit user confirmation; inferred memory is prohibited.
- Memory is inspectable and editable by the user at all times.
- Obsidian is the system of record for knowledge; databases store indices, embeddings, and metadata only.
- Knowledge updates are versioned; no destructive edits to existing notes.

User Interaction Model (WhatsApp‑First)

- WhatsApp is the primary channel for suggestions, approvals, and status updates.
- Messages are concise, explain “why,” and include quick actions (Approve, Snooze, Dismiss).
- The assistant never sends messages without a clear causal trigger.
- The user can issue commands such as “pause background,” “what are you working on,” and “show recent activity.”

Research & Document Generation Capabilities

- Research runs as a durable workflow with checkpoints and retries.
- Outputs are structured Obsidian artifacts: research summaries, prep briefs, comparison tables, and decision logs.
- Artifacts include metadata: sources, timestamps, model used, confidence, and approval status.
- Artifacts progress through states: Prepared → Draft → Approved → Archived. State transitions are user‑initiated and audited.

Non‑Goals

- No real‑time conversational chatbot focus; priority is background workflows.
- No multi‑tenant or enterprise features (SSO, RBAC, compliance certifications) in v1.
- No multimodal processing (images/audio/video) in v1.
- No autonomous actions without explicit approval.
- No self‑modifying or self‑optimizing behavior.
- No financial or legal advice decision‑making.

System Constraints & Invariants

- Docker + Docker Compose deployment is required.
- DeepSeek API is the primary LLM; Ollama and smaller HuggingFace models are supported fallbacks.
- The system must run on CPU‑only hardware; GPU is optional.
- Obsidian vault is mounted as a volume and never baked into images.
- Every action is audited with inputs, outputs, and reasoning context.
- Workflows must survive crashes and resume from last checkpoint.
- Tool execution is isolated; tools never directly mutate core state.
- Transparency overrides performance when in conflict.
- User control overrides automation.

Dependencies & Assumptions

- WhatsApp connectivity via a configurable provider (e.g., WhatsApp Business API integration).
- Email and calendar access via authenticated connectors.
- PostgreSQL with pgvector and Redis are available via Docker Compose.
- Optional Temporal workflow engine for durable orchestration.
- User maintains an accessible Obsidian vault on disk.

Risks & Mitigations

- Tool escape or unsafe execution: enforce layered isolation, resource limits, and allow‑list permissions.
- State corruption: enforce ACID transactions, atomic file writes, and immutable audit logs.
- Observability gaps: require structured logging and workflow tracing from day one.
- Obsidian file conflicts: serialize writes through a queue with atomic rename.
- LLM outage or cost spikes: fallback routing and queued background jobs.
- Over‑notification: enforce quiet hours, rate limits, and user‑controlled proactive toggles.

Milestones / Phased Delivery

- Phase 0 – Foundation (Weeks 1–2): PostgreSQL schema, audit log, minimal workflow runner, basic tool isolation, Obsidian draft writer, WhatsApp stub integration.
- Phase 1 – Durability & Drafts (Weeks 3–4): durable workflows, background job persistence, signal detection from email/calendar, draft plan generation, and resumable workflows.
- Phase 2 – Production Hardening (Weeks 5–6): containerized isolation upgrades, observability stack, WhatsApp production integration, and reliability testing.

Open Design Decisions

- WhatsApp provider choice and authentication model for production integration.
- Which email and calendar providers are supported in v1 (e.g., Google vs Microsoft).