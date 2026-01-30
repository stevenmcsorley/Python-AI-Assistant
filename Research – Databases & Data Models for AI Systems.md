---
created: 2026-01-30
tags: [research, databases, ai-systems, data-models, python-ai-assistant]
connections:
  - "[[Architecture Synthesis – Python AI Assistant]]"
  - "[[Desired Capabilities – Python AI Assistant]]"
  - "[[Research – Memory & State in AI Systems]]"
  - "[[Research – Production AI Research Systems]]"
---

# Research – Databases & Data Models for AI Systems

*Based on analysis of SQL vs NoSQL databases for AI applications, vector database considerations, and AI agent data requirements.*

## Types of Data AI Systems Need to Store

### Core Data Categories
1. **Jobs & Workflows**
   - Task definitions and parameters
   - Execution status and progress
   - Priority and scheduling information
   - Dependencies and relationships

2. **Memory Systems**
   - **Working memory:** Session context, temporary calculations
   - **Episodic memory:** Chronological action records, decision logs
   - **Semantic memory:** Vector embeddings, knowledge representations
   - **Procedural memory:** Tool configurations, execution patterns

3. **Artifacts & Outputs**
   - Generated documents and reports
   - Research findings and summaries
   - Code snippets and configurations
   - Intermediate processing results

4. **Logs & Audit Trails**
   - System events and errors
   - User interactions and decisions
   - Performance metrics and timing
   - Security and access logs

5. **Embeddings & Vector Data**
   - Text embeddings for semantic search
   - Document chunk embeddings
   - Knowledge graph representations
   - Multi-modal embeddings (text, images, audio)

## Relational vs Document vs Vector Storage Roles

### Relational Databases (SQL)
**Best for:** Structured data with strong consistency requirements
- User profiles and permissions
- Workflow state and job tracking
- Audit trails and compliance logs
- Financial transactions and billing
- Metadata for artifacts and outputs

**Examples:** PostgreSQL (with pgvector), MySQL, SQLite

### Document Databases (NoSQL)
**Best for:** Flexible, schema-less data
- Chat history and conversation context
- JSON-based configurations and settings
- Unstructured research findings
- Rapid prototyping and iteration
- User preferences and session data

**Examples:** MongoDB, Firebase, CouchDB

### Vector Databases
**Best for:** High-dimensional similarity search
- Semantic memory and embeddings
- RAG (Retrieval Augmented Generation) contexts
- Knowledge base vector representations
- Multi-modal AI applications
- Real-time recommendation systems

**Examples:** Pinecone, Weaviate, Qdrant, ChromaDB, pgvector

### In-Memory Databases
**Best for:** Low-latency access
- Working memory and active context
- Caching of frequent queries
- Rate limiting and throttling
- Session state management
- Real-time analytics counters

**Examples:** Redis, Memcached

## Common Hybrid Database Patterns

### Pattern 1: PostgreSQL + pgvector + Redis
- **PostgreSQL:** Primary data store for structured data
- **pgvector:** Vector search extension within PostgreSQL
- **Redis:** Working memory and caching layer

**Use case:** Most balanced approach for AI assistants, combining ACID compliance with vector search and low-latency access.

### Pattern 2: MongoDB + Dedicated Vector DB
- **MongoDB:** Flexible document store for unstructured data
- **Pinecone/Weaviate:** Specialized vector database
- **Redis:** Optional caching layer

**Use case:** Applications needing maximum flexibility for unstructured data with high-performance vector search.

### Pattern 3: Polyglot Persistence
- **PostgreSQL:** Transactions and structured data
- **MongoDB:** JSON documents and flexible schemas
- **Redis:** Caching and real-time data
- **Vector DB:** Embeddings and semantic search

**Use case:** Enterprise-scale AI systems with diverse data requirements.

## Trade-offs Between Simplicity and Flexibility

### Simplicity-First Approach
**Pros:**
- Single database to manage and maintain
- Reduced operational complexity
- Easier backup and recovery
- Lower infrastructure costs
- Simplified development and debugging

