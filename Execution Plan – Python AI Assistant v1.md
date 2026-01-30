---
title: Execution Plan – Python AI Assistant v1
date: 2026-01-30
status: draft
phase: planning
confidence: high
---

## Overview

This execution plan outlines a pragmatic, time‑boxed build sequence for the Python AI Assistant v1, assuming a single developer. It is based on the [[PRD – Python AI Assistant v1]] and [[Runtime Architecture – Python AI Assistant]] notes.

The plan is structured in three phases, each with clear deliverables, risks, and validation checkpoints. The goal is to deliver a working, durable, and safe assistant incrementally, while keeping the codebase maintainable and the architecture evolvable.

## Phase 0 – Foundation & Core Workflow Engine (Weeks 1‑2)

**Goal:** Establish the basic workflow orchestration, durable state storage, and a minimal tool‑execution loop.

### What Must Be Correct from Day One
- **PostgreSQL + pgvector schema** – The core tables for workflows, tasks, and audit logs must be designed to support all future phases. Schema migrations must be planned from the start.
- **Workflow‑state persistence** – The ability to save and resume a workflow’s state after a crash is non‑negotiable.
- **Basic isolation boundary** – Even a simple subprocess sandbox must prevent tool calls from corrupting the main process.
- **Immutable audit log** – Every action taken by the assistant must be recorded in an append‑only log that cannot be altered.

### What Can Be Stubbed or Mocked
- **Advanced memory layers** – Semantic (vector) memory can be a simple in‑memory dict; episodic memory can be logged to a file.
- **Full observability stack** – Start with structured logging to stdout; distributed tracing can be added later.
- **Complex tool set** – Implement only 2‑3 essential tools (e.g., web‑fetch, note‑creation).
- **Background job queue** – Use a simple in‑memory queue; defer to Temporal or a robust message broker in Phase 2.
- **Multi‑worker parallelism** – Run everything in a single process; concurrency can be simulated with asyncio.

### Key Technical Risks (Phase 0)
1. **PostgreSQL schema locks us in** – If the initial schema is too rigid, later changes may require costly migrations.
   *Mitigation:* Use JSONB fields for extensible metadata; keep tables normalized but add version columns early.
2. **State‑serialization breaks** – Pickle or JSON serialization of complex Python objects may fail on resume.
   *Mitigation:* Use a simple, explicit state dictionary; avoid serializing open file handles or network connections.
3. **Sandbox escapes** – A naive subprocess sandbox may allow tools to modify the host filesystem or exhaust memory.
   *Mitigation:* Apply resource limits (CPU, memory, disk) and run tools as a low‑privilege OS user.

### Validation Checkpoints (Phase 0)
- [ ] **Checkpoint 0.1** – PostgreSQL schema created and can store/retrieve a workflow record.
- [ ] **Checkpoint 0.2** – A simple “research” workflow can be started, paused (kill the process), and resumed from the last step.
- [ ] **Checkpoint 0.3** – A tool (e.g., `web_fetch`) runs in a sandboxed subprocess; the main process survives a malformed response.
- [ ] **Checkpoint 0.4** – Every step logs an immutable audit entry; the log can be replayed to reconstruct what happened.

## Phase 1 – Durability & Basic Autonomy (Weeks 3‑4)

**Goal:** Harden the system for long‑running operation, add background job execution, and implement the first autonomous loops (e.g., multi‑step research).

### What Must Be Correct from Day One
- **Background job persistence** – Jobs scheduled for later execution must survive a system restart.
- **Failure‑handling boundaries** – A failing tool must not crash the entire workflow; errors must be captured and recorded.
- **Obsidian‑integration contract** – The format and location of generated notes must be stable; changes will break user expectations.
- **Resource‑limit enforcement** – Background jobs must respect CPU/memory/network quotas to avoid starving the system.

### What Can Be Stubbed or Mocked
- **Advanced vector search** – Use pgvector’s exact search; defer approximate nearest‑neighbor indexes until needed.
- **Full‑blown container isolation** – Continue with subprocess sandboxing; container‑based isolation can be a Phase 2 upgrade.
- **Multi‑node deployment** – Assume a single machine; scaling horizontally is out of scope for v1.
- **Real‑time user interaction** – The assistant runs in “batch” mode; interactive prompting can be simulated with a config file.

### Key Technical Risks (Phase 1)
1. **Background job starvation** – Poorly written jobs may run forever, blocking other work.
   *Mitigation:* Implement timeouts and a watchdog that kills jobs exceeding their quota.
