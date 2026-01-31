# Python AI Assistant – Repository Skeleton

This repository is a build-ready skeleton based on the PRD and Runtime Architecture. It contains Docker Compose layout, service placeholders, and environment configuration. No business logic is implemented yet.

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

## Notes
- Orchestrator and worker are placeholders and simply stay alive.
- Obsidian vault is mounted at `/obsidian` inside containers.
- Set provider credentials and scheduling in `.env`.

## Baileys WhatsApp Sidecar (Optional)

Baileys is a standalone WhatsApp Web bridge. It is not required for the system to run.

**Warning:** Baileys is non-contractual and may break.

### Start Baileys
- Start only the sidecar: `docker compose up -d baileys`

### QR Auth
- On first start, a QR code is printed to the Baileys container logs.
- Scan the QR code with WhatsApp on your phone to authenticate.
- Auth state is persisted in the `baileys_auth` volume.
