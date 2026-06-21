/**
 * ws-client.js
 * Auto-reconnecting WebSocket. Dispatches CustomEvents on window:
 *   overlay:<type>  for all events
 *   overlay:connected_layout  for the initial layout state on connect
 */
(function () {
  const WS_URL = `ws://${location.host}`;
  let ws, retryTimer;

  function connect() {
    ws = new WebSocket(WS_URL);
    let gotInitialLayout = false;

    ws.addEventListener('message', ({ data }) => {
      try {
        const event = JSON.parse(data);
        if (!event.type) return;

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