**Cons:**
- May not optimize for all data types
- Performance trade-offs for specific workloads
- Limited scalability for certain operations
- May require workarounds for specialized needs

### Flexibility-First Approach
**Pros:**
- Each database optimized for specific workloads
- Maximum performance for each data type
- Can scale components independently
- Leverages specialized features of each system

**Cons:**
- Higher operational burden
- Data consistency challenges
- Complex backup and recovery
- Increased infrastructure costs
- Development complexity across multiple systems

## Schema Design Considerations for AI Workflows

### Workflow State Schema
```sql
-- PostgreSQL schema for durable workflow state
CREATE TABLE workflows (
    id UUID PRIMARY KEY,
    type VARCHAR(50),               -- research, synthesis, analysis, etc.
    status VARCHAR(50),             -- pending, running, paused, completed, failed
    priority INTEGER,               -- execution priority
    current_step INTEGER,           -- progress tracking
    checkpoint JSONB,               -- serialized intermediate state
    parameters JSONB,               -- task-specific parameters
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error_details TEXT,             -- failure information
    metadata JSONB                  -- tags, labels, custom fields
);

CREATE INDEX idx_workflow_status ON workflows(status);
CREATE INDEX idx_workflow_created ON workflows(created_at);
```

### Memory Storage Considerations
1. **Working Memory:** Key-value with TTL (Redis)
   - Session-specific context
   - Temporary calculations
   - Rate limiting counters

2. **Episodic Memory:** Time-series structure
   - Chronological action records
   - Decision logs with timestamps
   - Outcome tracking

3. **Semantic Memory:** Vector + metadata
   - Embeddings with source references
   - Confidence scores and provenance
   - Version history and updates

## How State Survives Restarts and Crashes

### Durability Mechanisms
1. **Workflow Engine Persistence** (Temporal, Airflow)
   - Automatic state checkpointing
   - Event sourcing for reconstruction
   - Compensation actions for failures

2. **Database Transactions**
   - ACID guarantees for critical data
   - Write-ahead logging for crash recovery
   - Point-in-time recovery capabilities

3. **Application-Level Checkpointing**
   - Periodic state serialization
   - Incremental progress saving
   - Resume-from-last-checkpoint logic

### Crash Recovery Strategies
- **Automatic retries** with exponential backoff
- **State reconstruction** from persistent storage
- **Partial rollback** to last consistent state
- **Manual intervention points** for complex failures
- **Dead letter queues** for unprocessable items

### Trade-offs Between Simplicity and Durability
| Approach | Simplicity | Durability | Recovery Complexity |
|----------|------------|------------|---------------------|
| In-memory only | High | Low | High (state lost) |
| Database with transactions | Medium | High | Low (transaction rollback) |
| Event sourcing | Low | Very High | Medium (replay events) |
| Workflow engine | Low | Very High | Low (automatic) |

## Auditability and Explainability Implications

### Database Design for Transparency
1. **Immutable Event Logs**
   - Append-only tables for all actions
   - Cryptographic hashing for integrity
   - Timestamped records with actor information

2. **Decision Tracking**
   - Link outputs to inputs and reasoning steps
   - Store confidence scores and alternatives considered
   - Maintain source references for generated content

3. **Version Control for Artifacts**
   - Git-like branching for document evolution
   - Diff tracking between versions
   - Approval workflows and change reasons

### Explainability Through Data Models
- Store **reasoning chains** with each decision
- Maintain **confidence intervals** for predictions
- Track **data provenance** from source to output
- Record **tool usage patterns** and effectiveness

## Operational Complexity and Migration Concerns

### Infrastructure Trade-offs
| Database Type | Operational Burden | Scaling Complexity | Cost Profile |
|---------------|-------------------|-------------------|--------------|
| Managed SQL | Low | Medium | Predictable, per-instance |
| Self-hosted SQL | High | High | Variable, hardware-dependent |
| Managed NoSQL | Low | Low | Usage-based, can spike |
| Vector DB SaaS | Very Low | Very Low | Per-embedding/query, expensive at scale |
| Self-hosted Vector | High | Medium | Fixed + maintenance |

