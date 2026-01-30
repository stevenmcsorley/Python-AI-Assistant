---
created: 2026-01-30
updated: 2026-01-30
tags: [architecture, synthesis, python, ai-assistant]
related:
  - "[[Desired Capabilities – Python AI Assistant]]"
  - "[[Research – Task Queues & Workflow Systems (Celery, RQ, Temporal)]]"
  - "[[Research – Async & Parallelism in Python AI Systems]]"
  - "[[Research – Memory & State in AI Systems]]"
  - "[[Research – Production AI Research Systems]]"
  - "[[Research – Databases & Data Models for AI Systems]]"
  - "[[Research – Tool Execution, Isolation & Safety in AI Systems]]"
  - "[[Research – Observability & Debuggability in AI Systems]]"
---

# Architecture Synthesis – Python AI Assistant

*Based on comprehensive research across 7 domains, this synthesis presents an integrated architecture for a long-running Python AI assistant with durable memory, safe autonomy, and production-grade reliability.*

## Executive Summary

The Python AI assistant requires a **hybrid architecture** that balances:
- **Durability** for long-running tasks (Temporal workflow engine)
- **Performance** for I/O-bound operations (asyncio)
- **Safety** for tool execution (layered isolation)
- **Observability** for debugging and trust (structured logging + tracing)
- **Flexibility** for evolving requirements (modular design)

This synthesis integrates findings from all research notes into a cohesive system design.

## 1. Execution Model

### Core Orchestration: Temporal
**Why Temporal over Celery/RQ:**
- **Automatic state persistence** – workflows survive crashes/restarts
- **Built-in retries and compensation** – essential for long-running research
- **Event sourcing** – enables replay and debugging
- **Human-in-the-loop support** – for approval steps and interventions

**Architecture:**
```
User Request → Temporal Workflow → Activity Workers → Results
       ↑              ↓                    ↓
    Obsidian ← Document Synthesis ← Research Pipeline
```

**Where Temporal Fits:**
- Multi-step research workflows
- Background document synthesis
- Long-running investigative tasks
- Any operation requiring durability

**Where Temporal Doesn't Fit:**
- Simple, stateless API calls
- Real-time chat responses
- Memory cache operations
- File I/O operations

### Worker Model
**Hybrid Worker Types:**
1. **Workflow Workers** – Temporal-specific, manage state and coordination
2. **Activity Workers** – Python processes executing specific tasks
3. **Async Workers** – asyncio-based for I/O-bound operations
4. **CPU Workers** – multiprocessing for document processing

## 2. Concurrency & Parallelism Model

### Layered Approach
```
┌─────────────────────────────────────────────┐
│            Temporal Workflow Layer          │
│  (Orchestration, State Management, Retries) │
└─────────────────────────────────────────────┘
                    │
┌─────────────────────────────────────────────┐
│         Application Concurrency Layer        │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐       │
│  │ asyncio │ │ Threads │ │Processes│       │
│  │ (I/O)   │ │ (Mixed) │ │ (CPU)   │       │
│  └─────────┘ └─────────┘ └─────────┘       │
└─────────────────────────────────────────────┘
```

### Specific Use Cases
- **Web Research:** asyncio + aiohttp for parallel page fetching
- **LLM Calls:** asyncio for concurrent API requests
- **Document Processing:** multiprocessing for CPU-heavy operations
- **Tool Execution:** isolated subprocesses with resource limits
- **Memory Operations:** threading for concurrent Redis/DB access

### GIL Considerations
- **I/O-bound:** asyncio avoids GIL contention
- **CPU-bound:** multiprocessing bypasses GIL
- **Mixed workloads:** hybrid approach with process pools

## 3. Background Task Strategy

### Task Classification
| Task Type | Persistence | Concurrency | Isolation | Example |
|-----------|-------------|-------------|-----------|---------|
| **Research Job** | High (DB + Temporal) | Parallel web search | Medium | Multi-source investigation |
| **Document Synthesis** | High (DB + files) | Sequential/parallel | Low | Report generation |
| **Memory Update** | Medium (Redis + DB) | Concurrent | Low | Embedding generation |
| **Tool Execution** | Low (logs only) | Isolated | High | Web scraping, code execution |
| **Observability** | High (immutable) | Async | Low | Logging, metrics |

### Queue Management
- **Primary Queue:** Temporal for durable, stateful workflows
- **Secondary Queue:** Redis for fast, ephemeral tasks
- **Priority Queue:** Separate queues for different SLA requirements
- **Dead Letter Queue:** For failed tasks requiring manual review

## 4. Tool Execution & Isolation Strategy

