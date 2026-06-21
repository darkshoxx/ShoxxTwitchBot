/**
 * layout.js
 * Shared layout position config + animator.
 * Each overlay registers its components and their positions for each of the
 * four cases. The WebSocket layout event triggers an animated reflow.
 *
 * Cases (booleans → string key):
 *   "00" = notescam off, livesplit off   (default)
 *   "10" = notescam on,  livesplit off
 *   "01" = notescam off, livesplit on
 *   "11" = notescam on,  livesplit on
 *
 * Position objects: { top, left, width, height, opacity } — all CSS strings.
 * Omit a key to leave that property untouched.
 */

window.LAYOUT = (() => {

  // ── Position catalogue ──────────────────────────────────
  // Edit these to taste. All values are CSS strings.
  // 1920×1080 canvas.

  const POSITIONS = {

    chat: {
      '00': { bottom: '0px',   right: '0px',  width: '340px', height: '600px', opacity: '1' },
      '10': { bottom: '0px',   right: '0px',  width: '280px', height: '500px', opacity: '1' },
      '01': { bottom: '0px',   right: '0px',  width: '280px', height: '440px', opacity: '1' },
      '11': { bottom: '0px',   right: '0px',  width: '240px', height: '380px', opacity: '1' },
    },

    webcam: {
      '00': { bottom: '0px',  left: '0px',  width: '400px', height: '400px', opacity: '1' },
      '10': { bottom: '200px', left: '0px', width: '320px', height: '320px', opacity: '1' },
      '01': { bottom: '0px',  left: '0px',  width: '320px', height: '320px', opacity: '1' },
      '11': { bottom: '160px', left: '0px', width: '280px', height: '280px', opacity: '1' },
    },

    notescam: {
      '00': { bottom: '0px',  left: '0px',   width: '400px', height: '300px', opacity: '0' },
      '10': { bottom: '0px',  left: '0px',   width: '400px', height: '300px', opacity: '1' },
      '01': { bottom: '0px',  left: '0px',   width: '400px', height: '300px', opacity: '0' },
      '11': { bottom: '0px',  left: '0px',   width: '360px', height: '270px', opacity: '1' },
    },

    livesplit: {
      '00': { top: '20px',  right: '360px', width: '200px', opacity: '0' },
      '10': { top: '20px',  right: '360px', width: '200px', opacity: '0' },
      '01': { top: '20px',  right: '360px', width: '200px', opacity: '1' },
      '11': { top: '20px',  right: '360px', width: '200px', opacity: '1' },
    },

  };

  // ── Animator ────────────────────────────────────────────

  const TRANSITION = 'top 0.4s cubic-bezier(0.16,1,0.3,1), ' +
                     'left 0.4s cubic-bezier(0.16,1,0.3,1), ' +
                     'bottom 0.4s cubic-bezier(0.16,1,0.3,1), ' +
                     'right 0.4s cubic-bezier(0.16,1,0.3,1), ' +
                     'width 0.4s cubic-bezier(0.16,1,0.3,1), ' +
                     'height 0.4s cubic-bezier(0.16,1,0.3,1), ' +
                     'opacity 0.3s ease';

  function caseKey(notescam, livesplit) {
    return `${notescam ? 1 : 0}${livesplit ? 1 : 0}`;
  }

  function applyLayout(el, positions) {
    el.style.transition = TRANSITION;
    for (const [prop, val] of Object.entries(positions)) {
      el.style[prop] = val;
    }
  }

  // components: { [name]: HTMLElement }
  function register(components) {
    function apply(notescam, livesplit) {
      const key = caseKey(notescam, livesplit);
      for (const [name, el] of Object.entries(components)) {
        if (!el) continue;
        const pos = POSITIONS[name]?.[key];
        if (pos) applyLayout(el, pos);
      }
    }

    // Apply immediately (no transition) on first load
    window.addEventListener('overlay:layout', e => {
      apply(e.detail.notescam, e.detail.livesplit);
    });

    // Also listen for the initial state sent on WS connect
    window.addEventListener('overlay:connected_layout', e => {
      // suppress transition on first paint
      const els = Object.values(components).filter(Boolean);
      els.forEach(el => { el.style.transition = 'none'; });
      apply(e.detail.notescam, e.detail.livesplit);
      // re-enable after paint
      requestAnimationFrame(() => requestAnimationFrame(() => {
        els.forEach(el => { el.style.transition = TRANSITION; });
      }));
    });

    return { apply };
  }

  return { register, POSITIONS, caseKey };
})();
