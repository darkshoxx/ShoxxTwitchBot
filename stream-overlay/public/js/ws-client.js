/**
 * ws-client.js
 * Auto-reconnecting WebSocket. Dispatches CustomEvents on window:
 *   overlay:<type>  for all events
 *   overlay:connected_layout  for the initial layout state on connect
 * Also syncs --theme from theme.css onto <html data-theme="..."> across all overlays.
 */
(function () {
  const WS_URL = `ws://${location.host}`;
  let ws, retryTimer;

  function readCssToken(name) {
    const styles = getComputedStyle(document.documentElement);
    let val = styles.getPropertyValue(name).trim();
    const commentIdx = val.indexOf('/*');
    if (commentIdx !== -1) val = val.slice(0, commentIdx).trim();
    let guard = 0;
    while (val.startsWith('var(') && val.endsWith(')') && guard < 12) {
      const inner = val.slice(4, -1).trim();
      const comma = inner.indexOf(',');
      const varName = (comma === -1 ? inner : inner.slice(0, comma)).trim();
      const fallback = comma === -1 ? '' : inner.slice(comma + 1).trim();
      let next = styles.getPropertyValue(varName).trim();
      const cIdx = next.indexOf('/*');
      if (cIdx !== -1) next = next.slice(0, cIdx).trim();
      val = next || fallback;
      guard++;
    }
    return val.replace(/^["']|["']$/g, '').trim();
  }

  function syncThemeFromCss() {
    const mode = readCssToken('--theme').toLowerCase();
    if (mode === 'christmas') {
      document.documentElement.setAttribute('data-theme', 'christmas');
    } else if (mode === 'regular') {
      document.documentElement.removeAttribute('data-theme');
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', syncThemeFromCss);
  } else {
    syncThemeFromCss();
  }
  window.addEventListener('load', syncThemeFromCss);

  function connect() {
    ws = new WebSocket(WS_URL);
    let gotInitialLayout = false;

    ws.addEventListener('message', ({ data }) => {
      try {
        const event = JSON.parse(data);
        if (!event.type) return;

        if (event.type === 'refresh') {
          location.reload();
          return;
        }

        if (event.type === 'layout') {
          // First layout message after connect is the initial state
          const evtName = gotInitialLayout ? 'overlay:layout' : 'overlay:connected_layout';
          gotInitialLayout = true;
          window.dispatchEvent(new CustomEvent(evtName, { detail: event }));
          // Also always dispatch overlay:layout so components that don't care about
          // the distinction still update
          if (evtName === 'overlay:connected_layout') {
            window.dispatchEvent(new CustomEvent('overlay:layout', { detail: event }));
          }
          return;
        }

        if (event.type !== 'connected') {
          window.dispatchEvent(new CustomEvent(`overlay:${event.type}`, { detail: event }));
        }
      } catch (_) {}
    });

    ws.addEventListener('close', () => {
      clearTimeout(retryTimer);
      retryTimer = setTimeout(connect, 3000);
    });
    ws.addEventListener('error', () => ws.close());
  }

  connect();
})();
