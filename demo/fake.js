// Injected (by demo/serve.py) at the top of the real island / settings page:
// window.pywebview.api, answered by the simulated host in the demo page
// around this frame (demo/host.js), so the real pages run unchanged.
(() => {
  const host = window.top && window.top.__demoHost;
  if (!host) return;
  const api = new Proxy({}, {
    get: (_, name) => name === "then" ? undefined : (...args) => {
      try { return Promise.resolve(host.call(window, String(name), args)); } catch (e) { console.error(name, e); return Promise.resolve(null); }
    },
  });
  window.pywebview = { api };
  host.attach(window);
})();
