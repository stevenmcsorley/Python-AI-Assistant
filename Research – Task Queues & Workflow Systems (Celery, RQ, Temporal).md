---
tags: [research, python, task-queues, workflow-systems, celery, rq, temporal, ai-agents]
created: 2026-01-30
updated: 2026-01-30
related:
  - "[[Research – Durable AI Agents with Temporal (Python)]]"
  - "[[Research – LangChain vs Custom Agent Pipelines (Python)]]"
  - "[[Desired Capabilities – Python AI Assistant]]"
---

# Research – Task Queues & Workflow Systems (Celery, RQ, Temporal)

*Comparison of Python task queue systems for long-running AI research workflows.*

## Core Distinction: Task Queues vs Workflow Engines

**Task Queues (Celery, RQ):**
- Execute individual, independent jobs
- Focus on job distribution and worker management
- Jobs are stateless units of work
- Good for: email sending, image processing, database updates

**Workflow Engines (Temporal):**
- Orchestrate multi-step processes with state
- Manage long-running workflows with dependencies
- Maintain workflow state across failures
- Good for: business processes, data pipelines, complex AI workflows

## Celery

**What it is:**
Mature, full-featured distributed task queue system for Python.

**Key Characteristics:**
- Multiple broker support (Redis, RabbitMQ, SQS)
- Built-in scheduling for periodic tasks
- Complex but flexible configuration
- Supports task prioritization via named queues
- Inter-language task support (tasks can come from non-Python systems)

**Failure Handling:**
- Configurable retry counts and intervals
- Exponential backoff support
- Self-retry capability within task code
- Reliability depends on broker choice (RabbitMQ offers better guarantees than Redis)

**State Persistence:**
- Tasks are stateless by default
- Results can be stored in various backends
- No built-in workflow state persistence

**Observability:**
- Flower monitoring tool available
- Complex setup but comprehensive monitoring
- Queue latency metrics important for scaling

**Operational Complexity:**
- **High learning curve** - complex configuration
- Requires separate broker service (RabbitMQ adds operational overhead)
- Multiple components to manage (broker, workers, monitoring)
- Containerization straightforward

**Suitability for AI Research Tasks:**
- **Good for:** Parallel job execution, scheduled research runs
- **Poor for:** Long-running multi-step workflows, stateful research processes
- **Breaks down:** When workflows need to survive worker crashes, maintain state between steps

## RQ (Redis Queue)

**What it is:**
Simple, lightweight task queue built on Redis.

**Key Characteristics:**
- Redis-only broker (simplifies infrastructure)
- Minimal API, low barrier to entry
- Python-only (no inter-language support)
- Priority queues via ordered queue consumption
- No built-in scheduler (requires separate package)

**Failure Handling:**
- Configurable retry policies
- Simpler than Celery's options
- Potential task loss if worker crashes after grabbing task
- Redis doesn't guarantee same durability as RabbitMQ

**State Persistence:**
- Tasks stateless
- Results stored in Redis
- No workflow state management

**Observability:**
- RQ dashboard available
- Simpler monitoring than Celery
- Less comprehensive metrics

**Operational Complexity:**
- **Low learning curve** - simple documentation
- Only requires Redis (often already in infrastructure)
- Easy deployment and maintenance
- Containerization straightforward

**Suitability for AI Research Tasks:**
- **Good for:** Simple background jobs, quick prototyping
- **Poor for:** Complex workflows, high-reliability requirements
- **Breaks down:** At scale (benchmarks show Celery 4x faster for 20k jobs), when Redis durability isn't enough

## Temporal

**What it is:**
Workflow engine for building durable, reliable applications.

**Key Characteristics:**
- Workflow orchestration, not just task queuing
- Automatic state persistence and recovery
- Built for long-running processes (days, months)
- Activities (tasks) + Workflows (orchestration)

**Failure Handling:**
- **Automatic retries** for Activities
- Workflows survive server crashes
- No data loss on failures
- Built-in exponential backoff

**State Persistence:**
- **Automatic workflow state persistence**
- Checkpoints after each step
- Resume from last checkpoint after failures
- Strong durability guarantees

**Observability:**
- Workflow history visible
- Debugging capabilities built-in
- Temporal Web UI for monitoring
- Better visibility into multi-step processes

**Operational Complexity:**
- **Moderate learning curve** - different paradigm
- Requires Temporal cluster (managed or self-hosted)
- More infrastructure than simple task queues
- Better for production reliability

**Suitability for AI Research Tasks:**
- **Excellent for:** Long-running research workflows, multi-step reasoning pipelines
- **Excellent for:** Failure recovery and resumable tasks
- **Poor for:** Simple one-off jobs (overkill)
- **Breaks down:** When you only need simple task queuing

## Comparison to Desired Capabilities

| Capability | Celery | RQ | Temporal |
|------------|--------|----|----------|
| Long-running & resumable tasks | ❌ No workflow state | ❌ No workflow state | ✅ **Excellent** |
| Background research jobs | ✅ Good | ✅ Good | ✅ Good (but heavier) |
| Parallel web search | ✅ Good | ✅ Good | ✅ Good |
| Multi-step reasoning pipelines | ❌ No orchestration | ❌ No orchestration | ✅ **Excellent** |
| Document synthesis workflows | ⚠️ Manual coordination | ⚠️ Manual coordination | ✅ **Good** |
| Investigative note trails | ❌ No state persistence | ❌ No state persistence | ✅ **Good** (with custom logic) |
| Durable memory | ❌ Stateless | ❌ Stateless | ✅ **Workflow state only** |
| Failure recovery & retries | ✅ Configurable | ✅ Basic | ✅ **Automatic & robust** |
| Safe background autonomy | ⚠️ Depends on implementation | ⚠️ Depends on implementation | ✅ **Built-in reliability** |

## Operational Trade-offs

**Infrastructure Cost:**
- **RQ:** Lowest (just Redis)
- **Celery:** Medium (Redis/RabbitMQ + monitoring)
- **Temporal:** Highest (cluster + persistence)

**Learning Curve:**
- **RQ:** Lowest
- **Celery:** Highest (complex configuration)
- **Temporal:** Medium (different paradigm)

**Production Reliability:**
- **Temporal:** Highest (built for durability)
- **Celery (with RabbitMQ):** High
- **RQ:** Medium (Redis limitations)
- **Celery (with Redis):** Medium

## Recommendation for AI Research System

**For [[Desired Capabilities – Python AI Assistant]]:**

1. **Temporal** is the best fit for core workflow requirements:
   - Long-running, resumable tasks ✅
   - Multi-step reasoning pipelines ✅
   - Automatic failure recovery ✅
   - State persistence across crashes ✅

2. **Consider hybrid approach:**
   - Temporal for orchestration of complex workflows
   - RQ/Celery for simple background jobs within workflows
   - Temporal Activities can call RQ/Celery tasks

3. **If starting simple:**
   - Begin with RQ for prototyping
   - Migrate to Temporal when workflow complexity increases
   - Avoid Celery unless you need specific features (inter-language, RabbitMQ)

**Key Insight:** Task queues solve job distribution; workflow engines solve process orchestration. Your desired capabilities need **both**, which suggests Temporal (or similar) for orchestration, with simple task execution within it.

## Related Research

- [[Research – Durable AI Agents with Temporal (Python)]]
- [[Research – LangChain vs Custom Agent Pipelines (Python)]]
- [[System Definition – Python AI Assistant]]

## Next Steps

1. Prototype a simple research workflow with Temporal
2. Compare with custom state management on RQ
3. Evaluate operational overhead vs capability benefits
4. Design failure recovery patterns specific to AI research tasks
