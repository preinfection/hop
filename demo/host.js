// The simulated Hop host for the browser demo. The real one is island/host.py
// (Windows media, the clipper, Claude Code hooks...); this one answers the
// same calls with made-up but believable data, and the buttons on the demo
// page fire the same events the real host would.
(() => {
  const H = {};
  window.__demoHost = H;
  let L = null, SPEC = {}, POPDEF = {};
  let islandWin = null, settingsWin = null;
  const frames = () => ({ island: document.getElementById("islandFrame"), settings: document.getElementById("settingsFrame") });

  // ---------------------------------------------------------------- made-up media
  function art(c1, c2, label) {
    const c = document.createElement("canvas"); c.width = c.height = 120;
    const g = c.getContext("2d"), gr = g.createLinearGradient(0, 0, 120, 120);
    gr.addColorStop(0, c1); gr.addColorStop(1, c2); g.fillStyle = gr; g.fillRect(0, 0, 120, 120);
    g.fillStyle = "rgba(255,255,255,.85)"; g.font = "bold 34px Segoe UI"; g.textAlign = "center"; g.fillText(label, 60, 74);
    return c.toDataURL("image/png");
  }
  function thumb(c1, c2, label) {
    const c = document.createElement("canvas"); c.width = 320; c.height = 180;
    const g = c.getContext("2d"), gr = g.createLinearGradient(0, 0, 320, 180);
    gr.addColorStop(0, c1); gr.addColorStop(1, c2); g.fillStyle = gr; g.fillRect(0, 0, 320, 180);
    g.fillStyle = "rgba(255,255,255,.8)"; g.font = "bold 26px Segoe UI"; g.textAlign = "center"; g.fillText(label, 160, 100);
    return c.toDataURL("image/jpeg", 0.8);
  }
  const SONGS = [
    { track: "Midnight City", artist: "M83", album: "Hurry Up, We're Dreaming", durationMs: 243000, c: ["#7b2ff7", "#f107a3"], l: "M83" },
    { track: "Blinding Lights (Extended Night Drive Version)", artist: "The Weeknd", album: "After Hours", durationMs: 200000, c: ["#ff512f", "#dd2476"], l: "AH" },
    { track: "Nights", artist: "Frank Ocean", album: "Blonde", durationMs: 307000, c: ["#1d976c", "#93f9b9"], l: "FO" },
  ];
  let songIdx = 0, playing = true, progressAt = Date.now() - 61000, progressMs = 61000, nothing = false, shuffle = false, repeat = "off";
  const pb = () => {
    if (nothing) return null;
    const s = SONGS[songIdx];
    if (!s.art) s.art = art(s.c[0], s.c[1], s.l);
    const p = playing ? progressMs + (Date.now() - progressAt) : progressMs;
    return { empty: false, isPlaying: playing, progressMs: Math.min(p, s.durationMs), durationMs: s.durationMs, track: s.track,
             artist: s.artist, album: s.album, artworkUrl: s.art, uri: "demo:" + songIdx, shuffle, repeat, app: "Spotify.exe" };
  };
  const state = () => ({ status: nothing ? "Nothing playing" : "Windows media", connected: true, demoMode: true, playback: pb(),
                         lyrics: { synced: [], plain: "", source: "none" }, activeLyricIndex: -1, config: {} });
  const push = () => { if (islandWin && islandWin.__islandPush) islandWin.__islandPush(state()); };
  const ev = (kind, data) => { if (islandWin && islandWin.__hopEvent) islandWin.__hopEvent(kind, data); };
  const js = (fn, ...a) => { if (islandWin && islandWin[fn]) islandWin[fn](...a); };

  // ---------------------------------------------------------------- prayer times around now, so the demo shows a countdown
  function prayers() {
    const d = new Date(), at = (mins) => { const x = new Date(d.getTime() + mins * 60000); return `${String(x.getHours()).padStart(2, "0")}:${String(x.getMinutes()).padStart(2, "0")}`; };
    const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    const t = { Fajr: "05:58", Sunrise: "07:21", Dhuhr: "13:06", Asr: "16:12", Maghrib: "18:49", Isha: "20:06" };
    t[d.getHours() < 13 ? "Dhuhr" : d.getHours() < 16 ? "Asr" : d.getHours() < 18 ? "Maghrib" : "Isha"] = at(14);
    return { date: iso, today: t, tomorrow: { ...t } };
  }
  let prayerData = null;
  const today = () => ({
    hijri: { day: 21, month: "Rabīʿ al-Thānī", year: 1448, events: [{ name: "Ramadan", days: 139 }, { name: "Eid al-Fitr", days: 169 }] },
    weather: { temp: 14.2, high: 17, low: 9, code: 2 }, prayers: prayerData,
  });

  // ---------------------------------------------------------------- clips, shelf, notes, agents...
  const clips = () => [
    { name: "clip 2026-10-03 14-42-45 (15s).mp4", seconds: 15, at: Date.now() / 1000 - 7400, kind: "clip", c: ["#1e3c72", "#2a5298"], l: "Roblox" },
    { name: "Roblox 2026-10-01 22-12-39 (30s).mp4", seconds: 30, at: Date.now() / 1000 - 90000, kind: "clip", c: ["#134e5e", "#71b280"], l: "Roblox" },
    { name: "recording 2026-10-01 21-59-46.mp4", seconds: 0, at: Date.now() / 1000 - 93000, kind: "recording", c: ["#41295a", "#2f0743"], l: "REC" },
  ].map((c) => ({ ...c, path: "C:\\demo\\" + c.name, url: "/demo/media/sample.mp4", thumb: thumb(c.c[0], c.c[1], c.l) }));
  let shelf = [
    { name: "design-notes.pdf", path: "C:\\demo\\design-notes.pdf", pinned: true },
    { name: "hop-logo.png", path: "C:\\demo\\hop-logo.png", thumb: art("#111", "#444", "🐰") },
  ];
  let notes = "Ideas for 0.1.4:\n- per-game clip folders\n- record mic as its own track";
  let prompter = "Hey everyone, welcome back.\nToday I'm showing Hop 0.1.3: the island got a notch, AI agent cards, a timer, a calendar, and way more settings.\nLet's start with the notch.";
  const agents = { sessions: [
    { id: "s1", tool: "claude", name: "hop", status: "work", detail: "Editing island/ui/features.js" },
    { id: "s2", tool: "codex", name: "mutate", status: "idle", detail: "Waiting for your next prompt" },
  ], usage: { five: 42, week: 18, fiveReset: "2h 14m", weekReset: "Tue" } };
  const extra = {
    calendarUrl: "", lastfm: { user: "", connected: false }, profiles: ["Gaming", "Work"], activeProfile: "",
    profileRules: [{ exe: "robloxplayerbeta.exe", profile: "Gaming" }],
    agents: { connected: false }, monitors: [{ index: 0, name: "Built-in display (1920×1080)", primary: true }, { index: 1, name: "DELL S2421H (1920×1080)", primary: false }],
    downloads: true, screenshots: true,
  };
  const extensions = [
    { id: "world-clock", name: "World clock", description: "Three cities at a glance", url: "/ext/world-clock/page.html" },
    { id: "countdown", name: "Big countdown", description: "Days left to a date you pick", url: "/ext/countdown/page.html" },
  ];

  // ---------------------------------------------------------------- settings validation (the host's options.py, simplified)
  function clean(raw) {
    const out = { ...L };
    for (const [k, v] of Object.entries(raw || {})) {
      const s = SPEC[k];
      if (!s) { if (["pages", "hidden", "musicLeft", "musicRight", "appTheme", "style", "scale"].includes(k) || typeof L[k] === "boolean") out[k] = v; continue; }
      const kind = s[0];
      if (kind === "bool" && typeof v === "boolean") out[k] = v;
      else if (kind === "enum" && s[2].includes(v)) out[k] = v;
      else if (kind === "int" && Number.isFinite(+v)) out[k] = Math.round(Math.min(s[3], Math.max(s[2], +v)));
      else if (kind === "color" && /^#[0-9a-f]{6}$/i.test(v)) out[k] = v.toLowerCase();
      else if (kind === "time" && /^([01]\d|2[0-3]):[0-5]\d$/.test(v)) out[k] = v;
      else if (kind === "str" && typeof v === "string") out[k] = v.slice(0, s[2]);
      else if (["order", "subset", "exes", "names", "countdowns", "reminders", "teams"].includes(kind) && Array.isArray(v)) out[k] = v;
      else if (kind === "popups" && v && typeof v === "object") out[k] = v;
    }
    if (out.hidden.length >= out.pages.length) out.hidden = out.hidden.filter((p) => p !== "music");
    return out;
  }
  function windowSize() {
    const notch = L.style === "notch", cw = notch ? L.notchW : L.pillW;
    const glow = L.glow ? 24 : 0;
    return [Math.max(L.openW, cw) + glow, L.openH + 42 + 4 + glow / 2];
  }
  function placeIsland() {
    const f = frames().island; if (!f || !L) return;
    const [w, h] = windowSize(), s = L.scale || 1;
    const gap = L.topGap >= 0 ? L.topGap : L.style === "notch" ? 0 : 10;
    Object.assign(f.style, { width: w * s + "px", height: h * s + "px", top: gap * s + "px", marginLeft: (-w * s / 2) + "px" });
    document.body.classList.toggle("is-notch", L.style === "notch");
  }
  function setLayout(raw) {
    L = clean(raw);
    placeIsland();
    js("__islandLayout", L);
    if (settingsWin && settingsWin.__demoLayout) settingsWin.__demoLayout(L);
    return { ...L };
  }

  // ---------------------------------------------------------------- hover: the real host watches the cursor; here the page does
  function wireHover(win) {
    const isl = win.document.getElementById("island");
    if (!isl) return;
    let enter = 0, leave = 0, open = false;
    const set = (on) => { if (on === open) return; open = on; win.__islandHover(on); };
    isl.addEventListener("mouseenter", () => {
      clearTimeout(leave);
      if (L.openOn === "click" || win.document.querySelector(".island.carding")) return;
      enter = setTimeout(() => set(true), L.hoverDelay);
    });
    isl.addEventListener("click", () => { if (L.openOn === "click" && !open) set(true); });
    win.document.addEventListener("mouseleave", () => { clearTimeout(enter); if (!H.pinned) leave = setTimeout(() => set(false), 300 + L.closeDelay); });
    isl.addEventListener("mouseleave", (e) => {
      clearTimeout(enter);
      if (H.pinned || isl.contains(e.relatedTarget)) return;
      leave = setTimeout(() => set(false), 300 + L.closeDelay);
    });
    H.setOpen = set;
  }

  H.attach = (win) => {
    const isIsland = /index\.html/.test(win.location.pathname) && !/preview=/.test(win.location.search);
    const isSettings = /settings\.html/.test(win.location.pathname);
    if (isIsland) {
      islandWin = win;
      win.addEventListener("load", () => {
        wireHover(win);
        push();
        setTimeout(() => ev("agents", agents), 300);
      });
    }
    if (isSettings) settingsWin = win;
  };

  // ---------------------------------------------------------------- every call the pages make
  const sounds = { tick: [1200, 0.04], pop: [660, 0.08], chime: [880, 0.5], bell: [523, 0.9] };
  function beep(name) {
    const s = sounds[name]; if (!s) return;
    try {
      const a = H.audio || (H.audio = new AudioContext()), o = a.createOscillator(), g = a.createGain();
      o.frequency.value = s[0]; o.type = "sine"; g.gain.setValueAtTime(0.18, a.currentTime); g.gain.exponentialRampToValueAtTime(0.001, a.currentTime + s[1]);
      o.connect(g).connect(a.destination); o.start(); o.stop(a.currentTime + s[1]);
    } catch {}
  }
  const log = (...a) => { const el = document.getElementById("log"); if (el) { el.textContent = a.join(" ") + "\n" + el.textContent.slice(0, 2000); } };

  H.call = (win, name, args) => {
    switch (name) {
      case "get_state": return state();
      case "playback": {
        const a = args[0];
        if (a === "play" || a === "pause") { progressMs = pb() ? pb().progressMs : 0; progressAt = Date.now(); playing = a === "play"; }
        if (a === "next" || a === "previous") { songIdx = (songIdx + (a === "next" ? 1 : SONGS.length - 1)) % SONGS.length; progressMs = 0; progressAt = Date.now(); }
        if (a === "shuffle") shuffle = !shuffle;
        if (a === "repeat") repeat = { off: "all", all: "one", one: "off" }[repeat];
        setTimeout(push, 60); return state();
      }
      case "seek": progressMs = args[0]; progressAt = Date.now(); return state();
      case "get_volume": return H.vol || (H.vol = { level: 0.62, muted: false });
      case "set_volume": { const v = H.vol || (H.vol = { level: 0.62, muted: false }); if (args[0] != null) v.level = args[0]; if (args[1] != null) v.muted = args[1]; return v; }
      case "get_prayers": return prayerData;
      case "get_today": return today();
      case "get_clips": return clips();
      case "get_sys": return { cpu: 18 + Math.random() * 20, gpu: 30 + Math.random() * 25, ram: { used: 9.1e9, total: 15.7e9 },
                               disks: { C: { letter: "C", free: 95e9, total: 475e9 }, E: { letter: "E", free: 37e9, total: 931e9 } } };
      case "ping": return 18 + Math.round(Math.random() * 12);
      case "speedtest": return new Promise((r) => setTimeout(() => r(212), 1500));
      case "record": H.rec = args[0] ? Date.now() : 0; return { available: true, started: H.rec };
      case "hold_open": if (H.setOpen) H.setOpen(!!args[0]); return true;
      case "chime": beep(args[0] === "bell" ? "bell" : "chime"); return true;
      case "sound": beep(args[0]); return true;
      case "set_pill_width": case "set_pill_wide": case "set_big": case "set_extra": case "set_expanded": case "start_drag": case "swiped": case "log":
      case "remap_hosts": case "want_keys":
        return true;
      case "recenter": log("snap to top middle"); return true;
      case "open_file": case "show_file": case "open_url": case "open_clips_folder": case "open_calendar": case "agent_jump":
        log(name, args[0] || ""); return true;
      case "copy_file": case "copy_image": log("copied", args[0]); return true;
      case "open_settings": H.openSettings(); return true;
      case "restart_app": islandWin && islandWin.location.reload(); return true;
      case "update_answer": log("update:", args[0] ? "now" : "later"); return true;
      case "install_update": {
        let p = 0; const t = setInterval(() => { p += 0.12; ev("update", { latest: "0.1.4", state: "downloading", progress: Math.min(1, p) }); if (p >= 1) { clearInterval(t); log("would run HopSetup-0.1.4.exe /SILENT and restart"); } }, 250);
        return true;
      }
      // the newer calls
      case "hop_hello": return { agents, calendar: H.calendar || [], calSet: true, extensions, clipStats: { running: true, today: 3 }, privacy: { mic: [], cam: [] } };
      case "need": return true;
      case "get_battery": return { pct: 64, charging: false, minutes: 192, health: 87, cycles: 312, design: 41000, full: 35670,
        drainers: [{ name: "Roblox", cpu: 21.4 }, { name: "Brave", cpu: 6.2 }, { name: "Spotify", cpu: 1.1 }] };
      case "get_shelf": return shelf;
      case "shelf": {
        const [op, path] = args;
        if (op === "remove") shelf = shelf.filter((s) => s.path !== path);
        if (op === "pin") shelf = shelf.map((s) => s.path === path ? { ...s, pinned: !s.pinned } : s).sort((a, b) => b.pinned - a.pinned);
        if (op === "add") shelf.unshift({ name: path.split("\\").pop(), path });
        return shelf;
      }
      case "get_notes": return notes;
      case "set_notes": notes = args[0]; return true;
      case "get_prompter": return prompter;
      case "agent_answer": {
        log("agent answer:", JSON.stringify(args[1]));
        agents.sessions[0].status = "work"; agents.sessions[0].detail = args[1] === "deny" ? "Denied: trying another way" : "Running the command";
        ev("agents", agents); return true;
      }
      case "trim_clip": return new Promise((r) => setTimeout(() => r({ path: "C:\\demo\\clip (trimmed).mp4", name: "clip 2026-10-03 14-42-45 (trimmed).mp4" }), 700));
      case "upload_file": {
        ev("x", 0); let p = 0;
        const t = setInterval(() => { p += 0.25; js("__islandUpload", p < 1 ? { state: "uploading", name: "clip.mp4", size: 16680314, progress: p } : { state: "done", link: "https://mutate.lol/f/k3x9q" }); if (p >= 1) clearInterval(t); }, 300);
        return true;
      }
      case "drop_choice": log("drop:", args[1]); if (args[1] === "shelf") shelf.unshift({ name: args[0].split("\\").pop(), path: args[0] }); else H.call(win, "upload_file", [args[0]]); return true;
      // settings app
      case "get_layout": return { ...L };
      case "set_layout": return setLayout(args[0]);
      case "reset_layout": return setLayout({ ...H.base, scale: L.scale });
      case "get_position": return H.pos || (H.pos = { x: 50, top: 0 });
      case "set_position": H.pos = { x: args[0] ?? (H.pos || {}).x ?? 50, top: args[1] ?? (H.pos || {}).top ?? 0 }; return H.pos;
      case "reset_position": H.pos = { x: 50, top: 0 }; return { layout: setLayout({ ...L, scale: 1 }), position: H.pos };
      case "get_clipper": return { running: true, installed: true, folder: "E:\\Videos\\Clips", settings: H.clip || (H.clip = {
        watermark: true, cursor: true, toastInClips: true, islandInClips: true, fps: 60, quality: "high", defaultSeconds: 30, sounds: true, saveDir: "",
        micTrack: false, gameNames: true, gameFolders: false }) };
      case "set_clipper": Object.assign(H.clip, args[0]); return H.call(win, "get_clipper", []);
      case "start_clipper": case "pick_folder": return null;
      case "get_location": return { location: { name: "Toronto", label: "Toronto, Ontario, Canada" }, method: 2, school: 0 };
      case "set_location": return H.call(win, "get_location", []);
      case "search_city": return [{ label: "Toronto, Ontario, Canada" }];
      case "get_update": case "check_update": return { current: "0.1.3", latest: "0.1.3", available: false, checked: true, auto: true };
      case "set_auto_update": return H.call(win, "get_update", []);
      case "open_release": return true;
      case "get_extra": return { ...extra, extensions };
      case "set_extra": Object.assign(extra, args[0] || {}); if ((args[0] || {}).prompter != null) prompter = args[0].prompter; return { ...extra, extensions };
      case "agents_connect": extra.agents.connected = !!args[0]; return extra.agents;
      case "profile_save": if (!extra.profiles.includes(args[0])) extra.profiles.push(args[0]); H.profiles = H.profiles || {}; H.profiles[args[0]] = { ...L }; return extra.profiles;
      case "profile_load": if (H.profiles && H.profiles[args[0]]) setLayout(H.profiles[args[0]]); extra.activeProfile = args[0]; return { ...L };
      case "profile_delete": extra.profiles = extra.profiles.filter((p) => p !== args[0]); return extra.profiles;
      case "theme_code": return btoa(JSON.stringify(Object.fromEntries(Object.entries(L).filter(([k]) => H.LOOK.includes(k)))));
      case "theme_apply": try { return setLayout({ ...L, ...JSON.parse(atob(String(args[0]).trim())) }); } catch { return null; }
      case "export_settings": log("would save Hop settings.json to the Desktop"); return "C:\\Users\\you\\Desktop\\Hop settings.json";
      case "import_settings": return null;
      case "diagnostics": log("would zip the logs to the Desktop"); return "C:\\Users\\you\\Desktop\\Hop diagnostics.zip";
      case "lastfm_login": extra.lastfm = { user: args[0], connected: true }; return extra.lastfm;
      case "play_sound": beep(args[0]); return true;
      default:
        log("(no demo answer for " + name + ")");
        return null;
    }
  };

  // ---------------------------------------------------------------- the demo page's buttons
  const soon = (mins) => Date.now() + mins * 60000;
  H.demo = {
    nextSong: () => H.call(null, "playback", ["next"]),
    togglePlay: () => H.call(null, "playback", [playing ? "pause" : "play"]),
    nothing: () => { nothing = !nothing; push(); },
    notif: () => ev("notif", { app: "Discord", title: "preinfection", text: "yo did you push the notch build? the clip from last night is crazy" }),
    mail: () => ev("notif", { app: "Outlook", title: "Your Porkbun renewal", text: "gethop.lol renews on 2027-09-30" }),
    agentWork: () => { agents.sessions[0].status = "work"; agents.sessions[0].detail = "Running tests/test_layout.py"; ev("agents", agents); },
    agentAsk: () => {
      agents.sessions[0].status = "ask"; agents.sessions[0].detail = "Wants to run a command"; ev("agents", agents);
      ev("agentAsk", { kind: "permission", id: "p1", tool: "claude", name: "hop", verb: "run", summary: "python -m pytest tests/test_layout.py -q" });
    },
    agentQuestion: () => ev("agentAsk", { kind: "question", id: "q1", tool: "claude", name: "hop", question: "Which installer version?", options: ["0.1.3", "0.2.0", "Skip for now"] }),
    agentPlan: () => ev("agentAsk", { kind: "plan", id: "pl1", tool: "claude", name: "hop", plan: "## Plan\n1. Add Style: Notch / Pill to the Island tab\n2. Snap to the top edge in notch mode\n3. Tests for sizes and gaps\n4. Build HopIsland only and copy it over the install\n5. No installer until asked" }),
    agentDone: () => { agents.sessions[0].status = "done"; agents.sessions[0].detail = "Finished: 688 tests passed"; ev("agents", agents);
      ev("agentAsk", { kind: "done", session: "s1", tool: "claude", name: "hop", summary: "688 layout tests passed. Committed on the next branch." }); },
    agentEdit: () => ev("agentEdit", { tool: "claude", file: "island/ui/features.js", plus: 42, minus: 7 }),
    timer10: () => { if (islandWin && islandWin.__hopTimer) islandWin.__hopTimer.start(10000); },
    calendar: () => { H.calendar = [{ uid: "e" + Date.now(), title: "Design review: Hop 0.1.3", start: soon(1.05), end: soon(31), location: "Google Meet", link: "https://meet.google.com/abc-defg-hij" },
                                     { uid: "e2", title: "Gym", start: soon(180), end: soon(240), location: "" }]; ev("calendar", H.calendar); },
    download: () => ev("download", { name: "HopSetup-0.1.3.exe", size: "103 MB", path: "C:\\Users\\you\\Downloads\\HopSetup-0.1.3.exe" }),
    snip: () => ev("snip", { thumb: thumb("#232526", "#414345", "Screenshot"), size: "1920 × 1080", name: "Screenshot 2026-10-03 170512.png", path: "C:\\demo\\shot.png" }),
    rain: () => ev("rain", { title: "Rain in about 15 min", text: "Toronto · 2.1 mm over the next hour" }),
    reminder: () => ev("reminder", { title: "Stretch", text: "Every 45 min" }),
    caps: () => { H.caps = !H.caps; ev("caps", H.caps); },
    wifi: () => ev("wifi", { ssid: "BELL892" }),
    focus: () => { H.focus = !H.focus; ev("focus", H.focus); },
    game: () => { H.gaming = !H.gaming; ev("game", H.gaming); log("game mode", H.gaming ? "on (pop-ups held)" : "off"); },
    mic: () => { H.mic = !H.mic; ev("privacy", { mic: H.mic ? ["Discord"] : [], cam: [] }); },
    cam: () => { H.cam = !H.cam; ev("privacy", { mic: [], cam: H.cam ? ["Camera"] : [] }); },
    clip: () => js("__islandClip", { name: "Roblox 2026-10-03 17-02-11 (30s).mp4", path: "C:\\demo\\clip.mp4", url: "/demo/media/sample.mp4", seconds: 30, kind: "clip", game: "Roblox" }),
    goal: () => { const m = (s) => ({ id: "m1", league: "Premier League", home: "Arsenal", away: "Chelsea", hs: s, as: 1, status: "67'", live: true, state: "in" });
                  ev("sports", [m(1)]); setTimeout(() => ev("sports", [m(2)]), 400); },
    bt: () => js("__islandActivity", { kind: "bt", name: "Galaxy Buds2 Pro", pct: 78 }),
    charge: () => js("__islandActivity", { kind: "charge", pct: 64 }),
    low: () => js("__islandActivity", { kind: "low", pct: 14 }),
    update: () => ev("update", { latest: "0.1.4", state: "ready" }),
    drop: () => ev("drop", { name: "trip-photos.zip", path: "C:\\demo\\trip-photos.zip" }),
    prayer: () => { prayerData = prayers(); const d = new Date(); const x = new Date(d.getTime() + 61000);
      const key = Object.keys(prayerData.today).find((k) => k !== "Sunrise" && prayerData.today[k] === `${String(new Date(d.getTime() + 14 * 60000).getHours()).padStart(2, "0")}:${String(new Date(d.getTime() + 14 * 60000).getMinutes()).padStart(2, "0")}`) || "Asr";
      prayerData.today[key] = `${String(x.getHours()).padStart(2, "0")}:${String(x.getMinutes()).padStart(2, "0")}`; js("__islandPrayers", prayerData); js("__islandPrayerReset"); log(key, "in 1 minute"); },
    rec: () => { H.rec = H.rec ? 0 : Date.now(); js("__islandRec", true, H.rec); },
    pin: () => { H.pinned = !H.pinned; if (H.setOpen) H.setOpen(H.pinned); },
  };
  H.LOOK = ["style", "pillW", "pillH", "notchW", "notchH", "openW", "openH", "radiusClosed", "radiusOpen", "topGap", "bg", "bgOpacity", "bgStyle",
            "border", "borderColor", "borderOpacity", "glow", "accentMode", "accentColor", "font", "anim", "bounce", "speed", "slotLeft", "slotCenter", "slotRight", "customCss"];

  H.openSettings = () => {
    document.body.classList.add("settings-open");
    const f = frames().settings;
    if (!f.src) f.src = "/island/ui/settings.html";
  };
  H.closeSettings = () => document.body.classList.remove("settings-open");

  // ---------------------------------------------------------------- start
  H.ready = fetch("/demo/layout.json").then((r) => r.json()).then((d) => {
    L = d.layout; H.base = { ...d.layout }; SPEC = d.spec; POPDEF = d.popupDefaults;
    prayerData = prayers();
    placeIsland();
    setInterval(() => { if (playing && !nothing) { const p = pb(); if (p && p.progressMs >= p.durationMs) H.call(null, "playback", ["next"]); } }, 1000);
    setInterval(() => ev("net", { down: 2.4e6 + Math.random() * 6e6, up: 3e5 }), 2000);
  });
})();
