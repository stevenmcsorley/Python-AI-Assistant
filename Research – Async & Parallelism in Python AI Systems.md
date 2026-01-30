---
title: Research – Async & Parallelism in Python AI Systems
date: 2026-01-30
tags: [research, python, concurrency, async, parallelism, ai-systems]
related:
  - "[[Desired Capabilities – Python AI Assistant]]"
  - "[[System Definition – Python AI Assistant]]"
---
# Async & Parallelism in Python AI Systems

## Core Distinctions

### Asyncio
**Strengths:**
- Single-threaded event loop for I/O-bound operations
- Cooperative multitasking (programmer controls context switches with `await`)
- Excellent for network operations (web scraping, API calls, LLM requests)
- Low memory overhead compared to threads/processes
- Built into Python standard library (3.4+)

**Limitations:**
- Not suitable for CPU-bound tasks (still subject to GIL)
- Requires async/await syntax throughout call chain
- Debugging can be challenging (stack traces less clear)
- Not all libraries support async natively

### Multiprocessing vs Multithreading
**Multiprocessing:**
- True parallelism using multiple CPU cores
- Each process has its own Python interpreter and memory space
- Bypasses GIL completely
- Higher memory overhead and IPC (inter-process communication) cost
- Best for CPU-intensive AI workloads (model inference, data processing)

**Multithreading:**
- Multiple threads within same process
- Still subject to GIL (only one thread executes Python bytecode at a time)
- Good for I/O-bound tasks when libraries don't support async
- Shared memory (easier data sharing but requires synchronization)
- Lower overhead than multiprocessing

## GIL Implications for AI Workloads

The Global Interpreter Lock (GIL) prevents true parallelism in Python threads for CPU-bound operations. This affects AI systems in specific ways:

- **LLM calls**: Mostly I/O-bound (network requests), so GIL less relevant
- **Tool execution**: Mixed - some tools CPU-bound (data processing), some I/O-bound
- **Web research**: Primarily I/O-bound, good candidate for asyncio
- **Document synthesis**: Could be CPU-bound for large documents

**Workarounds:**
1. Use multiprocessing for CPU-heavy components
2. Use asyncio for I/O-heavy components
3. Consider PyPy or other Python implementations without GIL
4. Offload to external services (microservices)

## When Ray is Appropriate

Ray is a distributed computing framework that becomes relevant when:
- You need to scale beyond a single machine
- Complex task dependencies and scheduling
- Stateful actors with communication patterns
- Machine learning workloads with large datasets
- When you need both task parallelism and data parallelism

For our Python AI assistant, Ray might be overkill unless we anticipate:
- Distributed web research across many nodes
- Parallel model inference at scale
- Complex workflow orchestration across clusters

## Common Failure Modes

### Deadlocks
- **Asyncio**: Task dependencies creating circular waits
- **Threading**: Traditional mutex deadlocks
- **Multiprocessing**: IPC deadlocks with queues/pipes

### Resource Leaks
- Unclosed connections (aiohttp sessions)
- Unreleased file descriptors
- Memory leaks in long-running processes
- Zombie processes not properly joined

### Starvation
- Poorly designed task scheduling
- Unbounded queue growth
- Priority inversion
- I/O-bound tasks blocking CPU-bound ones

## Debugging & Observability Challenges

### Asyncio
- Stack traces can be confusing with event loop
- Hard to debug timing-related bugs
- Task cancellation propagation
- Exception handling across tasks

### Multiprocessing
- Separate memory spaces make debugging harder
- IPC issues (pickling errors, queue timeouts)
- Process spawning overhead and state
- Log aggregation across processes

### Threading
- Race conditions hard to reproduce
- GIL-related performance issues
- Thread-local data management

## Suitability for AI Assistant Components

### Web Research
**Best:** Asyncio with aiohttp
- Highly I/O-bound (network latency dominates)
- Can handle hundreds of concurrent requests
- Built-in rate limiting and retries
- Connection pooling reduces overhead

### Tool Execution
**Mixed approach:**
- I/O-bound tools (APIs, databases): Asyncio
- CPU-bound tools (data processing): Multiprocessing pool
- Mixed tools: Thread pool executor for compatibility

### LLM Calls
**Best:** Asyncio
- Network-bound (API calls to OpenAI/Anthropic/etc.)
- Can batch multiple requests
- Natural fit for async/await pattern
- Easy to implement retry logic

### Document Synthesis
**Best:** Multiprocessing
- CPU-intensive (parsing, analysis, formatting)
- Memory isolation prevents contamination
- Can process multiple documents in parallel

## Recommendations for Our System

Given the [[Desired Capabilities – Python AI Assistant]], we should adopt a **hybrid architecture**:

1. **Main event loop**: Asyncio for coordination
2. **Web research**: Asyncio with aiohttp for parallel fetching
3. **LLM operations**: Asyncio for API calls
4. **CPU-heavy processing**: Multiprocessing pool offloaded from main loop
5. **Tool execution**: Thread pool for synchronous libraries, asyncio for async ones

**Critical considerations:**
- State management across concurrency boundaries
- Error propagation and recovery
- Resource limits and backpressure
- Observability across all concurrency models

## Integration with Workflow Systems

If we choose [[Research – Task Queues & Workflow Systems (Celery, RQ, Temporal)|Temporal]] or similar:
- Temporal workers can use asyncio internally
- Activities can be CPU-bound (multiprocessing) or I/O-bound (asyncio)
- Workflow orchestration handles concurrency at higher level
- Failure recovery must consider concurrency state

## Next Steps

1. Prototype the hybrid architecture
2. Benchmark different concurrency patterns for our specific workloads
3. Design error handling that works across concurrency boundaries
4. Implement observability that tracks tasks across threads/processes

---
*Last updated: 2026-01-30*
