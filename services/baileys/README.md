# Baileys WhatsApp Sidecar

A minimal WhatsApp Web bridge using Baileys. This service is a dumb transport:
- No database access
- No business logic
- No retries/queues

## Endpoints

- `POST /send`
  - Body: `{ "to": "<phone>", "text": "<message>" }`
  - Sends a WhatsApp message (best-effort)

## Inbound Messages

Inbound WhatsApp messages are forwarded to:

```
http://orchestrator:8000/whatsapp
```

Payload:

```json
{
  "from": "<phone>",
  "text": "<message text>"
}
```

## Auth State

Baileys auth state is persisted under `./auth/`.

## Run

```bash
npm install
npm start
```

Scan the QR code printed to the terminal to authenticate.
