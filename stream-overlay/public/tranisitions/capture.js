/**
 * capture.js
 * Renders hex-stinger.html frame by frame using Puppeteer,
 * saves PNG frames with alpha, then assembles them into a webm with ffmpeg.
 *
 * Usage:
 *   node capture.js
 *
 * Output:
 *   ./frames/          — individual PNGs (deleted after encode unless --keep-frames)
 *   ./hex-stinger.webm — final VP9 webm with alpha channel, ready for OBS
 *
 * Requirements:
 *   npm install puppeteer
 *   ffmpeg on PATH
 */

const puppeteer = require('puppeteer');
const path      = require('path');
const fs        = require('fs');
const { execSync } = require('child_process');

const FPS         = 60;
const FRAME_MS    = 1000 / FPS;
const HTML_PATH   = path.resolve(__dirname, 'hex-wave.html');
const FRAMES_DIR  = path.resolve(__dirname, 'frames');
const OUTPUT_WEBM = path.resolve(__dirname, 'hex-wave.webm');
const KEEP_FRAMES = process.argv.includes('--keep-frames');

async function main() {
  // ── Setup ──────────────────────────────────────────────
  if (!fs.existsSync(FRAMES_DIR)) fs.mkdirSync(FRAMES_DIR);

  const browser = await puppeteer.launch({
    headless: 'new',
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--window-size=1920,1080',
    ],
  });

  const page = await browser.newPage();
  await page.setViewport({ width: 1920, height: 1080, deviceScaleFactor: 1 });

  // Transparent background — critical for alpha
  await page.goto(`file://${HTML_PATH}`);
  await page._client().send('Emulation.setDefaultBackgroundColorOverride', {
    color: { r: 0, g: 0, b: 0, a: 0 },
  });

  // Get total duration from the page
  const totalMs   = await page.evaluate(() => window.TOTAL_MS);
  const cutFrameMs = await page.evaluate(() => window.GROW_END_MS);
  const frameCount = Math.ceil(totalMs / FRAME_MS);
  const cutFrame   = Math.round(cutFrameMs / FRAME_MS);

  console.log(`Rendering ${frameCount} frames at ${FPS}fps (${totalMs}ms total)`);
  console.log(`Cut point: frame ${cutFrame} of ${frameCount} (${cutFrameMs.toFixed(0)}ms)`);

  // ── Render frames ──────────────────────────────────────
  for (let i = 0; i <= frameCount; i++) {
    const ms = i * FRAME_MS;
    await page.evaluate((t) => window.renderFrame(t), ms);

    const padded = String(i).padStart(5, '0');
    await page.screenshot({
      path: path.join(FRAMES_DIR, `frame${padded}.png`),
      omitBackground: true,   // preserves alpha
    });

    if (i % 10 === 0) process.stdout.write(`\r  frame ${i}/${frameCount}`);
  }

  await browser.close();
  console.log('\nCapture complete. Encoding webm...');

  // ── Encode to webm VP9 with alpha ─────────────────────
  // VP9 is the only codec OBS stingers support with alpha.
  // -pix_fmt yuva420p  — required for VP9 alpha
  // -auto-alt-ref 0    — must be disabled for alpha to work
  // -crf 10            — near-lossless quality
  const ffmpegCmd = [
    'ffmpeg -y',
    `-framerate ${FPS}`,
    `-i "${path.join(FRAMES_DIR, 'frame%05d.png')}"`,
    '-c:v libvpx-vp9',
    '-pix_fmt yuva420p',
    '-b:v 0 -crf 10',
    '-auto-alt-ref 0',
    '-metadata:s:v:0 alpha_mode=1',
    `"${OUTPUT_WEBM}"`,
  ].join(' ');

  execSync(ffmpegCmd, { stdio: 'inherit' });

  // ── Cleanup ────────────────────────────────────────────
  if (!KEEP_FRAMES) {
    fs.rmSync(FRAMES_DIR, { recursive: true });
    console.log('Frames cleaned up.');
  }

  console.log(`\nDone: ${OUTPUT_WEBM}`);
  console.log(`\n── OBS setup ────────────────────────────────`);
  console.log(`  Transition type : Stinger`);
  console.log(`  Video file      : hex-wave.webm`);
  console.log(`  Transition point: Time (ms) → ${cutFrameMs.toFixed(0)} ms`);
  console.log(`  Use "Transition Point Type: Time"`);
  console.log(`────────────────────────────────────────────\n`);
}

main().catch(e => { console.error(e); process.exit(1); });
