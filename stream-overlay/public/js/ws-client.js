/**
 * ws-client.js
 * Shared WebSocket helper for overlay pages.
 * Reconnects automatically; dispatches CustomEvents on window.
 *
 * Usage in an overlay:
 *   window.addEventListener('overlay:follow',  e => console.log(e.detail));
 *   window.addEventListener('overlay:sub',     e => ...);
 *   window.addEventListener('overlay:pokemon', e => ...);
 *   window.addEventListener('overlay:spin',    e => ...);
 *   window.addEventListener('overlay:raid',    e => ...);
 */
(function () {
  const WS_URL = `ws://${location.host}`;
  let ws, retryTimer;

  function connect() {
    ws = new WebSocket(WS_URL);

    ws.addEventListener('message', ({ data }) => {
      try {
        const event = JSON.parse(data);
        if (event.type && event.type !== 'connected') {
          window.dispatchEvent(
            new CustomEvent(`overlay:${event.type}`, { detail: event })
          );
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