2. **State‑bloat in PostgreSQL** – Checkpoints and audit logs may grow rapidly, slowing down queries.
   *Mitigation:* Introduce periodic archiving of completed workflows; use table partitioning if growth is a concern.
3. **Obsidian‑file corruption** – Concurrent writes to the same note could produce garbled output.
   *Mitigation:* Use file‑locking or a write queue for Obsidian operations; treat the vault as an eventually‑consistent store.

### Validation Checkpoints (Phase 1)
- [ ] **Checkpoint 1.1** – A background research job runs for >1 hour, survives a system reboot, and resumes where it left off.
- [ ] **Checkpoint 1.2** – A tool that raises an exception is caught; the workflow logs the error, skips that step, and continues.
- [ ] **Checkpoint 1.3** – The assistant can perform a multi‑step research task (search → fetch → summarize → write to Obsidian) without human intervention.
- [ ] **Checkpoint 1.4** – Resource limits are enforced: a tool that tries to allocate 2 GB of memory is killed, and the workflow handles the failure gracefully.

## Phase 2 – Production‑Ready & Scaling (Weeks 5‑6)

**Goal:** Add production‑grade observability, improve isolation, and prepare the system for real‑world usage.

### What Must Be Correct from Day One
- **Observability pipeline** – Logs, metrics, and traces must be reliable; losing observability data hampers debugging.
- **Security boundaries** – The chosen isolation layer (containers or microVMs) must truly prevent tool escapes.
- **Data‑migration pathway** – Any schema or storage changes must have a clear, tested migration script.
- **Deployment packaging** – The system must be deployable via a single command (Docker Compose, install script).

### What Is Explicitly Deferred (Beyond v1)
- **Multi‑tenant support** – v1 assumes a single user/instance.
- **Real‑time collaboration** – No live syncing of assistant state across multiple clients.
- **Advanced LLM‑routing** – All LLM calls go to a single provider/model; dynamic model selection is out of scope.
- **Self‑healing/self‑optimization** – The assistant does not modify its own code or architecture.
- **Cross‑platform GUIs** – The primary interface is the Obsidian vault and a CLI; no web dashboard or mobile app.

### Key Technical Risks (Phase 2)
1. **Observability overhead** – Adding tracing may slow down the workflow engine significantly.
   *Mitigation:* Use sampling (e.g., trace 1 in 10 requests) and async exporters.
2. **Container‑orchestration complexity** – Introducing Docker or microVMs adds moving parts that can fail in subtle ways.
   *Mitigation:* Start with a single‑container approach; keep the host‑mounts minimal and well‑documented.
3. **Upgrade‑path breakage** – Changes to the workflow‑state format may make older checkpoints unreadable.
   *Mitigation:* Maintain backward‑compatibility shims for at least one previous version; provide a state‑migration tool.

### Validation Checkpoints (Phase 2)
- [ ] **Checkpoint 2.1** – A full workflow trace can be viewed in a tracing UI (e.g., Jaeger), showing every tool call and LLM request.
- [ ] **Checkpoint 2.2** – A malicious tool payload (e.g., attempt to write outside its sandbox) is contained and logged.
- [ ] **Checkpoint 2.3** – The entire system can be deployed on a fresh machine with `docker‑compose up` (or equivalent).
- [ ] **Checkpoint 2.4** – A 24‑hour stress test runs without memory leaks, disk‑space exhaustion, or unhandled crashes.

## Pragmatic Constraints & Trade‑offs

- **Single developer** – Focus on one phase at a time; avoid context‑switching between front‑end, back‑end, and ops work.
- **Time‑boxing** – If a checkpoint slips by >2 days, re‑scope the phase rather than extending the timeline indefinitely.
- **Tool‑over‑framework** – Prefer writing a simple, transparent component over adopting a heavy framework that hides too much.
- **Obsidian as the UI** – Invest in clean note‑templates and linking conventions; avoid building a custom UI until the core is stable.

## Success Criteria for the Overall Plan

- **Phase 0** delivers a **runnable prototype** that can be demonstrated end‑to‑end.
- **Phase 1** delivers a **usable system** that can perform real research tasks unattended.
- **Phase 2** delivers a **deployable product** that a technical user could install and run on their own machine.

## Next Steps

1. Begin Phase 0 by setting up the PostgreSQL schema and a simple workflow‑runner loop.
2. After each checkpoint, update this note with actual results and adjust subsequent phases if needed.
3. Keep a separate “lessons‑learned” note to capture what works and what doesn’t.

---
*This plan builds on [[PRD – Python AI Assistant v1]], [[Runtime Architecture – Python AI Assistant]], and [[Initial Data Model – Python AI Assistant]].*