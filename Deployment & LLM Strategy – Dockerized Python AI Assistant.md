---
title: Deployment & LLM Strategy – Dockerized Python AI Assistant
tags: [deployment, llm, docker, architecture, strategy]
created: 2026-01-30
updated: 2026-01-30
---

## 1. Containerized Deployment Model

The assistant must be fully containerized using Docker to ensure consistent runtime behavior across different environments.

- **Docker Compose** is the primary orchestration mechanism for local development, testing, and production deployment.
- All core services (assistant runtime, workers, databases, caches) must be runnable via a single `docker-compose.yml` file.
- The system must be deployable on:
  - **Local machines** (development laptops, personal computers)
  - **Home servers** (Raspberry Pi, NAS devices, home lab servers)
  - **Cloud VMs** (AWS EC2, Google Compute Engine, DigitalOcean droplets)
- No component may assume a fixed host environment or specific hardware capabilities.
- Container images must be minimal and follow security best practices (non-root users, minimal base images).

## 2. Service Composition

The Docker Compose setup includes:

- **Core assistant runtime** (Python application) – The main orchestrator and API server
- **Background workers** – Scalable independently for parallel task processing
- **Database service** – PostgreSQL with pgvector extension for structured data + embeddings
- **Cache / working memory service** – Redis for session state and temporary data
- **Optional services** enabled via Docker Compose profiles:
  - Vector database (Qdrant, Weaviate) for advanced semantic search
  - Monitoring stack (Prometheus, Grafana) for production observability
  - Message queue (RabbitMQ) for advanced workflow patterns
- **Obsidian vault** mounted as a Docker volume, never baked into container images
  - This ensures the user's knowledge base remains separate from the application
  - Allows the user to edit notes while the assistant is running
  - Supports multiple vaults or vault switching via configuration

## 3. LLM Provider Strategy (Primary and Fallbacks)

### Primary Provider: DeepSeek API
- Used for reasoning, long-context analysis, and interactive chat
- Chosen for:
  - **Cost efficiency** – Competitive pricing compared to OpenAI, Anthropic
  - **Speed** – Fast response times for interactive use
  - **Reasoning capabilities** – Strong performance on planning and synthesis tasks
  - **Large context windows** – Support for 128K+ tokens for comprehensive analysis

### Multi-Provider Architecture
- The system must support multiple LLM backends via a unified interface
- Provider selection is configurable at runtime via environment variables
- Each provider implements a common interface for:
  - Chat completion
  - Embedding generation
  - Function/tool calling

### Fallback and Optional Providers
- **Ollama** (local models) – For offline operation or privacy-sensitive tasks
  - Llama 3.1 70B for reasoning
  - Mistral 7B for faster, simpler tasks
  - Custom fine-tuned models for specific domains
- **Smaller HuggingFace models** – For constrained scenarios:
  - Zephyr 7B for chat
  - BGE embeddings for semantic search
  - Specialized models for classification and extraction
- **Other cloud providers** (OpenAI, Anthropic, Google) – As backup or for specific capabilities

## 4. Model Capability Classes

The system routes tasks to different models based on capability requirements and cost:

### Reasoning Models
- **Purpose:** Planning, synthesis, decision-making, complex analysis
- **Examples:** DeepSeek-R1, Llama 3.1 70B
- **Use cases:**
  - Creating multi-step research plans
  - Synthesizing information from multiple sources
  - Making decisions about next actions
  - Evaluating options and trade-offs

### Chat Models
- **Purpose:** Interactive conversation, clarification, simple Q&A
- **Examples:** DeepSeek-Chat, Zephyr 7B
- **Use cases:**
  - WhatsApp message responses
  - Clarifying user intent
  - Simple information retrieval
  - Casual conversation

### Utility Models
- **Purpose:** Classification, extraction, summarization, embeddings
- **Examples:** Specialized small models, embedding models
- **Use cases:**
  - Classifying email content
  - Extracting dates and deadlines
  - Summarizing articles
  - Generating vector embeddings

