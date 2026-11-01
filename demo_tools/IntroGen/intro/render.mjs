#!/usr/bin/env node
/*
  Renders intro/intro.html frame by frame and encodes it to Intro.mp4 with audio.
*/
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { spawn, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..');
const OUT_DIR = path.join(HERE, 'out');

// ── args ────────────────────────────────────────────────────────────────
const argv = process.argv.slice(2);
const flag = name => argv.includes(`--${name}`);
const opt = (name, fallback) => {
  const i = argv.indexOf(`--${name}`);
  return i >= 0 && argv[i + 1] !== undefined ? argv[i + 1] : fallback;
};
const [WIDTH, HEIGHT] = opt('size', '1920x1080').split('x').map(Number);
const FPS = Number(opt('fps', '60'));
const OUT_FILE = path.resolve(opt('out', path.join(OUT_DIR, 'Intro.mp4')));

// ── static file server ──────────────────────────────────────────────────
const MOUNTS = [
  ['/vendor/three/', path.join(ROOT, 'node_modules', 'three')],
  ['/css/', path.join(ROOT, 'public', 'css')],
  ['/js/', path.join(ROOT, 'public', 'js')],
  ['/assets/', path.join(ROOT, 'public', 'assets')],
  ['/masks/', path.join(ROOT, 'public', 'masks')],
];
const MIME = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8', '.json': 'application/json', '.png': 'image/png', '.svg': 'image/svg+xml',
  '.woff2': 'font/woff2', '.woff': 'font/woff', '.mp4': 'video/mp4',
};

// ═══════════════════════════════════════════════════════════════════════
// Generate matching WAV audio for the MP4 export
// ═══════════════════════════════════════════════════════════════════════
function generateAudioTrack(outputPath, durationSec = 2.0, sampleRate = 44100) {
  const numSamples = Math.floor(sampleRate * durationSec);
  const buffer = Buffer.alloc(44 + numSamples * 2);

  buffer.write('RIFF', 0);
  buffer.writeUInt32LE(36 + numSamples * 2, 4);
  buffer.write('WAVE', 8);
  buffer.write('fmt ', 12);
  buffer.writeUInt32LE(16, 16);
  buffer.writeUInt16LE(1, 20);
  buffer.writeUInt16LE(1, 22);
  buffer.writeUInt32LE(sampleRate, 24);
  buffer.writeUInt32LE(sampleRate * 2, 28);
  buffer.writeUInt16LE(2, 32);
  buffer.writeUInt16LE(16, 34);
  buffer.write('data', 36);
  buffer.writeUInt32LE(numSamples * 2, 40);

  for (let i = 0; i < numSamples; i++) {
    const t = i / sampleRate;
    let sample = 0;

    if (t >= 0 && t < 0.7) {
      const freq = 80 + (600 - 80) * Math.min(1, t / 0.6);
      const env = Math.max(0, 1 - (t / 0.7)) * 0.25;
      const phase = (t * freq) % 1;
      const saw = (phase * 2 - 1);
      sample += saw * env;
    }

    const plingStart = 0.58;
    if (t >= plingStart && t < plingStart + 1.2) {
      const dt = t - plingStart;
      const plingFreq = 1046.50;
      const env = Math.exp(-dt * 4) * 0.3;
      const sine = Math.sin(2 * Math.PI * plingFreq * dt);
      sample += sine * env;
    }

    const intSample = Math.max(-1, Math.min(1, sample)) * 0x7FFF;
    buffer.writeInt16LE(intSample, 44 + i * 2);
  }

  fs.writeFileSync(outputPath, buffer);
}

function resolveRequest(pathname) {
  if (pathname === '/' || pathname === '/intro') return path.join(HERE, 'intro.html');
  for (const [prefix, dir] of MOUNTS) {
    if (!pathname.startsWith(prefix)) continue;
    const file = path.resolve(dir, decodeURIComponent(pathname.slice(prefix.length)));
    return file.startsWith(dir + path.sep) ? file : null;
  }
  return null;
}

function startServer(port) {
  const server = http.createServer((req, res) => {
    const file = resolveRequest(new URL(req.url, 'http://localhost').pathname);
    if (!file || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
      res.writeHead(404); res.end('Not found'); return;
    }
    res.writeHead(200, { 'Content-Type': MIME[path.extname(file).toLowerCase()] || 'application/octet-stream' });
    fs.createReadStream(file).pipe(res);
  });
  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(port, '127.0.0.1', () => resolve(server));
  });
}

function preflight() {
  const problems = [];
  if (!fs.existsSync(path.join(ROOT, 'node_modules', 'three', 'build', 'three.module.js')))
    problems.push('three.js not found. Run: npm i three@0.170.0');
  if (!fs.existsSync(path.join(ROOT, 'public', 'css', 'tokens.css')))
    problems.push('public/css/tokens.css not found');
  return problems;
}

