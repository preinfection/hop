// window.lyricsIsland for the lightweight host: the same eight calls and the
// same state feed that Electron's preload.js exposed, so the original
// renderer.js / index.html / styles.css run unchanged. Calls made before
// pywebview is ready are queued.
(() => {
  // TRANSPARENCY. styles.css sets `color-scheme: dark` on :root, and under
  // WebView2 (unlike Electron) that makes Chromium paint a dark #202020 canvas
  // behind the transparent page, so the pill sat in a grey box. The root goes
  // back to the normal scheme and the ISLAND carries the dark one instead, so
  // everything inside it (buttons, settings inputs) looks exactly the same.
  const fix = document.createElement("style");
  fix.textContent = ":root{color-scheme:normal!important;background:transparent!important}.island{color-scheme:dark}";
  (document.head || document.documentElement).appendChild(fix);

  let api = null;
  const waiting = [];
  const listeners = [];
  // PREVIEW: inside the settings app the page runs in an iframe. Local pages
  // can't reach into each other, so every API call is a message to the
  // settings window (whose window-moving calls do nothing), and the settings
  // window drives the preview with messages too. Nothing pushes state to it,
  // so it asks for the state every second.
  const preview = /[?&]preview=/.test(location.search);
  window.__islandPreview = preview;
  let ready;
  if (preview) {
    let seq = 0;
    const pending = new Map();
    window.addEventListener("message", (e) => {
      const m = e.data || {};
      if (m.t === "res" && pending.has(m.id)) { pending.get(m.id)(m.v); pending.delete(m.id); }
      else if (m.t === "cmd") { const f = window["__island" + m.fn]; if (f) f(...(m.args || [])); }
    });
    api = new Proxy({}, { get: (_, name) => name === "then" ? undefined : (...args) => new Promise((res) => {
      const id = ++seq;
      pending.set(id, res);
      window.parent.postMessage({ t: "call", id, name, args }, "*");
    }) });
    ready = Promise.resolve(api);
    window.addEventListener("load", () => window.parent.postMessage({ t: "ready" }, "*"));
    setInterval(() => api.get_state().then((st) => st && window.__islandPush(st)), 1000);
  } else {
    ready = new Promise((resolve) => {
      const done = () => { api = window.pywebview.api; resolve(api); waiting.splice(0).forEach((f) => f(api)); };
      if (window.pywebview && window.pywebview.api && window.pywebview.api.get_state) done();
      else window.addEventListener("pywebviewready", done, { once: true });
    });
  }
  const call = (name, ...args) => ready.then((a) => a[name](...args));

  window.__islandPush = (state) => listeners.forEach((cb) => { try { cb(state); } catch (e) { console.error(e); } });

  window.lyricsIsland = {
    getState: () => call("get_state"),
    saveConfig: (config) => call("save_config", config),
    connectSpotify: () => call("connect_spotify"),
    openSpotifyDashboard: () => call("open_dashboard"),
    playback: (action) => call("playback", action),
    seek: (positionMs) => call("seek", positionMs),
    setExpanded: (expanded) => call("set_expanded", expanded),
    resizeExpanded: (size) => call("resize_expanded", size),
    recenter: () => call("recenter"),
    getVolume: () => call("get_volume"),
    setVolume: (level, muted) => call("set_volume", level ?? null, muted ?? null),
    setExtra: (px) => call("set_extra", px),
    record: (on) => call("record", on),
    getPrayers: () => call("get_prayers"),
    holdOpen: (on) => call("hold_open", on),
    chime: () => call("chime"),
    setPillWide: (on) => call("set_pill_wide", on),
    setPillWidth: (px) => call("set_pill_width", px),
    setBig: (on) => call("set_big", on),
    openFile: (path) => call("open_file", path),
    copyFile: (path) => call("copy_file", path),
    getToday: () => call("get_today"),
    log: (msg) => call("log", msg),
    getClips: () => call("get_clips"),
    openClipsFolder: () => call("open_clips_folder"),
    getSys: () => call("get_sys"),
    ping: () => call("ping"),
    speedtest: () => call("speedtest"),
    micMuted: () => call("mic_muted"),
    setMic: (muted) => call("set_mic", muted),
    snip: () => call("snip"),
    getClipboard: () => call("get_clipboard"),
    copyText: (text) => call("copy_text", text),
    openSettings: () => call("open_settings"),
    restartApp: () => call("restart_app"),
    updateAnswer: (go) => call("update_answer", go),
    swiped: () => call("swiped"),
    remapHosts: () => call("remap_hosts"),
    onState: (callback) => listeners.push(callback)
  };

  // DRAGGING. Electron did it with -webkit-app-region, which only Electron
  // understands. Here: press anywhere on the island that is not a control and
  // move a few pixels, and the host hands the window to Windows' own move loop
  // (smooth, native). Waiting for movement first keeps double-click-to-expand
  // working on the artwork and title too.
  const NO_DRAG = "button, input, label, form, .progress, .vol-row, .resize-handle, .settings-popover, .lyric-panel";
  let press = null;
  window.addEventListener("mousedown", (e) => {
    if (e.button !== 0 || e.target.closest(NO_DRAG) || !e.target.closest(".island")) return;
    const isl = e.target.closest(".island");
    if (isl.classList.contains("carding") || isl.classList.contains("alerting")) return;   // that drag swipes it away
    press = { x: e.screenX, y: e.screenY };
  }, true);
  window.addEventListener("mousemove", (e) => {
    if (!press || !(e.buttons & 1)) { press = null; return; }
    if (Math.abs(e.screenX - press.x) + Math.abs(e.screenY - press.y) > 4) {
      press = null;
      call("start_drag");
    }
  }, true);
  window.addEventListener("mouseup", () => { press = null; }, true);
})();
