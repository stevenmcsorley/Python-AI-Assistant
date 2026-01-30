---
title: Research – Memory & State in AI Systems
date: 2026-01-30
tags: [research, memory, state, ai-systems, architecture]
related:
  - "[[Desired Capabilities – Python AI Assistant]]"
  - "[[System Definition – Python AI Assistant]]"
---
## Overview
Memory and state management are critical for AI systems that need to operate continuously, learn over time, and maintain context across sessions. This research examines memory architectures, storage approaches, and how they relate to building a durable Python AI assistant.

## Memory Types & Taxonomy

### Functional Classification
Based on the Agent-Memory-Paper-List survey, memory can be organized by function:

**Factual Memory** – Knowledge and information storage
- Token-level (explicit & discrete representations)
- Parametric (implicit weights in models)
- Latent (hidden states and embeddings)

**Experiential Memory** – Insights and skills from past interactions
- Episodic memory (specific experiences and events)
- Procedural memory (learned skills and routines)
- Semantic memory (general knowledge and concepts)

**Working Memory** – Active context management
- Short-term buffers for immediate reasoning
- Attention mechanisms for relevant context
- Active planning and decision state

### Temporal Classification
- **Short-term/Working Memory**: Active context for current task (seconds to minutes)
- **Episodic Memory**: Specific experiences and events (hours to days)
- **Semantic Memory**: General knowledge and concepts (persistent)
- **Procedural Memory**: Learned skills and routines (persistent)

## Storage Approaches

### Databases vs Files vs Vector Stores

**Relational Databases (PostgreSQL, SQLite)**
- **Strengths**: ACID guarantees, complex queries, relationships
- **Weaknesses**: Less natural for embeddings, fixed schema
- **Best for**: Structured state, audit logs, workflow metadata

**Document Stores (MongoDB, Redis)**
- **Strengths**: Flexible schema, fast writes, JSON-native
- **Weaknesses**: Less query flexibility, eventual consistency
- **Best for**: Episodic memory, conversation history, tool outputs

**Vector Stores (Pinecone, Chroma, Qdrant)**
- **Strengths**: Semantic search, similarity matching, embeddings
- **Weaknesses**: Not transactional, limited metadata queries
- **Best for**: Semantic memory, knowledge retrieval, document search

**Filesystem (Obsidian, plain text)**
- **Strengths**: Human-readable, version controllable, portable
- **Weaknesses**: Limited query capabilities, slower access
- **Best for**: Long-term knowledge, research notes, documentation

## State Durability & Crash Recovery

### How State Survives Restarts
1. **Checkpointing**: Periodic snapshots of system state
2. **Event Sourcing**: Replayable sequence of actions/decisions
3. **Write-Ahead Logging**: Actions logged before execution
4. **Incremental Persistence**: Continuous background saving

### Failure Scenarios
- **Process crashes**: In-memory state lost, need persistence layer
- **System restarts**: Need automatic recovery to last known state
- **Network partitions**: Handle eventual consistency
- **Storage corruption**: Need backups and validation

## Trade-offs: Simplicity vs Durability

**Simple Approach (Files + SQLite)**
- ✅ Easy to understand and debug
- ✅ Minimal infrastructure
- ✅ Good for prototyping
- ❌ Limited scalability
- ❌ Manual recovery needed
- ❌ Basic query capabilities

**Durable Approach (Temporal + PostgreSQL + Vector Store)**
- ✅ Automatic recovery and retries
- ✅ Scalable and production-ready
- ✅ Rich query capabilities
- ❌ Complex infrastructure
- ❌ Higher operational cost
- ❌ Steeper learning curve

**Hybrid Approach (Obsidian + Redis + Temporal)**
- ✅ Human-readable knowledge base
- ✅ Fast in-memory state
- ✅ Durable workflows
- ❌ Multiple systems to maintain
- ❌ Integration complexity
- ❌ Consistency challenges

## Auditability & Explainability

### Memory as Audit Trail
- Every decision and action should be traceable to source memory
- Memory updates should be logged with timestamps and reasons
- Users should be able to query "Why did you think that?"

### Explainability Implications
- **Transparent memory**: Users can inspect stored knowledge
- **Retrieval explanations**: Show why certain memories were recalled
- **Update transparency**: Clear when and why memory changes
- **Confidence tracking**: How certain the system is about memories

## Obsidian as Knowledge Spine

### Strengths for AI Systems
1. **Human-AI collaboration**: Both can read/write the same format
2. **Structured yet flexible**: Markdown with YAML frontmatter
3. **Relationship tracking**: Backlinks create knowledge graphs
4. **Version control friendly**: Git-compatible plain text
5. **Portable and durable**: Not locked into proprietary format

### Integration Patterns
- **Primary knowledge store**: All research and insights live in Obsidian
- **Memory index**: Obsidian notes reference database IDs
- **Human review layer**: AI writes drafts, human refines in Obsidian
- **Audit log**: Decision trails documented as notes

### Limitations to Consider
- **Performance**: File I/O slower than databases for frequent access
- **Concurrency**: Multiple processes writing to same files
- **Query limitations**: Basic search vs. complex database queries
- **Scale**: Thousands of notes may become unwieldy

## Relevance to Desired Capabilities

### Direct Matches
- **Durable memory (beyond sessions)**: Requires persistent storage that survives crashes
- **Investigative note trails**: Needs structured logging of research steps
- **Explainable decisions**: Depends on traceable memory retrieval
- **Document synthesis into Obsidian**: Leverages Obsidian as output target

### Architectural Implications
1. **Multi-layer memory**: Short-term in Redis, long-term in Obsidian+PostgreSQL
2. **State persistence workflow**: Temporal for workflow state, databases for facts
3. **Crash recovery**: Checkpointing to resume interrupted research
4. **Memory consolidation**: Moving from working → episodic → semantic memory

## Recommendations for Python AI Assistant

### Starting Point (MVP)
- **Working memory**: Redis for fast, volatile state
- **Episodic memory**: PostgreSQL for structured logs
- **Semantic memory**: Obsidian for research outputs
- **State persistence**: Temporal for workflow durability

### Evolution Path
1. **Phase 1**: Redis + Obsidian (simple, human-centric)
2. **Phase 2**: Add PostgreSQL for structured logging
3. **Phase 3**: Add Temporal for workflow durability
4. **Phase 4**: Add vector store for semantic search

### Critical Questions
1. How much memory should be human-readable vs. machine-optimized?
2. What recovery guarantees are needed for research tasks?
3. How to handle memory conflicts (contradictory information)?
4. What privacy considerations for storing user interactions?

## Related Research
- [[Research – Durable AI Agents with Temporal (Python)]]
- [[Research – Task Queues & Workflow Systems (Celery, RQ, Temporal)]]
- [[Research – Async & Parallelism in Python AI Systems]]
- [[Research – LangChain vs Custom Agent Pipelines (Python)]]