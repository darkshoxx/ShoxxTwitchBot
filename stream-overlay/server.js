/**
 * stream-overlay/server.js
 * Local asset server for darkshoxx stream overlays.
 * Serves static HTML/CSS/JS pages as OBS browser sources,
 * and provides a WebSocket event bus so the Python bot can
 * push alerts (follows, subs, pokemon events, etc.) in real-time.
 *
 * Usage:
 *   node server.js
 *
 * Python bot fires events via HTTP POST to /event:
 *   POST /event  { "type": "follow", "user": "someone" }
 *   POST /event  { "type": "sub",    "user": "someone", "months": 3 }
 *   POST /event  { "type": "pokemon","dex": 25 }
 *   POST /event  { "type": "spin" }
 */

const express    = require('express');
const http       = require('http');
const { WebSocketServer } = require('ws');
const path       = require('path');

const app    = express();
const server = http.createServer(app);
const wss    = new WebSocketServer({ server });

const PORT = 3000;

// ── Static files ─────────────────────────────────────────
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

// ── Overlay page routes ───────────────────────────────────
const overlayDir = path.join(__dirname, 'overlays');
const overlays = ['webcam', 'background', 'alerts', 'chat', 'hud', 'border-4x3', 'border-16x9'];
overlays.forEach(name => {
  app.get(`/${name}`, (_req, res) =>
    res.sendFile(path.join(overlayDir, `${name}.html`))
  );
});

app.get('/', (_req, res) =>
  res.sendFile(path.join(overlayDir, 'index.html'))
);

// ── WebSocket: broadcast to all connected overlay pages ───
function broadcast(payload) {
  const msg = JSON.stringify(payload);
  wss.clients.forEach(client => {
    if (client.readyState === 1) client.send(msg);
  });
}

wss.on('connection', ws => {
  ws.send(JSON.stringify({ type: 'connected' }));
});

// ── Event endpoint (called by Python bot) ────────────────
app.post('/event', (req, res) => {
  const event = req.body;
  if (!event || !event.type) {
    return res.status(400).json({ error: 'Missing event type' });
  }
  broadcast(event);
  res.json({ ok: true, broadcasted: event });
});

// ── Dev helper: fire a test event from browser ───────────
app.get('/test/:type', (req, res) => {
  const demos = {
    follow:  { type: 'follow',  user: 'TestViewer' },
    sub:     { type: 'sub',     user: 'TestViewer', months: 1 },
    resub:   { type: 'sub',     user: 'OldFan',     months: 7 },
    pokemon: { type: 'pokemon', dex: Math.floor(Math.random()*1025)+1 },
    spin:    { type: 'spin' },
    raid:    { type: 'raid',    user: 'BigStreamer', viewers: 42 },
  };
  const event = demos[req.params.type] || { type: req.params.type };
  broadcast(event);
  res.json({ ok: true, fired: event });
});

server.listen(PORT, () => {
  console.log(`\n🎮 Stream Overlay Server running`);
  console.log(`   Hub:        http://localhost:${PORT}/`);
  console.log(`   Webcam:     http://localhost:${PORT}/webcam`);
  console.log(`   Background: http://localhost:${PORT}/background`);
  console.log(`   Alerts:     http://localhost:${PORT}/alerts`);
  console.log(`   Chat:       http://localhost:${PORT}/chat`);
  console.log(`   HUD:        http://localhost:${PORT}/hud`);
  console.log(`   16x9:       http://localhost:${PORT}/border-16x9`);
  console.log(`   4x3:        http://localhost:${PORT}/border-4x3`);
  console.log(`\n   POST /event  to push alerts from the bot`);
  console.log(`   GET  /test/follow|sub|pokemon|spin|raid  for dev\n`);
});