### Defense-in-Depth Approach
```
┌─────────────────────────────────────┐
│      Application Permissions        │
│  (Tool whitelisting, rate limits)   │
└─────────────────────────────────────┘
                    │
┌─────────────────────────────────────┐
│        Process Isolation            │
│  (Resource limits, timeouts, chroot)│
└─────────────────────────────────────┘
                    │
┌─────────────────────────────────────┐
│      Container/Virtualization       │
│  (Docker, gVisor for high-risk ops) │
└─────────────────────────────────────┘
```

### Implementation Phases
**Phase 1 (Basic):**
- Subprocess with timeouts and resource limits
- Tool whitelisting and parameter validation
- Output sanitization for web content

**Phase 2 (Enhanced):**
- Docker container isolation for untrusted tools
- Network namespace isolation for web scraping
- Read-only filesystem mounts

**Phase 3 (Advanced):**
- MicroVM isolation (Firecracker, gVisor)
- Hardware-assisted virtualization
- Formal verification of safety properties

### Failure Containment
- **Partial writes:** Atomic operations with rollback
- **State corruption:** Immutable event log + snapshotting
- **Resource leaks:** Process/container lifecycle management
- **Network issues:** Circuit breakers and fallbacks

## 5. Memory vs Knowledge Separation

### Memory Layers
```
┌─────────────────────────────────────────┐
│          Working Memory (Redis)         │
│  • Session context                      │
│  • Temporary calculations               │
│  • Rate limiting state                  │
│  • Cache for frequent queries           │
└─────────────────────────────────────────┘
                    │
┌─────────────────────────────────────────┐
│         Episodic Memory (PostgreSQL)    │
│  • Action history                       │
│  • Decision logs                        │
│  • Task outcomes                        │
│  • Timeline of events                   │
└─────────────────────────────────────────┘
                    │
┌─────────────────────────────────────────┐
│         Semantic Memory (pgvector)      │
│  • Vector embeddings                    │
│  • Knowledge graph                      │
│  • Document summaries                   │
│  • Research findings                    │
└─────────────────────────────────────────┘
                    │
┌─────────────────────────────────────────┐
│           Obsidian Knowledge            │
│  • Human-readable reports               │
│  • Research synthesis                   │
│  • Decision documentation               │
│  • Audit trail (human view)             │
└─────────────────────────────────────────┘
```

### Knowledge Flow
1. **Working → Episodic:** Session context becomes historical record
2. **Episodic → Semantic:** Actions inform knowledge embeddings
3. **Semantic → Obsidian:** Insights become human-readable knowledge
4. **Obsidian → Semantic:** Human edits update AI understanding

## 6. Database Choices and Data Roles

### Hybrid Database Architecture
```
┌─────────────────────────────────────────────────┐
│            PostgreSQL + pgvector                │
│  • Workflow state                               │
│  • Episodic memory                              │
│  • Vector embeddings                            │
│  • Audit logs                                   │
│  • User permissions                             │
└─────────────────────────────────────────────────┘
                    │
┌─────────────────────────────────────────────────┐
│                    Redis                        │
│  • Working memory                               │
│  • Cache layer                                  │
│  • Rate limiting                                │
│  • Session state                                │
└─────────────────────────────────────────────────┘
                    │
┌─────────────────────────────────────────────────┐
│              Object Storage                     │
│  • Large documents                              │
│  • Generated reports                            │
│  • Research artifacts                           │
│  • Backup snapshots                             │
└─────────────────────────────────────────────────┘
```

### Schema Design Principles
1. **Immutable event log** for auditability
2. **Versioned artifacts** with lineage tracking
3. **Soft deletes** for recovery and analysis
4. **JSONB columns** for flexible metadata
5. **Foreign key constraints** for data integrity

### Data Migration Strategy
- **Phase 1:** Single PostgreSQL instance with basic schemas
- **Phase 2:** Add Redis for performance-critical operations
- **Phase 3:** Evaluate dedicated vector store if scale demands
- **Always:** Maintain backward compatibility and migration paths

## 7. Observability and Audit Strategy

### Multi-Layer Observability
```
┌─────────────────────────────────────────────┐
│        Application Logging                  │
│  • Structured JSON logs                     │
│  • Correlation IDs across services          │
│  • Log levels per component                 │
└─────────────────────────────────────────────┘
                    │
┌─────────────────────────────────────────────┐
│        Distributed Tracing                  │
│  • OpenTelemetry instrumentation            │
│  • Workflow step tracing                    │
│  • Latency breakdowns                       │
└─────────────────────────────────────────────┘
                    │
┌─────────────────────────────────────────────┐
│        Metrics Collection                   │
│  • Prometheus metrics                       │
│  • Business metrics (acceptance rate, etc.) │
│  • Resource utilization                     │
└─────────────────────────────────────────────┘
                    │
┌─────────────────────────────────────────────┐
│        Audit Trail                          │
│  • Immutable database records               │
│  • Decision context capture                 │
│  • User action logging                      │
│  • Change history                           │
└─────────────────────────────────────────────┘
```