## 5. Cost, Performance, and Reliability Considerations

### Default Behavior Favors:
- **Low cost** – Use cheaper models when quality difference is minimal
- **Predictable latency** – Prefer models with consistent response times
- **Large context windows** – Essential for analyzing documents and long conversations

### Task-Based Model Selection
- **Background research tasks** may use slower or cheaper models
- **Interactive tasks** (WhatsApp responses) use faster, higher-quality models
- **Critical reasoning tasks** (planning, synthesis) use the best available reasoning models
- **Fallback logic** automatically switches providers if:
  - Primary provider is unavailable
  - Rate limits are exceeded
  - Costs exceed configured thresholds

### Graceful Degradation
- If no LLM provider is available, the system continues operating with:
  - Cached responses where possible
  - Simplified workflows that don't require LLM calls
  - Clear error messages to the user about capabilities
- Background jobs queue until LLM services are restored

## 6. Configuration and Secrets Management

- **All provider configuration** is supplied via environment variables
  - `DEEPSEEK_API_KEY`
  - `OLLAMA_BASE_URL`
  - `OPENAI_API_KEY` (optional)
- **No provider credentials** are hard-coded in source code or Docker images
- **Docker Compose files** define sensible defaults but allow overrides:
  - `.env` file for local development
  - Docker secrets for production deployment
  - Environment-specific compose files (docker-compose.prod.yml)
- **Model selection** is configurable per:
  - Task type
  - Time of day (cheaper models overnight)
  - User preference
  - Cost budget

## 7. Non-Goals

- **No hard dependency** on a single LLM vendor or provider
- **No SaaS-only deployment requirement** – Must run fully locally
- **No assumption of GPU availability** – CPU-only operation must be possible
- **No vendor lock-in** – Switching providers should not require architectural changes
- **No mandatory internet connectivity** – Local models provide offline capability

## Implementation Guidelines

### Docker Compose Structure
```yaml
# docker-compose.yml
services:
  assistant:
    build: ./assistant
    environment:
      - DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}
      - DATABASE_URL=postgresql://postgres:password@db:5432/assistant
    volumes:
      - ./obsidian-vault:/app/obsidian
    depends_on:
      - db
      - redis

  worker:
    build: ./assistant
    command: python -m worker
    # ... similar configuration

  db:
    image: pgvector/pgvector:pg16
    environment:
      - POSTGRES_PASSWORD=password
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data

volumes:
  postgres_data:
  redis_data:
```

### LLM Provider Interface
```python
# Abstract interface for all LLM providers
class LLMProvider:
    async def chat_completion(self, messages, tools=None):
        pass
    
    async def embeddings(self, texts):
        pass
    
    async def function_call(self, messages, functions):
        pass

# Concrete implementations
class DeepSeekProvider(LLMProvider):
    # Implementation using DeepSeek API

class OllamaProvider(LLMProvider):
    # Implementation using local Ollama

class HuggingFaceProvider(LLMProvider):
    # Implementation using HuggingFace models
```

### Configuration Example
```bash
# .env file
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxx
OLLAMA_BASE_URL=http://localhost:11434
PRIMARY_PROVIDER=deepseek
FALLBACK_PROVIDER=ollama
EMBEDDING_MODEL=bge-small-en
MAX_MONTHLY_COST=50.00  # USD
```

## Connection to Other Documents

This deployment strategy enables the capabilities defined in:
- [[Long-Running Assistant – Background Operation & WhatsApp Interface]] – Continuous operation across environments
- [[Assistant Product Intent – Personal Planning & Support]] – Reliable access to planning capabilities
- [[Runtime Architecture – Python AI Assistant]] – Containerized service architecture
- [[System Invariants – Python AI Assistant]] – Maintains safety and transparency

## Next Steps

1. Create Dockerfile for the Python assistant
2. Set up Docker Compose with PostgreSQL + pgvector
3. Implement the multi-provider LLM interface
4. Configure environment-based secrets management
5. Test deployment on local machine and cloud VM