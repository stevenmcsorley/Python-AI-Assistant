# Python AI Assistant

This repository implements a long-running, human-in-the-loop AI assistant. It runs via Docker Compose with an orchestrator (planning/control) and worker (execution/delivery), and produces Obsidian draft notes as outputs.

## Layout
- `docker-compose.yml` – service topology with profiles
- `.env.example` – environment variable template
- `services/assistant/` – shared image for orchestrator and worker
- `monitoring/` – Prometheus config placeholder
- `obsidian-vault/` – host-mounted vault directory

## Profiles
- `local` – Temporal + monitoring enabled for local dev
- `prod` – Temporal + monitoring + optional vector DB
- `offline` – Ollama enabled for local/offline LLM use

## Example Commands
- Base services only: `docker compose up -d`
- Run migrations only: `docker compose up migrate`
- Local with Temporal + monitoring: `docker compose --profile local up -d`
- Production-like (Temporal + Qdrant + monitoring): `docker compose --profile prod up -d`
- Offline mode (Ollama): `docker compose --profile offline up -d`

## Production Startup Order
1. `docker compose up -d postgres migrate`
2. `docker compose up -d orchestrator worker`
3. Optional: `docker compose up -d baileys`

## How to Use This App (Quick Start)

### 1) Start core services
```
docker compose up -d postgres migrate orchestrator worker
```

### 2) (Optional) Start WhatsApp sidecar
```
docker compose up -d baileys
docker logs -f pythonaiassistan-baileys-1
```

Scan the QR code shown in the Baileys logs with WhatsApp to authenticate.

To enable real WhatsApp delivery, set:
```
WHATSAPP_PROVIDER=baileys
```

### 3) Configure DeepSeek (synthesize task)
Set in your environment or `.env`:
```
DEEPSEEK_API_BASE=https://api.deepseek.com
DEEPSEEK_API_KEY=your_key_here
```

### 4) Configure Brave Search (web research)
Set in your environment or `.env`:
```
BRAVE_SEARCH_API_KEY=your_key_here
BRAVE_SEARCH_API_BASE=https://api.search.brave.com/res/v1/web/search
BRAVE_SEARCH_MAX_RESULTS=5
```

### 5) Create a user and bind WhatsApp phone
```
INSERT INTO users (user_id, whatsapp_phone, display_name, timezone, status)
VALUES ('00000000-0000-0000-0000-000000000001', '+447900000000', 'Demo User', 'UTC', 'active');
```

### 6) Trigger ingest
```
curl -X POST http://localhost:8000/ingest
```

### 7) Approve via WhatsApp
You will receive a `suggestion_ready` message. Reply:
```
approve <suggestion_id>
```

To test without WhatsApp, you can call the inbound endpoint directly:
```
curl -X POST http://localhost:8000/whatsapp \
  -H "Content-Type: application/json" \
  -d '{"from":"+447900000000","text":"approve <suggestion_id>"}'
```

### 8) Result
Once approved:
- Workflow runs to completion
- Obsidian draft note is created under `obsidian-vault/`
- WhatsApp updates are queued/sent (stub by default)

### WhatsApp research command
From WhatsApp, you can start a research workflow directly:
```
research <topic>
```
This creates a research workflow, searches the web via Brave, reads source pages, and produces a synthesized Obsidian draft note.

## Notes
- Orchestrator runs ingestion/approval/planning; worker runs execution and delivery loops.
- Obsidian vault is mounted at `/obsidian` inside containers.
- Set provider credentials and scheduling in `.env`.

## Failure Behavior (Ops)
- If PostgreSQL is down: orchestrator/worker readiness stays false and no work is accepted.
- If Baileys is down: message delivery attempts fail and are audited; workflows are unaffected.
- If DeepSeek is down or misconfigured: synthesize tasks fail with explicit reasons; other tasks continue.

## Baileys WhatsApp Sidecar (Optional)

Baileys is a standalone WhatsApp Web bridge. It is not required for the system to run.

**Warning:** Baileys is non-contractual and may break.

### Start Baileys
- Start only the sidecar: `docker compose up -d baileys`

### QR Auth
- On first start, a QR code is printed to the Baileys container logs.
- Scan the QR code with WhatsApp on your phone to authenticate.
- Auth state is persisted in the `baileys_auth` volume.