### What to Capture
1. **Decision Context:**
   - Input data and sources
   - Alternative options considered
   - Confidence scores and reasoning
   - Tool usage and parameters

2. **Execution Details:**
   - Start/end times and duration
   - Resource consumption
   - Errors and retries
   - External service calls

3. **Business Context:**
   - User who initiated action
   - Purpose and goals
   - Success criteria
   - Business impact

### Debugging Strategies
- **Replay capability:** Reconstruct execution from event log
- **Step-through debugging:** Inspect intermediate states
- **Comparative analysis:** Compare successful vs failed runs
- **Anomaly detection:** Identify patterns in failures

## 8. Integration with Orchestration Frameworks

### Where Frameworks Fit

**Temporal (Primary Orchestration):**
- ✅ Long-running workflows with state persistence
- ✅ Multi-step research pipelines
- ✅ Background document synthesis
- ✅ Failure recovery and compensation
- ✅ Human approval workflows

**LangChain/AutoGen (Avoid for Core):**
- ❌ Core orchestration (too opaque, poor observability)
- ✅ Specific tool integrations if well-isolated
- ✅ LLM interaction patterns (but implement directly for control)
- ✅ Rapid prototyping (but not production)

**Custom Implementation (Preferred):**
- ✅ Tool execution and isolation
- ✅ Memory management layers
- ✅ Observability instrumentation
- ✅ Integration with Obsidian
- ✅ Safety and permission systems

### Framework Selection Criteria
1. **Transparency:** Can we trace and debug every step?
2. **Control:** Can we customize behavior for safety?
3. **Observability:** Does it support our audit requirements?
4. **Durability:** Does state survive crashes?
5. **Integration:** Does it work with our stack?

## 9. Implementation Roadmap

### Phase 1: Foundation (Weeks 1-4)
- PostgreSQL + pgvector setup with basic schemas
- Temporal workflow engine for task orchestration
- Basic tool execution with process isolation
- Structured logging and metrics collection
- Simple Obsidian integration

### Phase 2: Capabilities (Weeks 5-8)
- Redis integration for working memory
- Advanced tool isolation (Docker containers)
- Distributed tracing with OpenTelemetry
- Multi-layer memory system
- Enhanced observability dashboard

### Phase 3: Production (Weeks 9-12)
- MicroVM isolation for high-risk tools
- Comprehensive audit trail system
- Performance optimization and scaling
- Disaster recovery procedures
- Security hardening and penetration testing

## 10. Key Trade-offs and Decisions

### Made Decisions
1. **Temporal over Celery/RQ** – for durability and state management
2. **PostgreSQL + pgvector over MongoDB** – for consistency and vector search
3. **Custom over LangChain** – for transparency and control
4. **Hybrid concurrency** – asyncio + multiprocessing based on workload
5. **Defense-in-depth isolation** – multiple layers of security

### Open Questions
1. **Vector database scale:** When to move from pgvector to dedicated store?
2. **Isolation level:** How much virtualization overhead is acceptable?
3. **Observability storage:** How long to retain detailed traces?
4. **Cache invalidation:** Strategy for semantic memory updates?

## 11. Risk Mitigation

### Technical Risks
- **State corruption:** Immutable event log + regular snapshots
- **Resource exhaustion:** Strict limits + monitoring + circuit breakers
- **Security breaches:** Layered isolation + least privilege + audit trails
- **Performance degradation:** Progressive enhancement + caching + load testing

### Operational Risks
- **Debugging complexity:** Comprehensive observability from day one
- **Data migration:** Versioned schemas + backward compatibility
- **Tool failures:** Graceful degradation + manual override points
- **Knowledge drift:** Regular validation + human review cycles

## 12. Success Metrics

### Technical Metrics
- Workflow completion rate (>95%)
- Mean time to recovery (<5 minutes)
- Observability coverage (>90% of execution paths)
- Isolation effectiveness (zero escapes from sandbox)

### Capability Metrics
- Research task success rate
- Document synthesis quality scores
- Memory retrieval accuracy
- Tool execution safety record

### Operational Metrics
- System availability (>99.5%)
- Mean time between failures
- Audit trail completeness
- Debugging time reduction

## Conclusion

This architecture synthesis presents a **production-ready design** for a Python AI assistant that meets all desired capabilities while addressing the complex requirements of safety, observability, and durability.

The key insight is that **no single technology solves all problems** – the system requires careful integration of specialized components (Temporal for orchestration, PostgreSQL for state, Redis for memory, layered isolation for safety) with custom implementation for transparency and control.

**Next steps:**
1. Create detailed component specifications
2. Prototype critical paths (workflow persistence, tool isolation)
3. Establish development and deployment pipelines
4. Begin Phase 1 implementation with focused milestones

---
*This synthesis integrates findings from all research notes and provides a concrete foundation for implementation.*