### Migration Challenges
1. **Embedding Migration**
   - Moving vectors between systems is complex
   - Requires re-indexing and similarity recalibration
   - May break existing references and links

2. **Schema Evolution**
   - AI systems evolve rapidly as capabilities grow
   - Backward compatibility becomes challenging
   - Data transformation pipelines add complexity

3. **Consistency Across Stores**
   - Maintaining referential integrity is difficult
   - Distributed transactions increase latency
   - Conflict resolution requires careful design

## Relevance to Long-running Python AI Assistant

### Direct Mapping to Desired Capabilities
1. **Long-running & resumable tasks** → Workflow state persistence in PostgreSQL
2. **Background research jobs** → Job queue with durable storage
3. **Parallel web search + page reading** → Cache results in Redis, store findings in PostgreSQL
4. **Multi-step reasoning pipelines** → Checkpoint intermediate states in database
5. **Document synthesis into Obsidian** → Store artifacts with metadata in PostgreSQL
6. **Investigative note trails** → Immutable audit logs in database
7. **Durable memory (beyond sessions)** → Multi-layer storage (Redis + PostgreSQL + vector)
8. **Explainable decisions** → Decision tracking with full context in database
9. **Safe background autonomy** → Permission and state tracking in SQL database
10. **Failure recovery & retries** → Failure logs and retry logic in workflow tables

### Recommended Architecture for Python AI Assistant
Based on research findings:

**Core Data Store:** PostgreSQL with pgvector
- Structured data: workflows, jobs, users, permissions
- Vector data: semantic memory, embeddings
- Audit trails: immutable event logs
- Strong consistency for critical operations

**Working Memory Layer:** Redis
- Session state and active context
- Cache for frequent queries (LLM responses, web results)
- Rate limiting and throttling
- Temporary calculations and intermediate results

**Artifact Storage:** Object storage + PostgreSQL metadata
- Large documents, reports, generated content
- Version history with metadata in database
- References linking artifacts to workflows

**Obsidian Integration:**
- Human-readable knowledge base and audit trail
- Linked to database records via IDs or metadata
- Serves as both output destination and input source

### Implementation Phases
**Phase 1 (MVP):** PostgreSQL + pgvector only
- All data in single database for simplicity
- Basic workflow and memory tables
- Simple vector search for embeddings

**Phase 2 (Scale):** Add Redis for working memory
- Session state and caching layer
- Improved performance for frequent operations
- More sophisticated memory management

**Phase 3 (Advanced):** Consider dedicated components
- Evaluate need for separate vector database
- Add object storage for large artifacts
- Implement comprehensive audit system

## Key Takeaways

1. **No single database fits all AI data needs** – Hybrid architectures are the norm in production systems.

2. **PostgreSQL + pgvector is a strong starting point** – Combines structured data management with vector search capabilities.

3. **Redis is essential for working memory** – Provides the low-latency access needed for active reasoning.

4. **Obsidian serves as the human interface** – Bridges the gap between AI-generated content and human consumption.

5. **Durability requires intentional design** – Not automatic; must be built into the architecture from the start.

6. **Auditability impacts every layer** – From database schema to application logic to storage strategy.

## Next Steps

1. Design concrete database schemas for the Python AI assistant
2. Prototype PostgreSQL + pgvector implementation with basic workflows
3. Define data migration strategy for evolving requirements
4. Implement comprehensive audit logging framework
5. Test crash recovery and state persistence scenarios
6. Evaluate performance characteristics at expected scales

---
*Connects to: [[Architecture Synthesis – Python AI Assistant]], [[Desired Capabilities – Python AI Assistant]], [[Research – Memory & State in AI Systems]], [[Research – Production AI Research Systems]]*