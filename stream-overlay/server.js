/**
 * stream-overlay/server.js
 *
 * POST /event                        — bot pushes any event
 * POST /toggle/:source               — Stream Deck toggles notescam / livesplit
 * GET  /layout                       — current layout state
 * GET  /test/:type                   — dev helpers
 *
 * Layout state drives both:
 *   1. OBS scene visibility (via obs-websocket)
 *   2. WebSocket broadcast so HTML overlays reflow animated positions
 */

const express = require('express');
const http    = require('http');
const { WebSocketServer } = require('ws');
const path    = require('path');

// obs-websocket-js v5 (npm install obs-websocket-js)
let OBSWebSocket;
try { ({ default: OBSWebSocket } = require('obs-websocket-js')); } catch (_) {}

const app    = express();
const server = http.createServer(app);
const wss    = new WebSocketServer({ server });
const PORT   = 3000;

// ── Layout state (single source of truth) ────────────────
const layout = { notescam: false, livesplit: false };

// ── OBS connection ────────────────────────────────────────
let obs = null;
async function connectOBS() {
  if (!OBSWebSocket) { console.warn('[obs] obs-websocket-js not installed, skipping'); return; }
  obs = new OBSWebSocket();
  try {
    await obs.connect('ws://localhost:4455', process.env.OBS_PW);
    console.log('[obs] connected');
  } catch (e) {
    console.warn('[obs] could not connect:', e.message);
    obs = null;
  }
}

// OBS scene names for the two toggleable sources
// Set these to whatever your OBS scenes are actually called
const OBS_SCENES = {
  notescam:  'Notescam Scene',
  livesplit: 'Livesplit Scene',
};

async function setOBSSceneVisible(sceneName, visible) {
  if (!obs) return;
  try {
    await obs.call('SetSceneItemEnabled', {
      sceneName: 'Main',        // your parent scene name
      sceneItemId: sceneName,   // if using nested scenes; adjust as needed
      sceneItemEnabled: visible,
    });
  } catch (e) {
    console.warn('[obs] setVisible failed:', e.message);
  }
}

// ── Static + routes ───────────────────────────────────────
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const overlayDir = path.join(__dirname, 'overlays');
['webcam','background','alerts','chat','hud','notescam','livesplit', 'border-4x3', 'border-16x9'].forEach(name => {
  app.get(`/${name}`, (_req, res) =>
    res.sendFile(path.join(overlayDir, `${name}.html`))
  );
});
app.get('/', (_req, res) => res.sendFile(path.join(overlayDir, 'index.html')));

// ── WebSocket ─────────────────────────────────────────────
function broadcast(payload) {
  const msg = JSON.stringify(payload);
  wss.clients.forEach(c => { if (c.readyState === 1) c.send(msg); });
}

wss.on('connection', ws => {
  // Send current layout state immediately on connect so overlays initialise correctly
  ws.send(JSON.stringify({ type: 'connected' }));
  ws.send(JSON.stringify({ type: 'layout', ...layout }));
});

// ── /event ────────────────────────────────────────────────
app.post('/event', (req, res) => {
  const event = req.body;
  if (!event?.type) return res.status(400).json({ error: 'Missing type' });
  broadcast(event);
  res.json({ ok: true });
});

// ── /toggle/:source  (Stream Deck binds here) ─────────────
app.post('/toggle/:source', async (req, res) => {
  const src = req.params.source;
  if (!(src in layout)) return res.status(404).json({ error: 'Unknown source' });

  layout[src] = !layout[src];
  broadcast({ type: 'layout', ...layout });
  await setOBSSceneVisible(OBS_SCENES[src], layout[src]);

  console.log(`[layout] ${src} → ${layout[src]}`);
  res.json({ ok: true, layout });
});

// Force-set rather than toggle (useful for Stream Deck "on release" actions)
app.post('/set/:source/:value', async (req, res) => {
  const src = req.params.source;
  const val = req.params.value === 'true';
  if (!(src in layout)) return res.status(404).json({ error: 'Unknown source' });

  layout[src] = val;
  broadcast({ type: 'layout', ...layout });
  await setOBSSceneVisible(OBS_SCENES[src], val);
  res.json({ ok: true, layout });
});

app.get('/layout', (_req, res) => res.json(layout));

// ── LiveSplit Server proxy ────────────────────────────────
// Bridges the browser overlay to LiveSplit's raw TCP server.
// Enable "LiveSplit Server" component in your LiveSplit layout.
const net = require('net');
const LS_PORT = 16834;

app.get('/livesplit', (_req, res) => {
  const client = new net.Socket();
  let buf = '';
  const results = {};
  const TIMEOUT = 800;

  client.setTimeout(TIMEOUT);
  client.connect(LS_PORT, '127.0.0.1', () => {
    // Request current time and layout dimensions
    client.write('getcurrenttime\r\n');
    client.write('getlayoutwidth\r\n');
    client.write('getlayoutheight\r\n');
  });

  client.on('data', data => { buf += data.toString(); });

  function finish() {
    client.destroy();
    const lines = buf.split('\r\n').filter(Boolean);
    results.time = lines[0] || null;
    const w = parseFloat(lines[1]);
    const h = parseFloat(lines[2]);
    if (w && h) results.aspect = w / h;
    res.json(results);
  }

  client.on('timeout', finish);
  client.on('close',   () => { if (!res.headersSent) finish(); });
  client.on('error',   () => { if (!res.headersSent) res.json({}); });
});

// ── Dev helpers ───────────────────────────────────────────
app.get('/test/:type', (req, res) => {
  const demos = {
    follow:  { type: 'follow',  user: 'TestViewer' },
    sub:     { type: 'sub',     user: 'TestViewer', months: 1 },
    resub:   { type: 'sub',     user: 'OldFan',     months: 7 },
    pokemon: { type: 'pokemon', dex: Math.floor(Math.random()*1025)+1 },
    spin:    { type: 'spin' },
    raid:    { type: 'raid',    user: 'BigStreamer', viewers: 42 },
    layout_notescam:  { type: 'layout', notescam: true,  livesplit: false },
    layout_livesplit: { type: 'layout', notescam: false, livesplit: true  },
    layout_both:      { type: 'layout', notescam: true,  livesplit: true  },
    layout_none:      { type: 'layout', notescam: false, livesplit: false },
  };
  const event = demos[req.params.type] || { type: req.params.type };
  if (req.params.type.startsWith('layout')) Object.assign(layout, event);
  broadcast(event);
  res.json({ ok: true, fired: event });
});

// ── Start ─────────────────────────────────────────────────
server.listen(PORT, async () => {
  await connectOBS();
  console.log(`\n🎮 Stream Overlay Server  http://localhost:${PORT}/`);
  console.log(`   Overlays: /webcam /background /alerts /chat /hud /notescam /livesplit`);
  console.log(`   Toggle:   POST /toggle/notescam   POST /toggle/livesplit`);
  console.log(`   Force:    POST /set/notescam/true  POST /set/livesplit/false\n`);
});