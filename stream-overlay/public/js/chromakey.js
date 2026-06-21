/**
 * chromakey.js
 * Replaces a <video> element with a <canvas> that renders the video
 * with a specified colour made transparent in real time.
 *
 * Usage:
 *   const ck = ChromaKey(videoEl, { r:0, g:0, b:0, threshold:30 });
 *   ck.start();   // begin rendering
 *   ck.stop();    // pause rendering
 *   ck.setKey({ r:0, g:255, b:0, threshold:60 }); // change colour at runtime
 *
 * The canvas is inserted immediately after the video in the DOM and
 * sized to match. The video element itself is hidden.
 *
 * Presets:
 *   ChromaKey.BLACK  = { r:0,   g:0,   b:0,   threshold: 30 }
 *   ChromaKey.GREEN  = { r:0,   g:255, b:0,   threshold: 60 }
 *   ChromaKey.BLUE   = { r:0,   g:0,   b:255, threshold: 60 }
 */

window.ChromaKey = function(videoEl, keyColor) {
  const canvas = document.createElement('canvas');
  canvas.style.cssText = videoEl.style.cssText;
  canvas.className     = videoEl.className;
  // mirror position so it drops in as a visual replacement
  canvas.style.position = getComputedStyle(videoEl).position || 'fixed';
  videoEl.parentNode.insertBefore(canvas, videoEl.nextSibling);
  videoEl.style.display = 'none';

  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  let key = { ...keyColor };
  let rafId = null;
  let running = false;

  function syncSize() {
    if (videoEl.videoWidth) {
      canvas.width  = videoEl.videoWidth;
      canvas.height = videoEl.videoHeight;
    }
  }

  function renderFrame() {
    if (!running) return;
    syncSize();
    if (canvas.width && canvas.height && !videoEl.paused && !videoEl.ended) {
      ctx.drawImage(videoEl, 0, 0, canvas.width, canvas.height);
      const frame = ctx.getImageData(0, 0, canvas.width, canvas.height);
      const d = frame.data;
      const { r: kr, g: kg, b: kb, threshold: T = 40 } = key;
      for (let i = 0; i < d.length; i += 4) {
        const dr = d[i]   - kr;
        const dg = d[i+1] - kg;
        const db = d[i+2] - kb;
        if (Math.sqrt(dr*dr + dg*dg + db*db) < T) {
          d[i+3] = 0; // transparent
        }
      }
      ctx.putImageData(frame, 0, 0);
    }
    rafId = requestAnimationFrame(renderFrame);
  }

  // Mirror visibility class from video to canvas
  const observer = new MutationObserver(() => {
    canvas.className = videoEl.className;
    videoEl.style.display = 'none'; // keep video hidden regardless
  });
  observer.observe(videoEl, { attributes: true, attributeFilter: ['class'] });

  return {
    canvas,
    start() { running = true; renderFrame(); },
    stop()  { running = false; cancelAnimationFrame(rafId); },
    setKey(k) { key = { ...key, ...k }; },
  };
};

ChromaKey.BLACK = { r: 0,   g: 0,   b: 0,   threshold: 35 };
ChromaKey.GREEN = { r: 0,   g: 255, b: 0,   threshold: 60 };
ChromaKey.BLUE  = { r: 0,   g: 0,   b: 255, threshold: 60 };
