/*
  The intro sound: the ONE place it is defined.

    - Live preview (intro.html): playIntroSound() plays it through a normal AudioContext.
    - Export (render.mjs): renderIntroSoundWav() renders the very same node graph offline
      (OfflineAudioContext) to a WAV, which ffmpeg then muxes into Intro.mp4.

  To change the sound, edit buildIntroSound(). Times inside it are relative to the moment the
  sound starts. WHEN it starts within the 2 s intro is set by CFG.sound.startAt in intro.html.
*/

/** Builds the sound on any Web Audio context (live or offline), starting at context time `t0`. */
export function buildIntroSound(ctx, t0 = ctx.currentTime) {
  const now = t0;

  // 1. Synthetic ZOOM (Frequency sweep + Filter sweep)
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  const filter = ctx.createBiquadFilter();

  osc.type = 'sawtooth';
  osc.frequency.setValueAtTime(80, now);
  osc.frequency.exponentialRampToValueAtTime(600, now + 0.6);

  filter.type = 'lowpass';
  filter.frequency.setValueAtTime(200, now);
  filter.frequency.exponentialRampToValueAtTime(2500, now + 0.55);

  gain.gain.setValueAtTime(0.01, now);
  gain.gain.linearRampToValueAtTime(0.25, now + 0.4);
  gain.gain.exponentialRampToValueAtTime(0.001, now + 0.7);

  osc.connect(filter);
  filter.connect(gain);
  gain.connect(ctx.destination);

  osc.start(now);
  osc.stop(now + 0.7);

  // 2. Final "PLING" (Bell-like high sine wave with long decay)
  const plingTime = now + 0.58;
  const plingOsc = ctx.createOscillator();
  const plingGain = ctx.createGain();

  plingOsc.type = 'sine';
  plingOsc.frequency.setValueAtTime(1046.50, plingTime); // High C (C6)
  plingOsc.frequency.exponentialRampToValueAtTime(2093.00, plingTime + 0.05);

  plingGain.gain.setValueAtTime(0.01, plingTime);
  plingGain.gain.linearRampToValueAtTime(0.3, plingTime + 0.02);
  plingGain.gain.exponentialRampToValueAtTime(0.0001, plingTime + 1.2);

  plingOsc.connect(plingGain);
  plingGain.connect(ctx.destination);

  plingOsc.start(plingTime);
  plingOsc.stop(plingTime + 1.3);
}

// ── live preview ────────────────────────────────────────────────────────
let liveCtx = null;

/** Plays the sound now through the speakers (the browser may need a click on the page first). */
export function playIntroSound() {
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!AC) return;
  if (!liveCtx) liveCtx = new AC();
  if (liveCtx.state === 'suspended') liveCtx.resume();
  buildIntroSound(liveCtx, liveCtx.currentTime);
}

// ── export ──────────────────────────────────────────────────────────────
/**
 * Renders the sound offline into a stereo 16-bit WAV that is `duration` seconds long, with the
 * sound starting `startAt` seconds in. Returns the WAV file as a base64 string.
 */
export async function renderIntroSoundWav(duration, startAt, sampleRate = 44100) {
  const ctx = new OfflineAudioContext({
    numberOfChannels: 2, length: Math.ceil(duration * sampleRate), sampleRate });
  buildIntroSound(ctx, startAt);
  return toBase64(audioBufferToWav(await ctx.startRendering()));
}

function audioBufferToWav(buffer) {
  const channels = buffer.numberOfChannels, frames = buffer.length, rate = buffer.sampleRate;
  const dataBytes = frames * channels * 2;
  const view = new DataView(new ArrayBuffer(44 + dataBytes));
  const text = (offset, s) => { for (let i = 0; i < s.length; i++) view.setUint8(offset + i, s.charCodeAt(i)); };

  text(0, 'RIFF'); view.setUint32(4, 36 + dataBytes, true);
  text(8, 'WAVE'); text(12, 'fmt ');
  view.setUint32(16, 16, true); view.setUint16(20, 1, true);            // PCM
  view.setUint16(22, channels, true); view.setUint32(24, rate, true);
  view.setUint32(28, rate * channels * 2, true); view.setUint16(32, channels * 2, true);
  view.setUint16(34, 16, true);
  text(36, 'data'); view.setUint32(40, dataBytes, true);

  const data = Array.from({ length: channels }, (_, c) => buffer.getChannelData(c));
  let offset = 44;
  for (let i = 0; i < frames; i++) {
    for (let c = 0; c < channels; c++) {
      const s = Math.max(-1, Math.min(1, data[c][i]));
      view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
      offset += 2;
    }
  }
  return new Uint8Array(view.buffer);
}

function toBase64(bytes) {
  let binary = '';
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}
