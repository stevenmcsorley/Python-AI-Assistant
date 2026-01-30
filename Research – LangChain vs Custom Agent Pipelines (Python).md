---
created: 2026-01-30
tags: [research, ai-agents, python, langchain, frameworks]
related:
  - "[[Desired Capabilities – Python AI Assistant]]"
  - "[[System Definition – Python AI Assistant]]"
---
# Research – LangChain vs Custom Agent Pipelines (Python)

*Based on analysis of Python AI agent frameworks and industry patterns.*

## What LangChain Abstracts Well

**Tool Integration & Standardization**
- Pre-built connectors for hundreds of APIs, databases, and services
- Consistent patterns for defining tools and their execution
- Built-in support for major LLM providers (OpenAI, Anthropic, etc.)

**Agent Patterns & Orchestration**
- Ready-made agent types (ReAct, conversational, planning)
- Built-in memory systems (conversation buffer, vector stores)
- LangGraph for stateful, long-running workflows

**Development Velocity**
- Quick prototyping with minimal boilerplate
- Extensive documentation and community examples
- LangSmith for debugging and observability

## What LangChain Makes Harder

**Complexity & Bloat**
- Large dependency footprint (100+ dependencies)
- Deep abstraction layers that obscure what's happening
- Performance overhead from multiple layers of indirection

**Customization Constraints**
- Difficult to deviate from LangChain's mental models
- Tight coupling between components limits architectural flexibility
- Memory and state management can be opaque

**Production Concerns**
- Version compatibility issues with rapid releases
- Limited control over error handling and retry logic
- Observability requires LangSmith (proprietary service)

## State and Memory Handling

**LangChain's Approach**
- Built-in memory classes (ConversationBufferMemory, VectorStoreRetrieverMemory)
- State managed through LangGraph for complex workflows
- Memory can be persisted to various backends

**Limitations for Long-Running Tasks**
- Memory systems designed for conversational contexts
- Limited support for resumable workflows after crashes
- State serialization can be complex for custom objects

## Suitability for Long-Running Research Tasks

**Strengths**
- LangGraph provides durable execution for stateful agents
- Built-in human-in-the-loop capabilities
- Good for structured research workflows with clear steps

**Weaknesses**
- Not optimized for days/weeks-long background jobs
- Memory systems may not scale for large research contexts
- Limited support for parallel web search + page reading at scale

## When Custom Pipelines Are Preferable

**Research-Heavy Systems**
- When you need fine-grained control over web search, parsing, and synthesis
- For investigative note trails that require custom linking and organization
- When research quality and depth outweigh development speed

**Production Requirements**
- Need for specific reliability patterns (circuit breakers, backoff strategies)
- Integration with existing infrastructure and monitoring systems
- Performance optimization requirements

**Architectural Control**
- When you want to own the entire stack for maintainability
- Need to implement custom failure recovery and retry logic
- Desire for explainable decisions with full transparency

## Relevance to Our Desired Capabilities

**Good Match for LangChain**
- Multi-step reasoning pipelines (LangGraph)
- Basic tool orchestration
- Quick prototyping of agent patterns

**Better Served by Custom**
- **Long-running & resumable tasks** – need durable execution beyond LangGraph
- **Background research jobs** – requires custom scheduling and monitoring
- **Parallel web search + page reading** – need fine-grained control over concurrency and parsing
- **Document synthesis into Obsidian** – requires direct file system integration
- **Investigative note trails** – custom linking and metadata management
- **Durable memory (beyond sessions)** – need persistent knowledge graphs
- **Explainable decisions** – full transparency into reasoning process
- **Safe background autonomy** – custom safety layers and monitoring
- **Failure recovery & retries** – need control over retry logic and state persistence

## Decision Framework

**Choose LangChain when:**
- You need to prototype quickly
- Standard tool integrations cover your needs
- You're building conversational or short-lived agents
- You can accept vendor lock-in with LangSmith

**Choose Custom when:**
- Research quality and control are paramount
- You need days/weeks-long background processing
- Direct Obsidian integration is critical
- Full transparency and explainability are required
- You want to own the entire stack for long-term maintenance

## Hybrid Approach Possibility

Consider using LangChain/LangGraph for agent orchestration while implementing:
- Custom tools for web research and document processing
- Direct Obsidian integration for note synthesis
- Custom memory layer for durable knowledge
- Specialized failure handling for long-running tasks

---

**Next Steps:**
1. Research [[Temporal]] as an alternative orchestration layer
2. Define minimum viable custom pipeline architecture
3. Prototype parallel web research system
4. Design Obsidian integration patterns