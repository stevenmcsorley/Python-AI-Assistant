const express = require('express');
const {
  default: makeWASocket,
  DisconnectReason,
  fetchLatestBaileysVersion,
  useMultiFileAuthState,
} = require('@whiskeysockets/baileys');

const PORT = Number(process.env.PORT || 3000);
const ORCHESTRATOR_URL = 'http://orchestrator:8000/whatsapp';
const WEBHOOK_SECRET = process.env.WHATSAPP_WEBHOOK_SECRET || '';

let socket = null;
let isReady = false;
let lastConnectionState = 'disconnected';
let latestQr = null;

function logStatus(message, extra = {}) {
  const payload = { level: 'info', message, ...extra };
  console.log(JSON.stringify(payload));
}

function logError(message, extra = {}) {
  const payload = { level: 'error', message, ...extra };
  console.error(JSON.stringify(payload));
}

async function startSocket() {
  const { state, saveCreds } = await useMultiFileAuthState('./auth');
  const { version } = await fetchLatestBaileysVersion();

  socket = makeWASocket({
    version,
    auth: state,
    printQRInTerminal: true,
  });

  socket.ev.on('creds.update', saveCreds);

  socket.ev.on('connection.update', (update) => {
    const { connection, lastDisconnect, qr } = update;
    if (qr) {
      latestQr = qr;
      logStatus('qr updated');
    }
    if (connection) {
      lastConnectionState = connection;
      isReady = connection === 'open';
      logStatus('connection update', { connection });
    }
    if (connection === 'close') {
      const shouldReconnect =
        lastDisconnect &&
        lastDisconnect.error &&
        lastDisconnect.error.output &&
        lastDisconnect.error.output.statusCode !== DisconnectReason.loggedOut;
      logStatus('connection closed', {
        shouldReconnect,
        statusCode: lastDisconnect?.error?.output?.statusCode,
      });
      if (shouldReconnect) {
        startSocket().catch((err) => logError('reconnect failed', { error: err.message }));
      }
    }
  });

  socket.ev.on('messages.upsert', async (event) => {
    if (!event || !event.messages) return;
    for (const message of event.messages) {
      if (!message.message || message.key?.fromMe) continue;
      const from = message.key.remoteJid || '';
      const text = extractText(message.message);
      if (!text) continue;
      logStatus('inbound message', { from, text });
      try {
        const headers = { 'Content-Type': 'application/json' };
        if (WEBHOOK_SECRET) {
          headers['X-Webhook-Secret'] = WEBHOOK_SECRET;
        }
        await fetch(ORCHESTRATOR_URL, {
          method: 'POST',
          headers,
          body: JSON.stringify({ from, text }),
        });
      } catch (err) {
        logError('failed to forward inbound message', { error: err.message });
      }
    }
  });
}

function extractText(message) {
  if (message.conversation) return message.conversation;
  if (message.extendedTextMessage && message.extendedTextMessage.text) {
    return message.extendedTextMessage.text;
  }
  if (message.imageMessage && message.imageMessage.caption) {
    return message.imageMessage.caption;
  }
  if (message.videoMessage && message.videoMessage.caption) {
    return message.videoMessage.caption;
  }
  return '';
}

async function sendMessage(to, text) {
  if (!socket || !isReady) {
    throw new Error('whatsapp_not_ready');
  }
  const jid = to.includes('@s.whatsapp.net') ? to : `${to}@s.whatsapp.net`;
  await socket.sendMessage(jid, { text });
}

async function main() {
  await startSocket();

  const app = express();
  app.use(express.json());

  app.post('/send', async (req, res) => {
    const { to, text } = req.body || {};
    if (!to || !text) {
      return res.status(400).json({ ok: false, error: 'to_and_text_required' });
    }
    try {
      await sendMessage(String(to), String(text));
      logStatus('outbound message', { to, text });
      return res.json({ ok: true });
    } catch (err) {
      logError('send failed', { error: err.message, to });
      return res.status(503).json({ ok: false, error: err.message });
    }
  });

  app.get('/qr', (_req, res) => {
    if (isReady) {
      return res.json({ ok: true, status: 'connected', qr: null });
    }
    if (!latestQr) {
      return res.status(404).json({ ok: false, error: 'qr_unavailable' });
    }
    return res.json({ ok: true, status: lastConnectionState, qr: latestQr });
  });

  app.listen(PORT, () => {
    logStatus('baileys sidecar listening', { port: PORT });
  });
}

main().catch((err) => {
  logError('startup failure', { error: err.message });
  process.exit(1);
});
