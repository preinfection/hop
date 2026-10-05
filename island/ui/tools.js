// Tools (0.1.5): the command palette, rain radar, highlights by game,
// auto-clip, and where the music is coming from. They open as a sheet over
// the open island, from the Tools button in the top bar (or Ctrl+K for the
// palette). Everything here plugs into the island through window.__hop,
// __hopEvent and __islandPush, and asks the host for things with api.call.
(() => {
  const H = window.__hop;
  if (!H || window.__islandPreview) return;
  const { api, $, esc, island } = H;
  const call = (name, ...args) => Promise.resolve(api.call(name, ...args)).catch(() => null);
  const store = {
    get: (k, d) => { try { const v = localStorage.getItem("hop.tools." + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
    set: (k, v) => { try { localStorage.setItem("hop.tools." + k, JSON.stringify(v)); } catch {} },
  };
  Object.assign(window.__hopIcons || {}, {
    bolt: '<path d="M13 3v7h6l-8 11v-7H5l8-11"/>',
    command: '<path d="M7 9a2 2 0 1 1 2-2v10a2 2 0 1 1-2-2h10a2 2 0 1 1-2 2V7a2 2 0 1 1 2 2H7"/>',
    "layout-grid": '<path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z"/>',
    "cloud-rain": '<path d="M7 18a4.6 4.4 0 0 1 0-9 5 4.5 0 0 1 11 2h1a3.5 3.5 0 0 1 0 7"/><path d="M11 13v2m0 3v2m4-5v2m0 3v2"/>',
    "player-pause": '<rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/>',
    "player-skip-forward": '<path d="M4 5v14l12-7zM20 5v14"/>',
    "player-skip-back": '<path d="M20 5v14L8 12zM4 5v14"/>',
    trash: '<path d="M4 7h16M10 11v6M14 11v6M5 7l1 12a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2l1-12M9 7V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v3"/>',
    "volume": '<path d="M15 8a5 5 0 0 1 0 8M17.7 5a9 9 0 0 1 0 14M6 15H4a1 1 0 0 1-1-1v-4a1 1 0 0 1 1-1h2l3.5-4.5A.8.8 0 0 1 11 5v14a.8.8 0 0 1-1.5.5z"/>',
  });
  const ICON = window.ICON;

  // ---------------------------------------------------------------- the sheet over the open island
  const sheet = document.createElement("div");
  sheet.className = "toolSheet";
  sheet.innerHTML = `<div class="tsHead"><span class="tsTitle"></span><button class="tsClose" title="Close">${ICON("x", 15)}</button></div><div class="tsBody"></div>`;
  (document.querySelector(".full") || island).appendChild(sheet);
  sheet.querySelector(".tsClose").onclick = () => close();
  const body = sheet.querySelector(".tsBody");
  let gen = 0;                                     // each open() starts a new generation; old timers check it and stop
  function open(title, html, after) {
    gen++;
    if (!H.isOpen() && window.__islandHover) window.__islandHover(true);
    call("hold_open", true);
    sheet.querySelector(".tsTitle").textContent = title;
    body.innerHTML = html;
    island.classList.add("toolOn");
    if (after) after(body, gen);
  }
  function close() { gen++; island.classList.remove("toolOn"); call("hold_open", false); }
  addEventListener("keydown", (e) => { if (e.key === "Escape" && island.classList.contains("toolOn")) close(); });

  // the Tools button in the top bar
  const TOOLS = [["palette", "Command palette", "command"], ["radar", "Rain radar", "cloud-rain"],
                 ["highlights", "Highlights", "photo"], ["autoclip", "Auto-clip", "bolt"]];
  function menu() {
    open("Tools", `<div class="tsGrid">${TOOLS.map(([id, name, ic]) => `<button class="tsTile" data-tool="${id}">${ICON(ic, 20)}<span>${esc(name)}</span></button>`).join("")}</div>`,
      (b) => { b.onclick = (e) => { const t = e.target.closest("[data-tool]"); if (t) FN[t.dataset.tool](); }; });
  }
  const addBar = () => {
    const right = document.querySelector(".topbar .tb-right");
    if (!right || right.querySelector(".tbTools")) return;
    const b = document.createElement("button");
    b.className = "tb tbTools"; b.title = "Tools (Ctrl+K: command palette)"; b.innerHTML = ICON("layout-grid", 15);
    b.onclick = menu;
    right.prepend(b);
  };
  addBar(); setInterval(addBar, 2000);

  // a small card saying what a command did
  const done = (text, sub = "") => H.showCard(`<div class="ic-sq" style="background:#2c2c2e">${ICON("check", 20)}</div><div class="ct"><div class="t">${esc(text)}</div>${sub ? `<div class="s">${esc(sub)}</div>` : ""}</div>`, 300, 72, 2200);

  // ================================================================ COMMAND PALETTE (Ctrl+K)
  const timer = (min, label) => [label, "alarm", () => { if (window.__hopTimer) { window.__hopTimer.start(min * 60000); done(label + " started"); } }];
  const look = (ch, text) => () => Promise.resolve(api.call("set_layout", { ...H.layout(), ...ch })).then(() => done(text));
  function vol(d, mute) {
    if (!H.vol) return;
    if (mute) H.vol.muted = !H.vol.muted;
    else { H.vol.level = Math.max(0, Math.min(1, Math.round((H.vol.level + d) * 100) / 100)); H.vol.muted = false; }
    H.paintVol && H.paintVol(); H.sendVol && H.sendVol(H.vol.level, H.vol.muted);
    done(mute ? (H.vol.muted ? "Muted" : "Unmuted") : `Volume ${Math.round(H.vol.level * 100)}%`);
  }
  const ACTIONS = () => [
    ["Play / pause", "player-pause", () => api.playback(H.playback() && H.playback().isPlaying ? "pause" : "play")],
    ["Next song", "player-skip-forward", () => api.playback("next")],
    ["Previous song", "player-skip-back", () => api.playback("previous")],
    ["Volume up", "volume", () => vol(+0.1)], ["Volume down", "volume", () => vol(-0.1)], ["Mute / unmute", "volume", () => vol(0, true)],
    ["Save a clip (F8)", "photo", () => call("save_clip").then((ok) => done(ok ? "Clip saved" : "Hop Clipper isn't running", ok ? "the last moments, like F8" : "start it from the Start menu"))],
    ["Start / stop recording", "camera", () => api.record(!island.classList.contains("recording"))],
    ["Open the clips folder", "folder", () => api.openClipsFolder()],
    ["Highlights", "photo", () => highlights()], ["Auto-clip", "bolt", () => autoclip()], ["Rain radar", "cloud-rain", () => radar()],
    timer(5, "5-minute timer"), timer(10, "10-minute timer"), timer(15, "15-minute timer"), timer(25, "25-minute focus"), timer(50, "50-minute focus"),
    ...(H.layout().boards || []).map((bd, i) => [`Go to ${bd.name}`, "layout-grid", () => { close(); H.setPage(i); }]),
    ["Notch", "layout-grid", look({ style: "notch" }, "Switched to the notch")], ["Pill", "layout-grid", look({ style: "pill" }, "Switched to the pill")],
    ["New design (widgets)", "layout-grid", look({ pageMode: "boards" }, "Switched to the new design")],
    ["Classic design (one thing per page)", "layout-grid", look({ pageMode: "pages" }, "Switched to the classic design")],
    ["Quiet hours on / off", "moon", () => look({ quiet: !H.layout().quiet }, H.layout().quiet ? "Quiet hours off" : "Quiet hours on")()],
    ["Snap to the top middle", "layout-grid", () => window.__hopSnap && window.__hopSnap()],
    ["Open settings", "settings", () => api.openSettings()],
    ["Check for updates", "download", () => call("check_update").then((u) => done(u && u.available ? `Hop ${u.latest} is out` : "Hop is up to date", u && u.available ? "Settings → Updates" : ""))],
    ["Restart Hop Island", "refresh", () => api.restartApp()],
    ["Open gethop.lol", "external-link", () => call("open_url", "https://gethop.lol")],
  ];
  function palette() {
    const acts = ACTIONS();
    open("Command palette", `<input class="tsIn palIn" placeholder="Type a command…" spellcheck="false" autocomplete="off"><div class="palList scrolls"></div>`, (b) => {
      const inp = b.querySelector(".palIn"), list = b.querySelector(".palList");
      let sel = 0, shown = acts, byKey = false, mx = -1, my = -1;
      // the mouse picks too: the row under it is the one Enter runs, also while the wheel scrolls
      list.onscroll = () => { if (mx < 0) return; const el = document.elementFromPoint(mx, my); if (el && list.contains(el)) list.onmousemove({ target: el, clientX: mx, clientY: my }); };
      list.onmousemove = (e) => {
        mx = e.clientX; my = e.clientY;
        const r = e.target.closest("[data-i]"); if (!r || +r.dataset.i === sel) return;
        sel = +r.dataset.i;
        list.querySelectorAll(".palRow").forEach((x) => x.classList.toggle("on", +x.dataset.i === sel));
      };
      const score = (t, q) => { t = t.toLowerCase(); q = q.toLowerCase().trim(); if (!q) return 1; if (t.includes(q)) return 2; let i = 0; for (const ch of t) if (ch === q[i]) i++; return i === q.length ? 1 : 0; };
      const draw = () => {
        shown = acts.map((a) => [a, score(a[0], inp.value)]).filter((x) => x[1]).sort((x, y) => y[1] - x[1]).map((x) => x[0]);
        sel = Math.min(sel, Math.max(0, shown.length - 1));
        list.innerHTML = shown.map((a, i) => `<div class="palRow${i === sel ? " on" : ""}" data-i="${i}">${ICON(a[1], 15)}<span>${esc(a[0])}</span><kbd>Enter</kbd></div>`).join("") || `<p class="tsP">Nothing matches.</p>`;
        const on = list.querySelector(".palRow.on");
        if (on && byKey) on.scrollIntoView({ block: "nearest" });
        byKey = false;
      };
      const run = (i) => { const a = shown[i]; if (!a) return; close(); a[2](); };
      inp.oninput = () => { sel = 0; draw(); };
      inp.onkeydown = (e) => {
        if (e.key === "ArrowDown") { sel = Math.min(shown.length - 1, sel + 1); byKey = true; draw(); e.preventDefault(); }
        if (e.key === "ArrowUp") { sel = Math.max(0, sel - 1); byKey = true; draw(); e.preventDefault(); }
        if (e.key === "Enter") run(sel);
      };
      list.onclick = (e) => { const r = e.target.closest("[data-i]"); if (r) run(+r.dataset.i); };
      draw(); setTimeout(() => inp.focus(), 50);
    });
  }
  addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); palette(); } });

  // ================================================================ HIGHLIGHTS: the last two weeks of clips, by game
  const plays = () => store.get("plays", {});
  function highlights() {
    open("Highlights", `<p class="tsP">Loading your clips…</p>`, async (b, g) => {
      const clips = (await call("all_clips")) || [];
      if (g !== gen) return;
      if (!clips.length) { b.innerHTML = `<p class="tsP">No clips from the last two weeks yet. Press F8 in a game and they show up here, by game.</p>`; return; }
      const P = plays();
      // the game: Hop Clipper's folder per game, or the start of the file name ("Roblox 2026-10-01 ...")
      clips.forEach((c) => { if (!c.game) { const m = /^(.+?)\s+\d{4}-\d{2}-\d{2}/.exec(c.name || ""); c.game = m && !/^(clip|recording)$/i.test(m[1]) ? m[1] : "Other"; } });
      const games = [...new Set(clips.map((c) => c.game))];
      b.innerHTML = games.map((gm) => {
        const mine = clips.filter((c) => c.game === gm);
        return `<div class="hlGame"><div class="hlHead">${esc(gm)}<span>${mine.length} clip${mine.length === 1 ? "" : "s"}</span></div><div class="hlRow">${mine.map((c) =>
          `<div class="hlClip" data-p="${esc(c.path)}" style="${c.thumb ? `background-image:url(${c.thumb})` : ""}"><span class="hlLen">${c.seconds ? c.seconds + "s" : ""}</span>
            <span class="hlName">${esc(H.ago ? H.ago(c.at) : "")}</span><span class="hlPlays">${ICON("player-play", 10)} ${P[c.path] || 0}</span>
            <button class="hlDel" data-del="${esc(c.path)}" title="Move to the Recycle Bin">${ICON("trash", 12)}</button></div>`).join("")}</div></div>`;
      }).join("");
      b.onclick = async (e) => {
        const d = e.target.closest("[data-del]");
        if (d) { e.stopPropagation(); if (await call("delete_clip", d.dataset.del)) highlights(); return; }
        const t = e.target.closest("[data-p]");
        if (!t) return;
        const c = clips.find((x) => x.path === t.dataset.p);
        const p = plays(); p[c.path] = (p[c.path] || 0) + 1; store.set("plays", p);
        close();
        window.__islandClip && window.__islandClip({ ...c, game: c.game || "" });
      };
    });
  }

  // ================================================================ AUTO-CLIP: Hop Clipper saves by itself when chat says "gg"
  const AUTO = () => store.get("auto", { on: false, words: "gg, clutch, nice, ace", apps: "discord" });
  function autoclip() {
    const a = AUTO();
    open("Auto-clip", `<p class="tsP">Hop Clipper saves the last moments by itself when a notification says one of your words, like a friend typing “gg” in Discord. Needs Hop Clipper running.</p>
      <label class="tsRow"><span><b>Auto-clip</b><small>save a clip on these words</small></span><input type="checkbox" data-k="on"${a.on ? " checked" : ""}></label>
      <label class="tsField"><span>Words</span><input class="tsIn" data-k="words" value="${esc(a.words)}" spellcheck="false"></label>
      <label class="tsField"><span>From apps</span><input class="tsIn" data-k="apps" value="${esc(a.apps)}" placeholder="discord, whatsapp (empty: any)" spellcheck="false"></label>`,
      (b) => { b.onchange = b.oninput = (e) => { const k = e.target.dataset.k; if (!k) return; const x = AUTO(); x[k] = e.target.type === "checkbox" ? e.target.checked : e.target.value; store.set("auto", x); }; });
  }
  const list = (s) => String(s || "").split(",").map((x) => x.trim().toLowerCase()).filter(Boolean);
  const reEsc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  let lastAuto = 0;
  const origEvent = window.__hopEvent;
  window.__hopEvent = (kind, data) => {
    origEvent(kind, data);
    if (kind !== "notif") return;
    const a = AUTO();
    if (!a.on || Date.now() - lastAuto < 20000) return;
    const apps = list(a.apps), words = list(a.words);
    if (!words.length || (apps.length && !apps.some((x) => String(data.app || "").toLowerCase().includes(x)))) return;
    const m = `${data.title || ""} ${data.text || ""}`.match(new RegExp(`\\b(${words.map(reEsc).join("|")})\\b`, "i"));
    if (!m) return;
    lastAuto = Date.now();
    call("save_clip").then((ok) => ok && H.showCard(`<div class="ic-sq" style="background:#ff9f0a">${ICON("bolt", 20)}</div><div class="ct"><div class="t">Auto-clip saved</div><div class="s">after “${esc(m[1])}” in ${esc(data.app || "a message")}</div></div>`, 300, 72, 3000));
  };

  // ================================================================ WHERE THE MUSIC COMES FROM (YouTube in Brave, Spotify...)
  const SOURCES = [[/spotify/i, "Spotify", "#1db954"], [/brave/i, "Brave", "#fb542b"], [/chrome/i, "Chrome", "#4285f4"], [/msedge|edge/i, "Edge", "#0a84ff"],
                   [/firefox|308046B0AF4A39CB/i, "Firefox", "#ff7139"], [/opera/i, "Opera", "#ff1b2d"], [/vlc/i, "VLC", "#ff8800"],
                   [/applemusic|itunes/i, "Apple Music", "#fa2d48"], [/zune|media ?player/i, "Media Player", "#0a84ff"], [/tidal/i, "TIDAL", "#fff"], [/deezer/i, "Deezer", "#a238ff"]];
  const BROWSERS = new Set(["Brave", "Chrome", "Edge", "Firefox", "Opera"]);
  function sourceOf(pb) {
    const hit = SOURCES.find(([re]) => re.test(pb.app || ""));
    if (!hit) return null;
    let name = hit[1];
    // in a browser, say the site when it's clearly YouTube (its music channels end in " - Topic")
    if (BROWSERS.has(name) && (/ - Topic$|VEVO$/i.test(pb.artist || "") || /youtube/i.test(`${pb.album || ""} ${pb.track || ""}`))) name = `YouTube · ${name}`;
    else if (BROWSERS.has(name)) name = `in ${name}`;
    return [name, hit[2]];
  }
  const origPush = window.__islandPush;
  if (origPush) window.__islandPush = (st) => {
    origPush(st);
    const pb = st && st.playback, s = pb && !pb.empty ? sourceOf(pb) : null;
    document.querySelectorAll(".island .meta").forEach((meta) => {
      let tag = meta.querySelector(".srcTag");
      if (!tag) { tag = document.createElement("span"); tag.className = "srcTag"; meta.appendChild(tag); }
      tag.hidden = !s;
      if (s) { tag.textContent = s[0]; tag.style.setProperty("--c", s[1]); }
    });
  };

  // ================================================================ RAIN RADAR, like The Weather Network's
  // Your Hop city (asked here if there isn't one yet), a map you drag and zoom,
  // and a time bar with a tick per 10 minutes and the time under it.
  const loadLeaflet = () => window.L ? Promise.resolve() : new Promise((res, rej) => {
    const css = document.createElement("link"); css.rel = "stylesheet"; css.href = "./vendor/leaflet/leaflet.css"; document.head.appendChild(css);
    const js = document.createElement("script"); js.src = "./vendor/leaflet/leaflet.js"; js.onload = res; js.onerror = rej; document.head.appendChild(js);
  });
  async function radar() {
    const loc = ((await call("get_location")) || {}).location;
    if (!loc || loc.lat == null) {
      return open("Rain radar", `<p class="tsP">Which city? It becomes Hop's city for the weather and prayer times too.</p>
        <div class="rdAsk"><input class="tsIn" id="rdCity" placeholder="City, e.g. Toronto" spellcheck="false"><button class="tsBtn" id="rdGo">Show radar</button></div><p class="tsP" id="rdErr"></p>`, (b) => {
        const go = async () => {
          const v = b.querySelector("#rdCity").value.trim(); if (!v) return;
          b.querySelector("#rdErr").textContent = "Looking it up…";
          const found = (await call("search_city", v)) || [];
          if (!found.length) { b.querySelector("#rdErr").textContent = "No place by that name (or you're offline)."; return; }
          await call("set_location", found[0]);
          radar();
        };
        b.querySelector("#rdGo").onclick = go;
        b.querySelector("#rdCity").onkeydown = (e) => { if (e.key === "Enter") go(); };
        setTimeout(() => b.querySelector("#rdCity").focus(), 50);
      });
    }
    const city = { name: loc.name || loc.label || "Your city", lat: +loc.lat, lon: +loc.lon };
    open(`Rain radar · ${city.name}`, `<div class="rdWrap"><div class="rdMap" id="rdMap"></div>
      <div class="rdZoom"><button id="rdIn" title="Zoom in">+</button><button id="rdOut" title="Zoom out">−</button></div>
      <div class="rdBar"><button class="rdPlay" id="rdPlay" title="Play / pause">${ICON("player-play", 14)}</button>
        <div class="rdTrack" id="rdTrack"><div class="rdTicks" id="rdTicks"></div><div class="rdHandle" id="rdHandle"><span id="rdNow"></span></div></div></div></div>`, async (b, g) => {
      try { await loadLeaflet(); } catch { b.querySelector(".rdWrap").innerHTML = `<p class="tsP">The map couldn't load.</p>`; return; }
      if (g !== gen) return;
      const el = b.querySelector("#rdMap");
      // the island turns pages on the wheel: on the map the wheel zooms instead
      el.addEventListener("wheel", (e) => e.stopPropagation(), { passive: true });
      const map = L.map(el, { center: [city.lat, city.lon], zoom: 7, zoomControl: false, attributionControl: false, minZoom: 3, maxZoom: 11 });
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { className: "rdOsm", maxZoom: 11 }).addTo(map);
      L.circleMarker([city.lat, city.lon], { radius: 5, color: "#fff", weight: 2, fillColor: "#fff", fillOpacity: 1 }).addTo(map);
      b.querySelector("#rdIn").onclick = () => map.zoomIn();
      b.querySelector("#rdOut").onclick = () => map.zoomOut();
      let d;
      try { d = await (await fetch("https://api.rainviewer.com/public/weather-maps.json")).json(); }
      catch { b.querySelector("#rdTicks").innerHTML = `<span class="rdErr">The radar is unavailable offline</span>`; return; }
      if (g !== gen) return;
      const frames = [...d.radar.past, ...(d.radar.nowcast || [])];
      const nowIdx = d.radar.past.length - 1;
      // RainViewer draws radar up to zoom 7; past that its tiles only say "Zoom Level".
      // maxNativeZoom keeps asking for zoom-7 tiles and stretches them, so the map still zooms in.
      const layers = frames.map((f) => L.tileLayer(`${d.host}${f.path}/256/{z}/{x}/{y}/2/1_1.png`, { opacity: 0, zIndex: 5, maxNativeZoom: 7, maxZoom: 11 }).addTo(map));
      const t = (f) => new Date(f.time * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
      b.querySelector("#rdTicks").innerHTML = frames.map((f, k) => `<i style="left:${(k / (frames.length - 1)) * 100}%" class="${k === nowIdx ? "now" : k > nowIdx ? "ahead" : ""}">${k % 2 === 0 || k === nowIdx ? `<b>${k === nowIdx ? "Now" : t(f)}</b>` : ""}</i>`).join("");
      let cur = -1, playing = true;
      const show = (k) => {
        if (k === cur) return;
        layers.forEach((l, n) => l.setOpacity(n === k ? 0.82 : 0));
        cur = k;
        const h = b.querySelector("#rdHandle");
        h.style.left = `${(k / (frames.length - 1)) * 100}%`;
        b.querySelector("#rdNow").textContent = (k > nowIdx ? "+" : "") + t(frames[k]);
        h.classList.toggle("ahead", k > nowIdx);
      };
      const loop = () => { if (g !== gen) return; if (playing) show((cur + 1) % frames.length); setTimeout(loop, 650); };
      const play = (on) => { playing = on; b.querySelector("#rdPlay").innerHTML = ICON(on ? "player-pause" : "player-play", 14); };
      b.querySelector("#rdPlay").onclick = () => play(!playing);
      const track = b.querySelector("#rdTrack");
      const seek = (e) => { const r = track.getBoundingClientRect(); show(Math.round(Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * (frames.length - 1))); };
      track.addEventListener("pointerdown", (e) => { play(false); track.setPointerCapture(e.pointerId); seek(e); track.onpointermove = seek; });
      track.addEventListener("pointerup", () => { track.onpointermove = null; });
      show(nowIdx); play(true); setTimeout(loop, 650);
      setTimeout(() => map.invalidateSize(), 60);
    });
  }

  const FN = { palette, radar, highlights, autoclip };
  window.__hopTools = { ...FN, menu, close };
})();