// ── main ────────────────────────────────────────────────────────────────
async function main() {
  const problems = preflight();
  if (problems.length) { console.error(problems.join('\n')); process.exit(1); }

  if (flag('serve')) {
    const port = Number(opt('port', '3100'));
    await startServer(port);
    console.log(`Preview server running: http://localhost:${port}/intro`);
    return;
  }

  let puppeteer;
  try { puppeteer = (await import('puppeteer')).default; }
  catch { console.error('puppeteer not found. Run: npm i puppeteer'); process.exit(1); }

  fs.mkdirSync(OUT_DIR, { recursive: true });
  const server = await startServer(0);
  const base = `http://127.0.0.1:${server.address().port}`;

  const args = ['--ignore-gpu-blocklist', '--enable-unsafe-swiftshader', '--hide-scrollbars', '--force-color-profile=srgb'];
  if (flag('software')) args.push('--use-gl=angle', '--use-angle=swiftshader');
  const browser = await puppeteer.launch({
    headless: true, args, defaultViewport: { width: WIDTH, height: HEIGHT, deviceScaleFactor: 1 },
  });

  try {
    const page = await browser.newPage();
    page.on('console', m => { if (['error', 'warning'].includes(m.type())) console.log(`[page ${m.type()}] ${m.text()}`); });
    page.on('pageerror', e => console.error(`[page error] ${e.message}`));

    const mode = flag('sheet') ? '?sheet=1' : '?capture=1';
    await page.goto(`${base}/intro${mode}`, { waitUntil: 'load' });
    await page.waitForFunction('window.__ready === true || window.__error', { timeout: 120000 });
    const error = await page.evaluate('window.__error');
    if (error) throw new Error(`The page failed to start:\n${error}`);

    if (flag('sheet')) {
      const file = path.join(OUT_DIR, 'sheet.png');
      await page.screenshot({ path: file, type: 'png' });
      console.log(`Wrote ${file}`);
      return;
    }

    if (flag('frame')) {
      const t = Number(opt('frame', '1'));
      await page.evaluate(time => window.renderAt(time), t);
      const file = path.join(OUT_DIR, `frame-${t.toFixed(2)}.png`);
      await page.screenshot({ path: file, type: 'png' });
      console.log(`Wrote ${file}`);
      return;
    }

    if (spawnSync('ffmpeg', ['-version']).error) throw new Error('ffmpeg not found on PATH.');

    // 1. Evaluate duration and set up frame directory first
    const duration = await page.evaluate('window.__duration');
    const total = Math.round(duration * FPS);
    const framesDir = path.join(OUT_DIR, 'frames');
    fs.rmSync(framesDir, { recursive: true, force: true });
    fs.mkdirSync(framesDir, { recursive: true });

    const started = Date.now();
    for (let i = 0; i < total; i++) {
      await page.evaluate(t => window.renderAt(t), i / FPS);
      await page.screenshot({ path: path.join(framesDir, `frame_${String(i).padStart(4, '0')}.png`), type: 'png' });
      if (i % 5 === 4 || i === total - 1) {
        const elapsed = (Date.now() - started) / 1000;
        const eta = (elapsed / (i + 1)) * (total - i - 1);
        process.stdout.write(`\rframe ${i + 1}/${total}  ${elapsed.toFixed(0)}s elapsed, ~${eta.toFixed(0)}s left   `);
      }
    }
    process.stdout.write('\n');

    // 2. Generate temporary audio file
    const audioFile = path.join(OUT_DIR, 'temp_audio.wav');
    generateAudioTrack(audioFile, duration, 44100);

    // 3. Render final MP4 with video and audio merged via FFmpeg
    fs.mkdirSync(path.dirname(OUT_FILE), { recursive: true });
    await new Promise((resolve, reject) => {
      const ff = spawn('ffmpeg', [
        '-y', '-hide_banner', '-loglevel', 'error',
        '-framerate', String(FPS), '-i', path.join(framesDir, 'frame_%04d.png'),
        '-i', audioFile,
        '-vf', 'scale=out_color_matrix=bt709:out_range=tv,format=yuv420p',
        '-c:v', 'libx264', '-crf', '14', '-preset', 'slow',
        '-c:a', 'aac', '-b:a', '192k',
        '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv',
        '-shortest',
        '-movflags', '+faststart', OUT_FILE,
      ], { stdio: 'inherit' });
      ff.on('error', reject);
      ff.on('close', code => {
        if (fs.existsSync(audioFile)) fs.unlinkSync(audioFile);
        code === 0 ? resolve() : reject(new Error(`ffmpeg exited with ${code}`));
      });
    });

    if (!flag('keep-frames')) fs.rmSync(framesDir, { recursive: true, force: true });
    console.log(`Wrote ${OUT_FILE}`);
  } finally {
    await browser.close();
    server.close();
  }
}

main().catch(err => { console.error(err.message || err); process.exit(1); });