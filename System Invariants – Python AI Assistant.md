---
tags: [system-design, invariants, constraints, architecture]
created: 2026-01-30
updated: 2026-01-30
status: active
importance: critical
---

# System Invariants – Python AI Assistant

These are the non-negotiable rules that govern the design, implementation, and operation of the Python AI Assistant. They override convenience, speed, or any other consideration.

## Core Invariants

### 1. No Silent Knowledge Mutation
**Rule:** Knowledge stored in the system must never be modified without explicit user approval or a clear audit trail.
**Implications:**
- All knowledge updates must be versioned
- Changes to stored facts require explicit confirmation
- No background "cleaning" or "optimization" of knowledge without user awareness
- Obsidian notes are treated as immutable once created; updates create new versions

### 2. Every Action Must Be Auditable
**Rule:** Every system action, from tool execution to knowledge retrieval, must leave a complete audit trail.
**Implications:**
- All tool calls logged with inputs, outputs, and context
- All decisions recorded with reasoning chain
- All external interactions (web searches, API calls) fully logged
- Audit logs must be human-readable and machine-queryable
- No "black box" operations allowed

### 3. Workflows Must Be Resumable
**Rule:** Any workflow or task must survive system crashes, restarts, and failures without data loss.
**Implications:**
- Workflow state must be persisted at logical boundaries
- Checkpoints must capture enough context to resume
- Partial failures must not corrupt overall workflow state
- Users must be able to manually resume interrupted workflows

### 4. Tools Must Be Isolated
**Rule:** Tool execution must be isolated from core system state and from other tools.
**Implications:**
- Tools run in separate processes or containers
- Tool failures must not crash the main system
- Tools cannot directly modify system state
- All tool outputs must be validated before integration
- Network and resource limits enforced per tool

### 5. Failures Must Not Corrupt State
**Rule:** System failures (crashes, errors, timeouts) must leave the system in a recoverable state.
**Implications:**
- Database transactions used for state changes
- Atomic operations for critical updates
- Rollback mechanisms for partial updates
- Failure detection before state corruption
- Graceful degradation, not catastrophic failure

### 6. Obsidian is the System of Record for Knowledge
**Rule:** Obsidian serves as the authoritative, human-readable source of truth for all knowledge.
**Implications:**
- All research findings, synthesis, and conclusions go to Obsidian
- Database stores references, not primary knowledge content
- Obsidian notes are the interface for human review and editing
- Knowledge in Obsidian takes precedence over cached or derived versions
- Obsidian structure drives knowledge organization, not vice versa

## Derived Principles

### 7. Transparency Over Performance
**Rule:** When trade-offs exist, choose the option that provides more transparency, even if slower.
**Implications:**
- Logging overhead accepted for debuggability
- Synchronous operations preferred when they improve auditability
- Simple, understandable code over clever optimizations
- Explicit configuration over magic behavior

### 8. User Control Over Automation
**Rule:** The user retains ultimate control over all autonomous behavior.
**Implications:**
- Autonomous loops require explicit user enablement
- Users can pause, modify, or cancel any operation
- System must explain what it's doing and why
- No "background" actions without user awareness

### 9. Defense in Depth for Safety
**Rule:** Multiple layers of safety controls, not just one.
**Implications:**
- Tool isolation at multiple levels (process, container, resource limits)
- Input validation at multiple points
- Permission checks before and during execution
- Fail-safe defaults for all operations

### 10. Progressive Disclosure of Complexity
**Rule:** System complexity should be hidden initially, revealable on demand.
**Implications:**
- Simple interfaces for common operations
- Detailed views available for debugging
- Configuration exposed gradually as needed
- Internal state inspectable but not overwhelming

## Enforcement Mechanisms

### Technical Enforcement
- Database constraints for data integrity
- Process isolation boundaries
- Automated audit log generation
- Version control for all artifacts
- Automated testing of invariants

### Process Enforcement
- Code reviews must check invariant compliance
- Deployment checks for safety mechanisms
- Regular audit log reviews
- Failure post-mortems that examine invariant violations

### Cultural Enforcement
- These invariants documented and visible to all contributors
- Violations treated as critical bugs, not features
- Design discussions reference relevant invariants
- New features evaluated against invariant compatibility

## When Invariants Conflict

In rare cases where invariants conflict:
1. **Safety first:** Isolation and non-corruption override other concerns
2. **Transparency second:** Auditability over performance
3. **User control third:** User override capability maintained
4. **Document the conflict** and rationale for resolution

## Exceptions

No exceptions to these invariants are permitted in the core system. If a use case appears to require an exception, it indicates either:
- A flaw in the use case design
- A need to refine the invariant
- A misunderstanding of system capabilities

All proposed exceptions must go through formal review and result in either rejection or invariant modification.

---

*These invariants form the foundation for [[Architecture Synthesis – Python AI Assistant]] and constrain [[Runtime Architecture – Python AI Assistant]]. They ensure the system remains [[System Definition – Python AI Assistant]] rather than drifting into unsafe or opaque behavior.*

**Last reviewed:** 2026-01-30
**Next review:** 2026-04-30 (quarterly)
**Review checklist:**
- [ ] All invariants still relevant
- [ ] No new conflicts identified
- [ ] Enforcement mechanisms effective
- [ ] No violations in production