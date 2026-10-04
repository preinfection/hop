// The island's newer half (0.1.3): your own look, the closed pill's three
// slots and what may take it over, pop-ups with per-kind settings (quiet
// hours, game mode, focus), and the pages added after 0.1.2: AI agents,
// timer, calendar, notifications, shelf, notes, sports, teleprompter,
// battery, and extensions. The host talks to it through one entry point,
// window.__hopEvent(kind, data); it asks the host for things with
// api.call(name, ...args).
(() => {
  const H = window.__hop;
  if (!H) return;
  const { api, $, esc, island } = H;
  const call = (name, ...args) => Promise.resolve(api.call(name, ...args)).catch(() => null);
  const L = () => H.layout() || {};
  const root = document.documentElement;
  const full = document.querySelector(".full");
  const dots = document.querySelector(".pg-dots");
  const now = () => H.nowMs();
  const hm = (d) => `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  const timeFmt = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" });
  const store = {
    get(k, d) { try { const v = localStorage.getItem("hop." + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem("hop." + k, JSON.stringify(v)); } catch {} },
  };
  const state = {
    gaming: false, focus: false, mic: [], cam: [], agents: [], usage: null, calendar: [], history: store.get("history", []),
    shelf: [], sports: [], battery: null, net: null, clipStats: null, held: [], extensions: [], prompter: { text: "", playing: false },
  };

  // ================================================================ LOOK
  const FONTS = {
    inter: '"Inter Island", "Segoe UI Variable Text", system-ui, sans-serif',
    segoe: '"Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif',
    outfit: '"Outfit", "Segoe UI Variable Text", system-ui, sans-serif',
    mono: '"Cascadia Mono", "Consolas", ui-monospace, monospace',
    system: 'system-ui, sans-serif',
  };
  const rgb = (hex) => { const n = parseInt((hex || "#000000").slice(1), 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; };
  const rgba = (hex, a) => `rgba(${rgb(hex).join(", ")}, ${a})`;
  function darkEnough([r, g, b], maxL = 0.22) {
    r /= 255; g /= 255; b /= 255;
    const mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2;
    if (l <= maxL) return [r * 255, g * 255, b * 255].map(Math.round);
    const d = mx - mn, sat = d === 0 ? 0 : d / (1 - Math.abs(2 * l - 1));
    let h = 0;
    if (d) h = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
    h *= 60;
    const c = (1 - Math.abs(2 * maxL - 1)) * sat, x = c * (1 - Math.abs(((h / 60) % 2) - 1)), m = maxL - c / 2;
    const [rr, gg, bb] = h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x] : h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
    return [rr + m, gg + m, bb + m].map((v) => Math.round(v * 255));
  }
  // "Copy as CSS" (settings): the island's whole look as CSS anyone can paste
  // into Custom CSS; !important so it wins over the settings it replaces
  function themeCss() {
    // (the closed width is left out: the pill must still widen for activities)
    const Lx = L(), NL = "\n", get = (el, k) => el.style.getPropertyValue(k).trim();
    const rootVars = ["--h", "--open-w", "--open-h", "--r-closed", "--r-open", "--isl-font", "--dur", "--ease-w", "--spring"]
      .filter((k) => get(root, k)).map((k) => `  ${k}: ${get(root, k)} !important;`);
    const islVars = ["--isl-bg", "--isl-ring", "--isl-glow"].filter((k) => get(island, k)).map((k) => `  ${k}: ${get(island, k)} !important;`);
    if (Lx.accentMode === "custom") islVars.push(`  --accent: ${Lx.accentColor} !important;`);
    const shape = Lx.style === "notch"
      ? `.island { border-radius: 0 0 var(--r-closed) var(--r-closed) !important; }${NL}.island.open { border-radius: 0 0 var(--r-open) var(--r-open) !important; }`
      : `.island { border-radius: var(--r-closed) !important; }${NL}.island.open { border-radius: var(--r-open) !important; }`;
    return [`/* Hop Island theme (${Lx.style === "notch" ? "notch" : "pill"} style): paste into Settings > Profiles & themes > Custom CSS */`,
            ":root {", ...rootVars, "}", ".island {", ...islVars, "}", shape,
            Lx.anim === "reduced" ? ".island, .island * { transition-duration: 120ms !important; animation: none !important; }" : "",
            Lx.customCss || ""].filter(Boolean).join(NL) + NL;
  }
  window.addEventListener("message", (e) => { if (e.data && e.data.t === "themecss") e.source.postMessage({ t: "themecss", css: themeCss() }, "*"); });
  function applyLook(L) {
    const notch = L.style === "notch";
    const st = root.style;
    st.setProperty("--w", (notch ? L.notchW : L.pillW) + "px");
    fitW = 0; fitWide = 0;
    st.setProperty("--h", (notch ? L.notchH : L.pillH) + "px");
    st.setProperty("--w-wide", Math.max(notch ? L.notchW : 176, notch ? L.notchW : L.pillW) + "px");
    st.setProperty("--open-w", L.openW + "px");
    st.setProperty("--open-h", L.openH + "px");
    const rc = L.radiusClosed >= 0 ? L.radiusClosed : notch ? 10 : Math.round(L.pillH / 2);
    const ro = L.radiusOpen >= 0 ? L.radiusOpen : 24;                 // one rounding for the open island and every card
    st.setProperty("--r-card", Math.min(ro, 30) + "px");
    st.setProperty("--r-closed", rc + "px");
    st.setProperty("--r-open", ro + "px");
    const a = L.bgOpacity / 100;
    // the island's text is light: a light background would swallow it, so the
    // colour keeps its hue but is darkened to at most 22 % lightness
    const [r, g, b] = darkEnough(rgb(L.bg));
    const dark = `rgba(${r * 0.55 | 0}, ${g * 0.55 | 0}, ${b * 0.55 | 0}, ${a})`;
    const base = `rgba(${r}, ${g}, ${b}, ${a})`;
    island.style.setProperty("--isl-bg", L.bgStyle === "gradient" ? `linear-gradient(180deg, ${base}, ${dark})`
      : L.bgStyle === "tint" ? `linear-gradient(180deg, color-mix(in srgb, var(--accent) 22%, ${base}), ${base})`
      : base);
    island.style.setProperty("--isl-ring", L.border ? `inset 0 0 0 1px ${rgba(L.borderColor, L.borderOpacity / 100)}` : "0 0 0 0 transparent");
    island.style.setProperty("--isl-glow", L.glow ? "0 4px 22px -2px color-mix(in srgb, var(--accent) 55%, transparent)" : "0 0 0 0 transparent");
    st.setProperty("--isl-font", FONTS[L.font] || FONTS.inter);
    const k = 100 / (L.speed || 100);
    st.setProperty("--dur", Math.round((L.anim === "subtle" ? 300 : 420) * k) + "ms");
    const over = L.anim === "full" ? 1 + (L.bounce / 100) * 0.4 : 1;           // 0..100 -> no overshoot .. a big spring
    st.setProperty("--ease-w", `cubic-bezier(0.32, ${over.toFixed(2)}, 0.55, 1)`);
    st.setProperty("--spring", `cubic-bezier(0.32, ${over.toFixed(2)}, 0.55, 1)`);
    root.classList.toggle("motion-reduced", L.anim === "reduced");
    island.classList.toggle("no-sr", !L.shuffleRepeat);
    let css = document.getElementById("userCss");
    if (!css) { css = document.createElement("style"); css.id = "userCss"; document.head.appendChild(css); }
    if (css.textContent !== (L.customCss || "")) css.textContent = L.customCss || "";
  }

  // ================================================================ THE CLOSED PILL: three slots
  const mini = island.querySelector(".mini");
  const slotBox = {};
  for (const side of ["l", "c", "r"]) {
    const d = document.createElement("div");
    d.className = `slot sl-${side}`;
    mini.appendChild(d);
    slotBox[side] = d;
  }
  const holder = document.createElement("div");
  holder.hidden = true;
  mini.appendChild(holder);
  const sv = (cls, html = "") => { const s = document.createElement("span"); s.className = `sv sv-${cls}`; s.innerHTML = html; return s; };
  const NODES = {
    art: $("miniArt"), clock: $("clock"), bars: mini.querySelector(".bars"),
    timer: sv("timer"), agents: sv("agents"), net: sv("net"), battery: sv("battery"), weather: sv("weather"),
    date: sv("date"), rec: sv("rec"),
  };
  const live = document.createElement("span");
  live.className = "live-text";
  mini.appendChild(live);
  const pdot = document.createElement("i");
  pdot.className = "pdot";
  mini.appendChild(pdot);
  const pdot2 = document.createElement("i");          // the second dot: the mic, when the camera is on too
  pdot2.className = "pdot pdot2";
  mini.appendChild(pdot2);
  let slotKey = "";
  function applySlots(L) {
    const want = { l: L.slotLeft, c: L.slotCenter, r: L.slotRight };
    const key = JSON.stringify(want);
    if (key === slotKey) return;
    const first = !slotKey;
    slotKey = key;
    if (!first) {
      mini.classList.add("slots-out");
      clearTimeout(applySlots.t);
      applySlots.t = setTimeout(() => { placeSlots(want); requestAnimationFrame(() => mini.classList.remove("slots-out")); }, 120);
      return;
    }
    placeSlots(want);
  }
  function placeSlots(want) {
    Object.values(NODES).forEach((n) => holder.appendChild(n));
    const used = new Set();
    for (const side of ["l", "c", "r"]) {
      const v = want[side];
      if (v === "none" || used.has(v) || !NODES[v]) continue;      // one place per thing
      used.add(v);
      slotBox[side].appendChild(NODES[v]);
    }
    needs();
    paintSlots();
  }
  const slotted = (v) => [L().slotLeft, L().slotCenter, L().slotRight].includes(v);
  function paintSlots() {
    if (slotted("timer")) NODES.timer.textContent = liveClock() ? fmtTimer(liveClock()) : "–:––";
    if (slotted("agents")) {
      const ss = state.agents.slice(0, 4);
      NODES.agents.innerHTML = ss.length ? ss.map((s) => `<i class="${s.status}"></i>`).join("") : '<i></i>';
    }
    if (slotted("net")) {
      const n = state.net;
      NODES.net.innerHTML = n ? `${speed(n.down)}<span class="u">↓</span>` : "–";
    }
    if (slotted("battery")) {
      const b = state.battery;
      NODES.battery.innerHTML = b && b.pct != null ? `${b.pct}<span class="u">%</span>${b.charging ? ICON("battery-charging", 14) : ""}` : "–";
    }
    if (slotted("weather")) {
      const w = H.today() && H.today().weather;
      NODES.weather.innerHTML = w ? `${wxIcon(w.code, 15)}${Math.round(w.temp)}°` : "–";
    }
    if (slotted("date")) {
      NODES.date.textContent = new Date(now()).toLocaleDateString(undefined, { weekday: "short", day: "numeric" });
    }
    if (slotted("rec")) {
      const c = state.clipStats;
      NODES.rec.innerHTML = c ? `${c.running ? "<i></i>" : ""}${c.today ?? 0}<span class="u">today</span>` : "<i></i>";
    }
    fitPill();
  }
  // The pill grows to fit what its slots show (a weather slot beside a clock
  // with seconds is wider than 126 px), and the host's click area with it.
  let fitW = 0, fitWide = 0;
  function fitPill() {
    const Lx = L(); if (!Lx.pillW) return;
    const base = Lx.style === "notch" ? Lx.notchW : Lx.pillW;
    const l = slotBox.l.offsetWidth, r = slotBox.r.offsetWidth;
    const mid = (el) => (el && el.textContent.trim() ? el.scrollWidth : 0);
    const c = Math.max(slotBox.c.offsetWidth, island.classList.contains("live-on") ? mid(live) : 0,
                       island.classList.contains("recording") ? mid($("recTime")) : 0);
    const two = pdot2.classList.contains("mic");
    const dot = pdot.classList.contains("mic") || pdot.classList.contains("cam") ? (two ? 19 : 10) : 0;    // room for the privacy dot(s)
    island.classList.toggle("pdot-on", !!dot);
    island.classList.toggle("pdot-two", two);
    // .mini's 10 px padding + a 12 px gap between a side slot and the middle, the same on both sides
    const side = 10 + 12 + Math.max(l, r + dot);
    const fit = (cw) => Math.ceil(cw ? cw + 2 * side : 10 + l + 16 + r + dot + 10);
    const w = Math.max(base, Math.min(Lx.openW, fit(c)));
    // the prayer countdown ("Maghrib · 12m") is wider than the clock: its own width
    const wide = Math.max(Lx.style === "notch" ? base : 176, w, Math.min(Lx.openW, fit(mid($("prayTime")))));
    if (w === fitW && wide === fitWide) return;
    fitW = w; fitWide = wide;
    root.style.setProperty("--w", w + "px");
    root.style.setProperty("--w-wide", wide + "px");
    H.settlePill();
  }
  const speed = (bps) => bps >= 1e6 ? `${(bps / 1e6).toFixed(bps >= 1e7 ? 0 : 1)}M` : bps >= 1e3 ? `${Math.round(bps / 1e3)}K` : `${Math.round(bps || 0)}B`;
  const wxIcon = (c, size) => window.ICON(c === 0 ? "sun" : c <= 3 ? "cloud" : c <= 48 ? "cloud-fog" : c <= 67 ? "cloud-rain" : c <= 77 ? "snowflake" : c <= 82 ? "cloud-rain" : "cloud-storm", size || 20);

  // tell the host what to watch, so it only polls what is on screen
  let needKey = "";
  function needs() {
    const n = { net: slotted("net"), battery: slotted("battery") || pageOn("battery"), sports: pageOn("sports") || (L().teams || []).length > 0,
                calendar: pageOn("calendar"), clipStats: slotted("rec") || !!L().clipDot };
    const k = JSON.stringify(n);
    if (k === needKey) return;
    needKey = k;
    call("need", n);
  }
  const pageOn = (id) => (L().pages || []).includes(id) && !(L().hidden || []).includes(id);

  // ---- a live thing in the middle of the pill, by the priority in settings
  function liveTick() {
    const P = L().priority || [];
    let text = "", color = "#fff", pulse = false;
    for (const kind of P) {
      if (kind === "rec" && island.classList.contains("recording")) break;           // its own red clock shows
      if (kind === "prayer") {
        if (island.classList.contains("pray-show")) break;
        const r = ramadanText();
        if (r) { text = r; color = "var(--hop-amber)"; break; }
      }
      if (kind === "timer" && liveClock()) { text = fmtTimer(liveClock()); color = "var(--hop-orange)"; break; }
      // only once the card about it is gone (dismissed or missed) and it still waits: never in the card's way
      if (kind === "agent" && state.agents.some((s) => s.status === "ask") && !H.cardOn() && now() - (state.askSince || 0) > 4000) {
        text = "Agent waiting"; color = "var(--hop-orange)"; pulse = true; break;
      }
      if (kind === "focus" && state.focus) { text = "Focus"; color = "var(--hop-purple)"; break; }
    }
    if (live.textContent !== text) live.textContent = text;
    live.style.setProperty("--live-c", color);
    island.classList.toggle("live-on", !!text);
    island.classList.toggle("live-pulse", pulse);
    paintSlots();
  }
  setInterval(liveTick, 1000);

  // ---- privacy dot
  function paintPrivacy() {
    const on = L().micCamDot !== false;
    // camera green, microphone orange; both in use: both dots, side by side
    const want = on && state.cam.length ? " cam" : on && state.mic.length ? " mic" : "";
    const want2 = on && state.cam.length && state.mic.length ? " mic" : "";
    pdot.title = [...state.cam.map((a) => a + " · camera"), ...state.mic.map((a) => a + " · microphone")].join("\n");
    pdot2.title = pdot.title;
    clearTimeout(paintPrivacy.t);
    const fade = (el) => { if (/\b(mic|cam)\b/.test(el.className)) el.classList.add("out"); };
    if (!want2) fade(pdot2);
    if (want) {
      pdot.className = "pdot" + want;
      if (want2) { pdot2.className = "pdot pdot2" + want2; fitPill(); return; }
      paintPrivacy.t = setTimeout(() => { pdot2.className = "pdot pdot2"; fitPill(); }, 260);
      fitPill();
      return;
    }
    fade(pdot);                                      // going: fade the dots, then close the gap
    paintPrivacy.t = setTimeout(() => { pdot.className = "pdot"; pdot2.className = "pdot pdot2"; fitPill(); }, 260);
  }

  // ---- idle: tuck the pill away after a while with nothing happening
  let idleTimer = 0;
  function idleReset() {
    island.classList.remove("idle-line", "idle-fade");
    clearTimeout(idleTimer);
    const Lx = L();
    if (!Lx.idleHide) return;
    idleTimer = setTimeout(() => {
      if (H.isOpen() || H.cardOn()) return idleReset();
      island.classList.add(Lx.idleStyle === "fade" ? "idle-fade" : "idle-line");
    }, (Lx.idleAfter || 20) * 1000);
  }

  // ================================================================ POP-UPS
  const SOUND_OK = new Set(["tick", "pop", "chime", "bell"]);
  function quietNow() {
    const Lx = L();
    if (Lx.quietInFocus && state.focus) return true;
    if (!Lx.quiet) return false;
    const t = hm(new Date(now())), a = Lx.quietFrom, b = Lx.quietTo;
    return a === b ? false : a < b ? t >= a && t < b : t >= a || t < b;
  }
  function remember(item) {
    state.history.unshift({ ...item, at: now() });
    state.history = state.history.slice(0, 40);
    store.set("history", state.history);
    if (H.pageId() === "alerts") paintAlerts();
  }
  // Every pop-up goes through here: its kind's settings decide whether it
  // shows, for how long, and with which sound.
  function popup(kind, html, w, h, after, opts = {}) {
    const P = (L().popups || {})[kind] || { on: true, ms: 5000, sound: "none" };
    if (opts.history) remember(opts.history);
    if (!P.on) return false;
    const urgent = kind === "timer" || kind === "agent";
    if (!urgent && quietNow()) return false;
    if (!urgent && state.gaming && L().gameMode) { state.held.push([kind, html, w, h, after, opts]); return false; }
    H.showCard(html, w, h, opts.sticky ? 0 : P.ms, after);
    if (SOUND_OK.has(P.sound) && !quietNow()) call("sound", P.sound);
    idleReset();
    return true;
  }
  window.__hopPopup = popup;                   // for extensions and the demo

  // ---- a short activity on the closed pill (caps lock, Wi-Fi, focus, an agent's edit)
  let actTimer = 0;
  function activity(kind, w, html, ms) {
    const P = (L().popups || {})[kind];
    if (P && !P.on) return;
    if (quietNow()) return;
    clearTimeout(actTimer);
    {   // how wide it really is: lay the content out off to the side and measure it
      const probe = document.createElement("div");
      probe.className = "act-view act-probe";
      probe.innerHTML = html;
      island.appendChild(probe);
      const need = [...probe.children].reduce((n, c) => n + c.scrollWidth, 0) + 12 * 2 + 14;
      probe.remove();
      w = Math.min(Math.max(w, need), L().openW || 400);
    }
    w = Math.max(w, fitW || 0, parseFloat(getComputedStyle(root).getPropertyValue("--w")) || 0);
    island.classList.remove("act-out");
    H.growPill(w).then(() => {
      $("actView").innerHTML = html;
      island.style.setProperty("--act-w", w + "px");
      island.classList.add("act");
    });
    actTimer = setTimeout(() => {
      island.classList.add("act-out");
      actTimer = setTimeout(() => { island.classList.remove("act", "act-out"); H.settlePill(); }, 130);
    }, ms || (P && P.ms) || 2500);
    idleReset();
  }

  // ================================================================ PAGES (built here, ordered by the layout)
  const PAGE_HTML = {
    prayer: `<div class="ph"><span>Next prayer</span><span class="sub" id="pnCity"></span></div>
      <div class="pn-next"><span class="pn-name" id="pnName">–</span><span class="pn-at" id="pnAt"></span></div>
      <div class="pn-in" id="pnIn"></div><div class="pn-list" id="pnList"></div>`,
    weather: `<div class="wx-top"><span class="wx-ic" id="wxIc"></span><span class="wx-t" id="wxT">–</span></div>
      <div class="wx-desc" id="wxD"></div><div class="wx-city" id="wxCity"></div>
      <div class="wx-hl" id="wxHL"></div>`,
    agents: `<div class="ph"><span>Agents</span><span class="sub" id="agSub"></span></div>
      <div class="rows scrolls" id="agRows"></div><div class="usage" id="agUsage" hidden></div>`,
    timer: `<div class="tm-modes" id="tmModes"><button data-m="timer" class="on" title="Timer">${ICON("alarm", 13)}<span>Timer</span></button><button data-m="watch" title="Stopwatch">${ICON("clock-hour-4", 13)}<span>Stopwatch</span></button><button data-m="pomo" title="Focus">${ICON("moon", 13)}<span>Focus</span></button></div>
      <div class="tm-big" id="tmBig" title="Scroll to change">5:00</div><div class="tm-sub" id="tmSub"></div>
      <div class="tm-row" id="tmRow"></div>`,
    calendar: `<div class="ph"><span id="calHead">Today</span><button class="lnk" id="calOpen">Open calendar</button></div><div class="rows scrolls" id="calRows"></div>`,
    alerts: `<div class="ph"><span>Notifications</span><button class="lnk" id="alClear">Clear</button></div><div class="rows scrolls" id="alRows"></div>`,
    shelf: `<div class="ph"><span>Shelf</span><span class="sub" id="shSub">Drop files on the island</span></div><div class="sh-items" id="shItems"></div>`,
    notes: `<div class="ph"><span>Notes</span><span class="sub" id="ntSub">Saved</span></div><div class="notes scrolls" id="notes" contenteditable="plaintext-only" spellcheck="false" data-ph="Type anything…"></div>`,
    sports: `<div class="ph"><span>Scores</span><span class="sub" id="spSub"></span></div><div id="spRows" class="scrolls"></div>`,
    prompter: `<div class="pr-view" id="prView"><div class="pr-text" id="prText"></div></div>
      <div class="pr-bar"><button class="lnk" id="prPlay">Play</button><button class="lnk" id="prBack">Restart</button><span id="prInfo"></span></div>`,
    battery: `<div class="bt-top"><div class="bt-cell"><i id="btFill"></i></div><div class="bt-big" id="btPct">–</div>
      <div class="bt-meta" id="btMeta"></div></div><div id="btRows" style="margin-top:10px"></div>`,
  };
  const PAGE_CLASS = { timer: "pg-timer", prompter: "pg-prompter" };
  for (const [id, html] of Object.entries(PAGE_HTML)) {
    const pg = document.createElement("div");
    pg.className = `pg pg-x ${PAGE_CLASS[id] || ""}`;
    pg.dataset.id = id;
    pg.innerHTML = html;
    full.insertBefore(pg, dots);
  }
  // ---------------------------------------------------------------- PRAYER and WEATHER widgets
  const WX_TEXT = (c) => c === 0 ? "Clear" : c <= 2 ? "Partly cloudy" : c === 3 ? "Cloudy" : c <= 48 ? "Fog" : c <= 57 ? "Drizzle"
    : c <= 67 ? "Rain" : c <= 77 ? "Snow" : c <= 82 ? "Showers" : "Thunderstorm";
  let city = "";
  call("get_city").then((c) => { city = c || ""; paintWeatherW(); paintPrayerW(); });
  function paintWeatherW() {
    const w = H.today() && H.today().weather;
    if (!$("wxT")) return;
    $("wxIc").innerHTML = w ? wxIcon(w.code, 30) : "";
    $("wxT").textContent = w ? `${Math.round(w.temp)}°` : "–";
    $("wxD").textContent = w ? WX_TEXT(w.code) : "No weather yet";
    $("wxCity").textContent = city;
    $("wxHL").innerHTML = w ? `<span>${ICON("sun", 13)} H ${Math.round(w.high)}°</span><span>${ICON("moon", 13)} L ${Math.round(w.low)}°</span>` : "";
  }
  function paintPrayerW() {
    const pr = H.prayers();
    if (!$("pnName")) return;
    $("pnCity").textContent = "";
    if (!pr || !pr.today) { $("pnName").textContent = "–"; $("pnIn").textContent = "Pick your city in settings"; $("pnList").innerHTML = ""; return; }
    const names = ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"], d = new Date(now());
    const at = (hmS, plus = 0) => { const [h, m] = hmS.split(":").map(Number); const x = new Date(d); x.setDate(x.getDate() + plus); x.setHours(h, m, 0, 0); return x; };
    let next = names.find((n) => at(pr.today[n]) > d), when = next ? at(pr.today[next]) : at((pr.tomorrow || pr.today).Fajr, 1);
    next = next || "Fajr";
    const mins = Math.max(0, Math.round((when - d) / 60000));
    $("pnName").textContent = next;
    $("pnAt").textContent = timeFmt.format(when);
    $("pnIn").textContent = mins >= 60 ? `in ${Math.floor(mins / 60)} h ${mins % 60} min` : `in ${mins} min`;
    $("pnList").innerHTML = names.map((n) => `<div class="${n === next ? "nx" : ""}"><span>${n}</span><b>${timeFmt.format(at(pr.today[n]))}</b></div>`).join("");
  }
  function paintDate() {
    const box = WG.today; if (!box) return;
    let h = box.querySelector(".td-date");
    if (!h) { h = document.createElement("div"); h.className = "td-date"; box.insertBefore(h, box.firstChild); }
    h.textContent = new Date(now()).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
  }
  setInterval(() => { paintPrayerW(); paintDate(); }, 30000);

  window.__hopPage = (id) => {
    if (id === "prayer") paintPrayerW();
    if (id === "weather") paintWeatherW();
    if (id === "today") paintDate();
    if (id === "agents") paintAgents();
    if (id === "calendar") paintCalendar();
    if (id === "alerts") paintAlerts();
    if (id === "shelf") loadShelf();
    if (id === "notes") loadNotes();
    if (id === "sports") paintSports();
    if (id === "battery") call("get_battery").then((b) => { if (b) { state.battery = b; paintBattery(); } });
    if (id === "prompter") loadPrompter();
    prompterRun(id === "prompter" && H.isOpen() && state.prompter.playing);
  };

  // ---- typing (notes, feedback): the island normally never takes the
  // keyboard (Alt+F4 in a game must not close it), so it asks for it only
  // while a text box is in use.
  document.addEventListener("focusin", (e) => { if (e.target.closest("[contenteditable], input, textarea")) call("want_keys", true); });
  document.addEventListener("focusout", (e) => { if (e.target.closest("[contenteditable], input, textarea")) call("want_keys", false); });

  // ---------------------------------------------------------------- AGENTS
  // each tool's own mark (logos.js: simple-icons, no background), not a letter tile
  const LOGO = window.__hopLogos || {};
  const AGENT_LOGO = { claude: "claude", codex: "openai", chatgpt: "openai", openai: "openai", gemini: "googlegemini",
                       copilot: "githubcopilot", cursor: "cursor" };
  const ST = { work: "Working", ask: "Needs you", done: "Done", idle: "Idle" };
  const mascot = (tool, status, big) => `<span class="mascot ${status}${big ? " big" : ""}">${LOGO[AGENT_LOGO[tool]] || LOGO.anthropic || ""}</span>`;
  function paintAgents() {
    const rows = $("agRows");
    if (!rows) return;
    const ss = state.agents;
    $("agSub").textContent = ss.length ? `${ss.filter((s) => s.status === "work").length} working` : "";
    rows.innerHTML = ss.length ? ss.slice(0, 6).map((s, i) => `<div class="row click" data-i="${i}">${mascot(s.tool, s.status)}
        <div class="grow"><div class="t1">${esc(s.name)}</div><div class="t2">${esc(s.detail || "")}</div></div>
        <span class="ag-st ${s.status}">${ST[s.status] || s.status}</span><i class="ag-dot ${s.status}" title="${ST[s.status] || s.status}"></i></div>`).join("")
      : `<div class="empty-note">No agents running.<br>Connect Claude Code in Settings → AI agents, then start a session.</div>`;
    rows.querySelectorAll(".row[data-i]").forEach((r) => r.addEventListener("click", () => call("agent_jump", ss[+r.dataset.i].id)));
    const u = state.usage, box = $("agUsage");
    box.hidden = !u;
    if (u) box.innerHTML = [["5h", u.five, u.fiveReset], ["Week", u.week, u.weekReset]].map(([n, p, r]) =>
      `<div style="flex:1;min-width:0;white-space:nowrap" title="${r ? "Resets in " + esc(r) : ""}"><b style="color:#fff;font-weight:600">${Math.round(p)}%</b> ${n}${r ? ` · ${esc(r)}` : ""}<div class="bar"><i class="${p >= 80 ? "hot" : ""}" style="width:${Math.min(100, p)}%"></i></div></div>`).join("");
  }
  function agentCard(a) {
    if (!L().agentsOn) return;
    const head = (t) => `${mascot(a.tool, "ask", true)}<div class="ct"><div class="t">${esc(t)}</div>`;
    if (a.kind === "permission") {
      popup("agent", `${head(`${a.name} wants to ${a.verb || "run"}`)}<div class="body one code" title="${esc(a.summary || "")}">${esc(a.summary || "")}</div>
        <div class="btns"><button class="pbtn ok2" id="aAllow">Allow</button><button class="pbtn no" id="aDeny">Deny</button><button class="pbtn" id="aTerm" title="Answer in the terminal instead">Terminal</button></div></div>`,
        340, 112, () => {
          $("aAllow").onclick = () => { call("agent_answer", a.id, "allow"); H.hideCard(); };
          $("aDeny").onclick = () => { call("agent_answer", a.id, "deny"); H.hideCard(); };
          $("aTerm").onclick = () => { call("agent_answer", a.id, "pass"); H.hideCard(); };
        }, { sticky: true, history: { app: a.name, title: "Permission", text: a.summary || "" } });
    } else if (a.kind === "question") {
      const picked = new Set();
      popup("agent", `${head(a.question || "A question")}
        <div class="choices">${(a.options || []).map((o, i) => `<button class="pbtn" data-i="${i}">${esc(o)}</button>`).join("")}</div>
        ${a.multi ? '<div class="btns"><button class="pbtn go" id="aSend">Send</button></div>' : ""}</div>`,
        360, a.multi ? 140 : 112, () => {
          document.querySelectorAll(".card .choices .pbtn").forEach((b) => b.addEventListener("click", () => {
            const o = a.options[+b.dataset.i];
            if (!a.multi) { call("agent_answer", a.id, { choice: [o] }); H.hideCard(); return; }
            picked.has(o) ? picked.delete(o) : picked.add(o);
            b.classList.toggle("ok", picked.has(o));
          }));
          if (a.multi) $("aSend").onclick = () => { call("agent_answer", a.id, { choice: [...picked] }); H.hideCard(); };
        }, { sticky: true, history: { app: a.name, title: "Question", text: a.question || "" } });
    } else if (a.kind === "plan") {
      popup("agent", `${head(`${a.name}: plan ready`)}<div class="plan scrolls">${esc(a.plan || "")}</div>
        <textarea class="fb" id="aFb" rows="1" placeholder="Feedback (optional), then Keep planning"></textarea>
        <div class="btns"><button class="pbtn ok2" id="aGo">Approve</button><button class="pbtn" id="aMore">Keep planning</button></div></div>`,
        360, 196, () => {
          document.querySelector(".card").classList.add("tall");
          const fb = $("aFb");
          // every new line makes the box (and the card) taller, up to the room the island has
          const plan = document.querySelector(".card .plan");
          const grow = () => {
            const c = document.querySelector(".card");
            plan.style.maxHeight = "";
            fb.style.overflowY = "hidden";
            fb.style.height = "auto";
            const want = fb.scrollHeight;
            fb.style.height = want + "px";
            H.fitCard(true);                           // taller only: typing never makes the card wider
            // the card's room is fixed now: what the buttons need is measured, not guessed
            const pb = parseFloat(getComputedStyle(c).paddingBottom) || 0, btns = c.querySelector(".btns");
            const over = () => btns.getBoundingClientRect().bottom - (c.getBoundingClientRect().bottom - pb);   // the buttons keep the bottom padding
            if (over() > 0) {                          // out of room: the plan text shrinks, whole lines, to 2 at least
              const ph = plan.offsetHeight, extra = ph - plan.clientHeight + 12;     // its padding / border
              plan.style.maxHeight = Math.max(2 * 16 + 12, Math.floor((ph - over() - extra) / 16) * 16 + 12) + "px";
            }
            if (over() > 0) {                          // then the box stops growing and scrolls inside itself
              fb.style.height = Math.max(26, fb.offsetHeight - over()) + "px";
              fb.style.overflowY = "auto";
            }
          };
          fb.addEventListener("input", grow);
          fb.addEventListener("keydown", (e) => e.stopPropagation());
          $("aGo").onclick = () => { call("agent_answer", a.id, "allow"); H.hideCard(); };
          $("aMore").onclick = () => { call("agent_answer", a.id, { deny: $("aFb").value || "Keep planning." }); H.hideCard(); };
        }, { sticky: true, history: { app: a.name, title: "Plan", text: (a.plan || "").slice(0, 80) } });
    } else if (a.kind === "done") {
      popup("agent", `${mascot(a.tool, "done", true)}<div class="ct"><div class="t">${esc(a.name)} is done</div>
        <div class="body">${esc(a.summary || "Finished its turn")}</div>
        <div class="btns"><button class="pbtn go" id="aJump">Jump to it</button></div></div>`, 340, a.summary && a.summary.length > 44 ? 120 : 100, () => {
          $("aJump").onclick = () => { call("agent_jump", a.session); H.hideCard(); };
        }, { history: { app: a.name, title: "Done", text: a.summary || "" } });
    }
  }
  function agentEdit(e) {
    if (!L().agentsOn) return;
    const name = (e.file || "").split(/[\\/]/).pop();
    activity("agent", Math.min(300, 120 + name.length * 7),
      `<div class="side">${mascot(e.tool || "claude", "work")}<span class="name">${esc(name)}</span></div>
       <div class="side"><span style="color:#7ee2a8">+${e.plus | 0}</span><span style="color:#ff9a92">−${e.minus | 0}</span></div>`, 3000);
  }

  // ---------------------------------------------------------------- TIMER / STOPWATCH / FOCUS (pomodoro)
  // Three separate clocks that can all run at once: the tabs only choose
  // which one you're looking at (a running one has a dot on its tab). The
  // pill shows the one started last.
  const POMO = { work: 25 * 60000, break: 5 * 60000, long: 15 * 60000 };
  const fresh = () => ({
    view: "timer", last: "",
    timer: { set: 300000, left: 300000, endAt: 0, running: false },
    watch: { elapsed: 0, startAt: 0, running: false },
    pomo: { left: POMO.work, endAt: 0, running: false, phase: "work", round: 1 },
  });
  let T = store.get("timers", null);
  if (!T || !T.timer || !T.watch || !T.pomo) T = fresh();
  for (const m of ["timer", "pomo"]) T[m].running = false;           // a restart doesn't resume a countdown silently
  if (T.watch.running) { T.watch.elapsed += now() - T.watch.startAt; T.watch.running = false; }
  const save = () => store.set("timers", T);
  const msOf = (m) => m === "watch" ? (T.watch.running ? now() - T.watch.startAt + T.watch.elapsed : T.watch.elapsed)
    : T[m].running ? Math.max(0, T[m].endAt - now()) : T[m].left;
  function fmtTimer(m = T.view) {
    const ms = msOf(m), s = Math.floor((m === "watch" ? ms : ms + 999) / 1000);
    const h = Math.floor(s / 3600), mm = Math.floor((s % 3600) / 60), ss = String(s % 60).padStart(2, "0");
    return h ? `${h}:${String(mm).padStart(2, "0")}:${ss}` : `${mm}:${ss}`;
  }
  // what the pill shows: the clock started last that is still running
  const liveClock = () => (T.last && T[T.last] && T[T.last].running ? T.last : ["timer", "pomo", "watch"].find((m) => T[m].running) || "");
  const timer = {                                    // the older code's view of it (slots, live text, gestures)
    get running() { return !!liveClock(); },
    get left() { return T.timer.left; },
    get mode() { return liveClock() || T.view; },
    get elapsed() { return T.watch.elapsed; },
  };
  function paintTimer() {
    if (!$("tmBig")) return;
    const m = T.view, c = T[m];
    $("tmBig").textContent = fmtTimer(m);
    $("tmBig").classList.toggle("run", c.running);
    [...$("tmModes").children].forEach((b) => {
      b.classList.toggle("on", b.dataset.m === m);
      b.classList.toggle("running", T[b.dataset.m].running);
    });
    $("tmSub").textContent = m === "pomo" ? `${c.phase === "work" ? "Focus" : "Break"} · round ${c.round} of 4` : "";
    const presets = m === "timer" ? [1, 5, 10, 25].map((x) => `<button class="lnk" data-p="${x}">${x}m</button>`).join("") : "";
    $("tmRow").innerHTML = `${presets}<button class="lnk go" id="tmGo">${c.running ? "Pause" : "Start"}</button><button class="lnk" id="tmReset">Reset</button>`;
    $("tmGo").onclick = () => (c.running ? pauseTimer(m) : startTimer(m));
    $("tmReset").onclick = () => resetTimer(m);
    $("tmRow").querySelectorAll("[data-p]").forEach((b) => b.onclick = () => {
      T.timer.set = T.timer.left = +b.dataset.p * 60000;
      if (T.timer.running) T.timer.endAt = now() + T.timer.left;
      save(); paintTimer();
    });
  }
  function startTimer(m = T.view) {
    const c = T[m];
    if (m === "watch") c.startAt = now();
    else { if (c.left <= 0) c.left = m === "pomo" ? POMO[c.phase] : c.set; c.endAt = now() + c.left; }
    c.running = true; T.last = m; save(); paintTimer(); liveTick();
  }
  function pauseTimer(m = T.view) {
    const c = T[m];
    if (m === "watch") c.elapsed += now() - c.startAt;
    else c.left = Math.max(0, c.endAt - now());
    c.running = false; save(); paintTimer(); liveTick();
  }
  function resetTimer(m = T.view) {
    const c = T[m];
    c.running = false;
    if (m === "watch") c.elapsed = 0;
    else if (m === "pomo") Object.assign(c, { phase: "work", round: 1, left: POMO.work });
    else c.left = c.set;
    save(); paintTimer(); liveTick();
  }
  function timerDone(m) {
    const c = T[m];
    c.running = false; c.left = 0;
    let title = "Time's up", sub = `${H.clipLen(T.timer.set / 1000)} timer`;
    if (m === "pomo") {
      if (c.phase === "work") { c.phase = c.round % 4 === 0 ? "long" : "break"; title = "Focus done"; sub = "Time for a break"; }
      else { c.phase = "work"; c.round = c.round % 4 + 1; title = "Break over"; sub = `Round ${c.round}`; }
      c.left = POMO[c.phase];
    }
    save(); paintTimer();
    popup("timer", `${chip("alarm", "var(--hop-orange)")}<div class="ct"><div class="t">${title}</div><div class="s">${sub}</div>
      <div class="btns">${m === "pomo" ? '<button class="pbtn warn" id="tNext">Start next</button>' : '<button class="pbtn" id="tAgain">Again</button>'}<button class="pbtn" id="tOk">OK</button></div></div>`,
      280, 100, () => {
        $("tOk").onclick = () => H.hideCard();
        if ($("tNext")) $("tNext").onclick = () => { startTimer("pomo"); H.hideCard(); };
        if ($("tAgain")) $("tAgain").onclick = () => { T.timer.left = T.timer.set; startTimer("timer"); H.hideCard(); };
      }, { history: { app: "Timer", title, text: sub } });
  }
  // switching tabs never stops anything
  $("tmModes").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-m]"); if (!b) return;
    T.view = b.dataset.m; save(); paintTimer();
  });
  $("tmBig").addEventListener("wheel", (e) => {
    e.preventDefault();
    if (T.view !== "timer" || T.timer.running) return;
    T.timer.set = T.timer.left = Math.max(60000, Math.min(99 * 60000, T.timer.left + (e.deltaY < 0 ? 60000 : -60000)));
    save(); paintTimer();
  }, { passive: false });
  setInterval(() => {
    for (const m of ["timer", "pomo"]) if (T[m].running && now() >= T[m].endAt) timerDone(m);
    if (H.isOpen() && $("tmBig").closest(".pg.on")) $("tmBig").textContent = fmtTimer(T.view);
  }, 250);
  paintTimer();
  window.__hopTimer = { start: (ms) => { T.view = "timer"; T.timer.set = T.timer.left = ms; startTimer("timer"); }, state: () => JSON.parse(JSON.stringify(T)) };

  // ---------------------------------------------------------------- CALENDAR (an iCal link)
  const alertedEv = new Set();
  function paintCalendar() {
    const rows = $("calRows");
    if (!rows) return;
    const t = now(), soon = state.calendar.filter((e) => e.end > t).slice(0, 5);
    const day = (ms) => { const d = new Date(ms), n = new Date(t); return d.toDateString() === n.toDateString() ? "" : d.toLocaleDateString(undefined, { weekday: "short" }) + " "; };
    $("calHead").textContent = soon.length ? `Next ${soon.length === 1 ? "event" : "events"}` : "Calendar";
    rows.innerHTML = soon.length ? soon.map((e, i) => `<div class="row">
        <span class="tm">${e.allDay ? "All day" : day(e.start) + timeFmt.format(e.start)}</span>
        <div class="grow"><div class="t1">${esc(e.title)}</div>${e.location ? `<div class="t2">${esc(e.location)}</div>` : ""}</div>
        ${e.link ? `<button class="mini-btn go" data-j="${i}">Join</button>` : ""}</div>`).join("")
      : `<div class="empty-note">${state.calSet ? "Nothing coming up." : "Paste your calendar's iCal link in Settings → Calendar (Google: Settings → your calendar → Secret address in iCal format)."}</div>`;
    rows.querySelectorAll("[data-j]").forEach((b) => b.onclick = (e) => { e.stopPropagation(); call("open_url", soon[+b.dataset.j].link); });
    // a click on a meeting's row joins it too (narrow tiles have no room for the button)
    rows.querySelectorAll(".row").forEach((r, i) => { if (soon[i] && soon[i].link) { r.classList.add("click"); r.onclick = () => call("open_url", soon[i].link); } });
  }
  $("calOpen").addEventListener("click", () => call("open_calendar"));
  setInterval(() => {
    const t = now();
    for (const e of state.calendar) {
      if (e.allDay || alertedEv.has(e.uid + e.start)) continue;
      const lead = e.start - t;
      if (lead <= 5 * 60000 && lead > -60000) {
        alertedEv.add(e.uid + e.start);
        const mins = Math.max(0, Math.round(lead / 60000));
        popup("calendar", `<div class="ic-sq" style="background:var(--hop-red);color:#fff;font-size:11px;line-height:1.05;text-align:center">${new Date(e.start).toLocaleDateString(undefined, { month: "short" }).toUpperCase()}<br>${new Date(e.start).getDate()}</div>
          <div class="ct"><div class="t">${esc(e.title)}</div><div class="s">${mins ? `In ${mins} min` : "Starting now"} · ${timeFmt.format(e.start)}</div>
          ${e.link ? '<div class="btns"><button class="pbtn ok2" id="eJoin">Join</button></div>' : ""}</div>`,
          320, e.link ? 100 : 72, () => { if ($("eJoin")) $("eJoin").onclick = () => { call("open_url", e.link); H.hideCard(); }; },
          { history: { app: "Calendar", title: e.title, text: mins ? `In ${mins} min` : "Starting now" } });
      }
    }
  }, 15000);

  // ---------------------------------------------------------------- NOTIFICATIONS (pop-ups + history page)
  const letter = (app) => (app || "?").replace(/[^A-Za-z0-9]/g, "").slice(0, 1).toUpperCase() || "•";
  const APPC = { Discord: "#5865f2", Outlook: "#0a64d2", Mail: "#0a84ff", WhatsApp: "#25d366", Teams: "#5b5fc7", Telegram: "#2aa3df", Slack: "#4a154b", Steam: "#1b2838" };
  function notif(n) {
    const icon = n.icon ? `<img src="${esc(n.icon)}" alt="">` : letter(n.app);
    popup("notif", `<div class="ic-sq" style="background:${APPC[n.app] || "#3a3a3c"};color:#fff">${icon}</div>
      <div class="ct"><div class="s">${esc(n.app)}</div><div class="t">${esc(n.title || n.app)}</div>${n.text ? `<div class="body">${esc(n.text)}</div>` : ""}</div>`,
      340, n.text ? 96 : 72, null, { history: { app: n.app, title: n.title, text: n.text, icon: n.icon || "" } });
  }
  // Hop's own pop-ups in the list: their icon, not a letter
  const OWN = { Downloads: ["download", "#64d2ff"], Scores: ["ball-football", "#30d158"], Reminder: ["bell", "#a5a3ff"], Weather: ["cloud-rain", "#5ac8fa"],
                Calendar: ["calendar-event", "#ff453a"], Timer: ["alarm", "#ff9f0a"], Clipper: ["photo", "#ff375f"], Screenshots: ["photo", "#64d2ff"],
                Prayer: ["building-mosque", "#ffd479"], "Game mode": ["device-gamepad-2", "#c7c7cc"], Shelf: ["pin", "#c7c7cc"], Hop: ["alert-triangle", "#ff9f0a"] };
  function paintAlerts() {
    const rows = $("alRows");
    if (!rows) return;
    rows.innerHTML = state.history.length ? state.history.slice(0, 20).map((h) => `<div class="row nrow">
        <span class="n-ic${OWN[h.app] ? " own" : ""}" style="--c:${(OWN[h.app] || [])[1] || APPC[h.app] || "#8e8e93"}">${h.icon ? `<img src="${esc(h.icon)}" alt="">` : OWN[h.app] ? ICON(OWN[h.app][0], 16) : esc(letter(h.app))}</span>
        <div class="grow"><div class="t1"><span class="n-app">${esc(h.app || "")}</span><span class="tm">${H.ago(h.at / 1000)}</span></div>
          <div class="t2"><b>${esc(h.title || h.app)}</b>${h.text ? " · " + esc(h.text) : ""}</div></div></div>`).join("")
      : `<div class="empty-note">No notifications yet</div>`;
  }
  // Clear: the rows slide out one after another, then the list collapses
  $("alClear").addEventListener("click", () => {
    const rs = [...$("alRows").querySelectorAll(".row")];
    rs.forEach((r, i) => { r.style.transitionDelay = `${i * 35}ms`; r.classList.add("gone"); });
    const box = $("alRows");
    setTimeout(() => {                                 // fold the list shut
      box.style.height = box.offsetHeight + "px"; box.style.transition = "height 220ms cubic-bezier(.2, .8, .2, 1)";
      void box.offsetHeight; box.style.height = "0px";
    }, 200 + rs.length * 35);
    setTimeout(() => {
      state.history = []; store.set("history", []);
      box.style.transition = box.style.height = "";
      paintAlerts();
      const n = box.querySelector(".empty-note"); if (n) n.animate([{ opacity: 0, transform: "translateY(4px)" }, { opacity: 1, transform: "none" }], { duration: 220, easing: "ease-out" });
    }, 440 + rs.length * 35);
  });

  // ---------------------------------------------------------------- SHELF (files parked on the island)
  const ext = (n) => (n.split(".").pop() || "").slice(0, 4).toUpperCase();
  function loadShelf() { call("get_shelf").then((items) => { state.shelf = items || []; paintShelf(); }); }
  function paintShelf() {
    const box = $("shItems");
    if (!box) return;
    $("shSub").textContent = state.shelf.length ? `${state.shelf.length} item${state.shelf.length === 1 ? "" : "s"}` : "Drop files on the island";
    box.innerHTML = state.shelf.length ? state.shelf.slice(0, 5).map((it, i) => `<div class="sh" data-i="${i}" title="${esc(it.path)}">
        ${it.pinned ? `<span class="pin">${ICON("pin", 12)}</span>` : ""}<button class="x" data-x="${i}" title="Remove">×</button>
        <div class="ic">${it.thumb ? `<img src="${esc(it.thumb)}" alt="">` : esc(it.dir ? "DIR" : ext(it.name))}</div><div class="nm">${esc(it.name)}</div></div>`).join("")
      : `<div class="sh-drop" style="flex:1">Drop files here to keep them handy. Click one to open it; right-click to pin it or copy it.</div>`;
    box.querySelectorAll(".sh").forEach((el) => {
      const it = state.shelf[+el.dataset.i];
      el.addEventListener("click", (e) => { if (!e.target.closest(".x")) call("open_file", it.path); });
      el.addEventListener("contextmenu", (e) => { e.preventDefault(); call("shelf", "pin", it.path).then(loadShelf); });
      el.addEventListener("auxclick", (e) => { if (e.button === 1) { call("copy_file", it.path); el.classList.add("ok"); } });
    });
    box.querySelectorAll("[data-x]").forEach((b) => b.addEventListener("click", () => call("shelf", "remove", state.shelf[+b.dataset.x].path).then(loadShelf)));
  }

  // ---------------------------------------------------------------- NOTES
  let notesTimer = 0;
  function loadNotes() { call("get_notes").then((t) => { const el = $("notes"); if (el && document.activeElement !== el) el.textContent = t || ""; }); }
  $("notes").addEventListener("input", () => {
    $("ntSub").textContent = "Typing…";
    clearTimeout(notesTimer);
    notesTimer = setTimeout(() => call("set_notes", $("notes").textContent).then(() => { $("ntSub").textContent = "Saved"; }), 500);
  });
  $("notes").addEventListener("keydown", (e) => { if (e.key === "Escape") e.target.blur(); e.stopPropagation(); });

  // ---------------------------------------------------------------- SPORTS
  let lastScores = {};
  function paintSports() {
    const box = $("spRows");
    if (!box) return;
    const ms = state.sports;
    $("spSub").textContent = ms.some((m) => m.live) ? "Live" : "";
    box.innerHTML = ms.length ? ms.slice(0, 3).map((m) => `<div class="match"><div class="tm-a">${esc(m.home)}</div>
        <div class="sc">${m.state === "pre" ? "vs" : `${m.hs} – ${m.as}`}</div><div class="tm-b">${esc(m.away)}</div>
        <div class="st ${m.live ? "live" : ""}">${esc(m.status)}</div></div>`).join("")
      : `<div class="empty-note">${(L().teams || []).length ? "No games today for your teams." : "Pick your teams in Settings → Sports."}</div>`;
  }
  function sports(ms) {
    for (const m of ms) {
      const k = m.id, sc = `${m.hs}-${m.as}`;
      if (lastScores[k] && lastScores[k] !== sc && m.live) {
        // who scored: the side whose number went up. Their crest pops in, a
        // ball rolls into it and "GOAL" sweeps across, like Google's live card.
        const [ph, pa] = lastScores[k].split("-").map(Number);
        const homeScored = +m.hs > ph, side = homeScored ? "home" : "away";
        const logo = m[side + "Logo"], team = m[side];
        const soccer = !m.sport || m.sport === "soccer";
        const word = soccer ? "GOAL" : "SCORE";
        const ball = ICON({ soccer: "ball-football", basketball: "ball-basketball", football: "ball-american-football", baseball: "ball-baseball" }[m.sport || "soccer"] || "ball-football", 18);
        popup("sports", `<div class="goal-crest">${logo ? `<img src="${esc(logo)}" alt="" onerror="this.hidden=true;this.nextElementSibling.hidden=false"><span class="crest-fb" hidden>${ball}</span>` : `<span class="crest-fb">${ball}</span>`}<span class="ball">${ball}</span></div>
          <div class="ct"><div class="goal-word">${[...(soccer ? "GO" + "A".repeat(14) + "L!" : word + "!")].map((ch, i) => `<span style="--i:${i}">${ch}</span>`).join("")}</div>
          <div class="goal-line"><span class="${homeScored ? "hit" : ""}">${esc(m.home)}</span><span class="sc">${m.hs} – ${m.as}</span><span class="${homeScored ? "" : "hit"}">${esc(m.away)}</span></div>
          <div class="goal-sub">${esc(m.status)} · ${esc(m.league)}</div></div>`, 340, 92, () => {
            document.querySelector(".card").classList.add("goal");
          }, { history: { app: "Scores", title: `${m.home} ${m.hs} – ${m.as} ${m.away}`, text: m.status } });
      }
      lastScores[k] = sc;
    }
    state.sports = ms;
    if (H.pageId() === "sports") paintSports();
  }

  // ---------------------------------------------------------------- TELEPROMPTER
  let prY = 0, prAnim = 0, prLast = 0;
  function loadPrompter() {
    if (!state.prompter.playing) $("prText").style.transform = `translateY(${prStart() - prY}px)`;
    call("get_prompter").then((t) => {
      state.prompter.text = t || "";
      $("prText").textContent = state.prompter.text || "Write your script in Settings → Teleprompter. It scrolls here, right under your webcam.";
    });
  }
  function prompterRun(on) {
    cancelAnimationFrame(prAnim);
    $("prPlay").textContent = state.prompter.playing ? "Pause" : "Play";
    if (!on) return;
    prLast = performance.now();
    const step = (t) => {
      const dt = (t - prLast) / 1000; prLast = t;
      prY += dt * (L().prompterSpeed || 40);
      const max = $("prText").offsetHeight - 30;
      if (prY > max) { prY = max; state.prompter.playing = false; $("prPlay").textContent = "Play"; }
      $("prText").style.transform = `translateY(${(prStart() - prY).toFixed(1)}px)`;
      $("prInfo").textContent = `${L().prompterSpeed || 40} px/s`;
      if (state.prompter.playing) prAnim = requestAnimationFrame(step);
    };
    prAnim = requestAnimationFrame(step);
  }
  $("prPlay").addEventListener("click", () => { state.prompter.playing = !state.prompter.playing; prompterRun(state.prompter.playing); });
  const prStart = () => Math.round(($("prView").clientHeight || 96) * 0.3);
  $("prBack").addEventListener("click", () => { prY = 0; $("prText").style.transform = `translateY(${prStart()}px)`; });
  $("prText").style.transform = "translateY(28px)";

  // ---------------------------------------------------------------- BATTERY
  function paintBattery() {
    const b = state.battery;
    if (!b || !$("btPct")) return;
    $("btPct").textContent = b.pct == null ? "No battery" : `${b.pct}%`;
    $("btFill").style.width = `${b.pct || 0}%`;
    $("btFill").classList.toggle("low", (b.pct || 0) <= 15);
    const left = b.minutes ? `${Math.floor(b.minutes / 60)}h ${b.minutes % 60}m ${b.charging ? "to full" : "left"}` : b.charging ? "Charging" : "";
    $("btMeta").innerHTML = [left && `<b>${left}</b>`, b.health != null && `Health <b>${b.health}%</b>${b.cycles ? ` · ${b.cycles} cycles` : ""}`,
      b.design && `${(b.full / 1000).toFixed(1)} of ${(b.design / 1000).toFixed(1)} Wh`].filter(Boolean).map((x, i) => `<div class="ln${i}">${x}</div>`).join("");
    const ds = (b.drainers || []).slice(0, 3);
    $("btRows").innerHTML = ds.length ? `<div class="bt-chips"><span class="lbl">Using most</span>${ds.map((d) => `<span class="chip">${esc(d.name)} <b>${d.cpu.toFixed(0)}%</b></span>`).join("")}</div>` : "";
  }

  // ---------------------------------------------------------------- EXTENSIONS (your own pages)
  function applyExtensions(L) {
    const on = new Set(L.extensions || []);
    document.querySelectorAll(".pg[data-ext]").forEach((p) => {
      if (on.has(p.dataset.ext)) return;
      const box = WG[p.dataset.id];
      if (box) { box.remove(); delete WG[p.dataset.id]; }
      p.remove();
    });
    for (const x of state.extensions) {
      if (!on.has(x.id) || document.querySelector(`.pg[data-ext="${x.id}"]`)) continue;
      const pg = document.createElement("div");
      pg.className = "pg pg-ext";
      pg.dataset.id = "ext-" + x.id;
      pg.dataset.ext = x.id;
      const box = document.createElement("div");
      box.className = "wg wg-ext";
      box.dataset.w = pg.dataset.id;
      box.innerHTML = `<iframe sandbox="allow-scripts" src="${esc(x.url)}" title="${esc(x.name)}"></iframe>`;
      pg.appendChild(box);
      WG[pg.dataset.id] = box;
      full.insertBefore(pg, dots);
    }
  }
  // an extension may ask for a pop-up: postMessage({hop: "popup", title, text})
  window.addEventListener("message", (e) => {
    const m = e.data || {};
    if (m.hop !== "popup") return;
    const frame = [...document.querySelectorAll(".wg-ext iframe")].find((f) => f.contentWindow === e.source);
    if (!frame) return;
    popup("notif", `<div class="ic-sq" style="background:#3a3a3c;color:#fff">${esc(letter(frame.title))}</div><div class="ct"><div class="s">${esc(frame.title)}</div>
      <div class="t">${esc(String(m.title || "").slice(0, 80))}</div>${m.text ? `<div class="body">${esc(String(m.text).slice(0, 200))}</div>` : ""}</div>`,
      320, m.text ? 96 : 72, null, { history: { app: frame.title, title: m.title, text: m.text } });
  });

  // ================================================================ BOARDS: pages made of widgets
  // Every kind's content lives in one .wg box. In classic mode the boxes sit
  // in their own full-size pages; in boards mode they move into the tiles of
  // a 4 x 2 grid, a few per page, sized by the settings (s w t b f).
  const WG = {};
  document.querySelectorAll(".full .pg[data-id]").forEach((pg) => {
    const box = document.createElement("div");
    box.className = `wg wg-${pg.dataset.id}`;
    box.dataset.w = pg.dataset.id;
    while (pg.firstChild) box.appendChild(pg.firstChild);
    pg.appendChild(box);
    WG[pg.dataset.id] = box;
  });
  const NAME = { music: "Now playing", today: "Today", clips: "Clips", pc: "PC", agents: "Agents", timer: "Timer", calendar: "Calendar",
                 alerts: "Notifications", shelf: "Shelf", notes: "Notes", sports: "Scores", prompter: "Teleprompter", battery: "Battery" };
  let boardKey = "";
  function home(w) {                                   // a widget back into its own classic page
    const pg = document.querySelector(`.full .pg[data-id="${w}"]:not(.pg-board)`);
    if (pg && WG[w] && WG[w].parentElement !== pg) pg.appendChild(WG[w]);
  }
  window.__hopBoards = (Lx) => {
    applyExtensions(Lx);
    const on = Lx.pageMode === "boards";
    placeButtons(on);
    const key = on ? JSON.stringify(Lx.boards) + "|" + Object.keys(WG).join() : "";
    if (key === boardKey) return;
    boardKey = key;
    Object.keys(WG).forEach(home);
    document.querySelectorAll(".full .pg-board").forEach((b) => b.remove());
    if (!on) return;
    (Lx.boards || []).forEach((b, i) => {
      const pg = document.createElement("div");
      pg.className = "pg pg-board";
      pg.dataset.id = "board-" + i;
      pg.dataset.name = b.name;
      const ws = b.widgets.filter((w) => WG[w.w]);
      pg.dataset.widgets = ws.map((w) => w.w).join(",");
      const grid = document.createElement("div");
      grid.className = "grid";
      for (const w of ws) {
        const tile = document.createElement("div");
        tile.className = `tile sz-${w.s} tile-${w.w.startsWith("ext-") ? "ext" : w.w}`;
        tile.dataset.w = w.w;
        tile.appendChild(WG[w.w]);
        grid.appendChild(tile);
      }
      pg.appendChild(grid);
      full.insertBefore(pg, dots);
    });
    buildTabs(Lx);
    requestAnimationFrame(dividers);
    // widgets that just joined a page show their content at once, not on the next visit
    setTimeout(() => (Lx.boards || []).forEach((b) => b.widgets.forEach((w) => window.__hopPage && window.__hopPage(w.w))), 0);
  };
  const TAB_ICON = { music: "home", agents: "robot", calendar: "calendar-event", clips: "photo", pc: "device-desktop", notes: "notes",
                     timer: "alarm", alerts: "bell", today: "calendar-event", prayer: "building-mosque", weather: "cloud", shelf: "folder",
                     sports: "ball-football", prompter: "note", battery: "battery-2" };
  const SNAP_SVG = '<svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor"><path d="M4 3.5h16v2H4zM12 8l5 5h-4v7.5h-2V13H7l5-5Z"/></svg>';
  const bar = document.createElement("div");
  bar.className = "topbar";
  bar.innerHTML = `<div class="tabs" id="tabs"></div><div class="tb-right"><button class="tb" id="tbSnap" title="Snap to top middle">${SNAP_SVG}</button></div>`;
  full.appendChild(bar);
  // widget pages: the refresh and settings buttons move up here (no more
  // hunting at the edge); classic pages keep them where they were
  function placeButtons(on) {
    const home = on ? bar.querySelector(".tb-right") : full;
    for (const id of ["reload", "gear"]) { const b = $(id); if (b.parentElement !== home) home.appendChild(b); b.classList.toggle("tb", on); }
  }
  // snap: one screen -> top middle at once; several -> pick one, in the
  // order they sit (Left monitor / This monitor / Right monitor)
  window.__hopSnap = () => Promise.resolve(api.recenter()).then((r) => {
    if (!r || !r.choose) return;
    H.showCard(`${chip("device-desktop", "#64d2ff")}<div class="ct"><div class="t">Move the island to</div>
      <div class="btns scr">${r.choose.map((m) => `<button class="pbtn ${m.label === "This monitor" ? "go" : ""}" data-m="${m.index}">${esc(m.label)}</button>`).join("")}</div></div>`,
      360, 92, 8000, () => {
        document.querySelectorAll(".card .scr [data-m]").forEach((b) => b.onclick = () => { call("snap_to", +b.dataset.m); H.hideCard(); });
      });
  });
  $("tbSnap").addEventListener("click", () => window.__hopSnap());
  function buildTabs(Lx) {
    const tabs = $("tabs");
    tabs.innerHTML = (Lx.boards || []).map((b, i) => `<button class="tab" data-i="${i}" title="${esc(b.name)}">${ICON(b.icon || TAB_ICON[(b.widgets[0] || {}).w] || "layout-grid", 15)}</button>`).join("");
    tabs.onclick = (e) => { const t = e.target.closest(".tab"); if (t) H.setPage(+t.dataset.i); };
  }
  window.__hopTab = (i) => document.querySelectorAll("#tabs .tab").forEach((t, k) => t.classList.toggle("on", k === i));
  // thin lines between columns / rows, like SuperIsland's dividers (not boxes)
  function dividers() {
    document.querySelectorAll(".pg-board .grid").forEach((g) => {
      const top = g.getBoundingClientRect();
      g.querySelectorAll(".tile").forEach((t) => {
        const r = t.getBoundingClientRect();
        t.classList.toggle("sep-l", r.left - top.left > 4);
        t.classList.toggle("sep-t", r.top - top.top > 4);
      });
    });
  }
  window.__hopDividers = dividers;
  window.__hopWidgetNames = () => ({ ...NAME, ...Object.fromEntries(state.extensions.map((x) => ["ext-" + x.id, x.name])) });

  // ================================================================ CARDS
  // ---- the clip-saved card: Open / Copy / Upload & copy link / Trim
  const UPLOAD_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 15V4m-4.5 4.5L12 4l4.5 4.5M5 15v3.5A1.5 1.5 0 0 0 6.5 20h11a1.5 1.5 0 0 0 1.5-1.5V15"/></svg>';
  const TRIM_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="6" r="2.6"/><circle cx="6" cy="18" r="2.6"/><path d="M8.2 7.4 20 17M8.2 16.6 20 7"/></svg>';
  window.__islandClip = (c, back) => {
    if (H.off("clipCard")) return;
    const label = c.kind === "recording" ? "Recording saved" : "Clip saved";
    const sub = `${H.clipLen(c.seconds)}${c.game ? " · " + esc(c.game) : " · just now"}`;
    const Lx = L();
    popup("clip", `<video src="${esc(c.url)}" muted autoplay loop playsinline></video>
      <div class="ct"><div class="t">${label}</div><div class="s">${sub}</div>
      <div class="btns"><button class="pbtn" id="cOpen">Open</button><button class="pbtn" id="cCopy">Copy</button>
      ${Lx.clipUpload ? `<button class="pbtn ico" id="cUp" title="Upload to mutate.lol and copy the link">${UPLOAD_SVG}</button>` : ""}
      ${Lx.clipTrim ? `<button class="pbtn ico" id="cTrim" title="Trim">${TRIM_SVG}</button>` : ""}</div></div>`,
      312, 100, () => {
        const v = document.querySelector(".card video");
        let again = false;
        v.addEventListener("error", () => {
          if (again) return; again = true;
          Promise.resolve(api.remapHosts && api.remapHosts()).then(() => setTimeout(() => { v.src = c.url + "?r=" + Date.now(); }, 800));
        });
        $("cOpen").onclick = () => { call("open_file", c.path); H.hideCard(); };
        $("cCopy").onclick = (e) => { call("copy_file", c.path); e.target.classList.add("ok"); e.target.textContent = "Copied ✓"; H.fitCard(); H.armCard(2500); };
        if ($("cUp")) $("cUp").onclick = () => { call("upload_file", c.path); };
        if ($("cTrim")) $("cTrim").onclick = () => trimCard(c);
      }, back ? {} : { history: { app: "Clipper", title: label, text: c.name || "" } });
  };
  function trimCard(c) {
    const dur = c.seconds || 30;
    let a = 0, b = dur;
    H.showCard(`<video src="${esc(c.url)}" muted autoplay loop playsinline></video>
      <div class="ct" style="min-width:170px"><div class="t">Trim</div>
      <div class="trim" id="trim"><div class="tr-rail"></div><div class="tr-sel" id="trSel"></div><div class="tr-h" id="trA"></div><div class="tr-h" id="trB"></div></div>
      <div class="trim-lbl" id="trLbl"></div>
      <div class="btns"><button class="pbtn warn" id="trSave">Save</button><button class="pbtn" id="trNo">Cancel</button></div></div>`,
      380, 140, 0, () => {
        const v = document.querySelector(".card video"), bar = $("trim");
        const paint = () => {
          const w = bar.offsetWidth;
          const x = (t) => 5 + (t / dur) * (w - 10);
          $("trA").style.left = x(a) + "px"; $("trB").style.left = x(b) + "px";
          $("trSel").style.left = x(a) + "px"; $("trSel").style.width = (x(b) - x(a)) + "px";
          $("trLbl").textContent = `${a.toFixed(1)}s – ${b.toFixed(1)}s · ${(b - a).toFixed(1)}s`;
        };
        const drag = (which) => (e) => {
          e.stopPropagation();
          const h = e.currentTarget; h.setPointerCapture(e.pointerId);
          const move = (ev) => {
            const r = bar.getBoundingClientRect(), t = Math.min(dur, Math.max(0, ((ev.clientX - r.left - 5) / (r.width - 10)) * dur));
            if (which === "a") a = Math.min(t, b - 0.5); else b = Math.max(t, a + 0.5);
            v.currentTime = which === "a" ? a : Math.max(a, b - 1);
            paint();
          };
          h.onpointermove = move;
          h.onpointerup = () => { h.onpointermove = null; };
        };
        $("trA").addEventListener("pointerdown", drag("a"));
        $("trB").addEventListener("pointerdown", drag("b"));
        v.addEventListener("timeupdate", () => { if (v.currentTime > b || v.currentTime < a - 0.2) v.currentTime = a; });
        $("trNo").onclick = () => window.__islandClip(c, true);      // back to Open / Copy / Upload / Trim
        $("trSave").onclick = () => {
          $("trSave").textContent = "Saving…";
          call("trim_clip", c.path, a, b).then((out) => {
            if (!out) { $("trSave").textContent = "Failed"; return; }
            H.showCard(`<div class="badge" style="background:#30d158"><svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg></div>
              <div class="ct"><div class="t">Trimmed</div><div class="s">${esc(out.name)}</div>
              <div class="btns"><button class="pbtn" id="tOpen">Open</button><button class="pbtn" id="tCopy">Copy</button></div></div>`, 300, 96, 6000, () => {
              $("tOpen").onclick = () => { call("open_file", out.path); H.hideCard(); };
              $("tCopy").onclick = (e) => { call("copy_file", out.path); e.target.textContent = "Copied ✓"; };
            });
          });
        };
        requestAnimationFrame(paint);
      });
  }

  // ---- a finished download, a new snip, the rain, a reminder, Jumu'ah
  const DL = '<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4v11m-5-5 5 5 5-5M5 19h14"/></svg>';
  function download(d) {
    popup("download", `${chip("download", "#64d2ff")}<div class="ct"><div class="s">Downloaded · ${esc(d.size || "")}</div>
      <div class="t">${esc(d.name)}</div><div class="btns"><button class="pbtn" id="dOpen">Open</button><button class="pbtn" id="dShow">Show</button><button class="pbtn" id="dShelf">Shelf</button></div></div>`,
      330, 100, () => {
        $("dOpen").onclick = () => { call("open_file", d.path); H.hideCard(); };
        $("dShow").onclick = () => { call("show_file", d.path); H.hideCard(); };
        $("dShelf").onclick = () => { call("shelf", "add", d.path).then(() => { H.hideCard(); }); };
      }, { history: { app: "Downloads", title: d.name, text: d.size || "" } });
  }
  function snip(s) {
    popup("snip", `<img class="snip" src="${esc(s.thumb)}" alt=""><div class="ct"><div class="t">Screenshot</div><div class="s">${esc(s.size || "")}</div>
      <div class="btns"><button class="pbtn" id="sCopy">Copy</button><button class="pbtn" id="sUp">Upload</button><button class="pbtn" id="sShow">Show</button></div></div>`,
      340, 96, () => {
        $("sCopy").onclick = (e) => { call("copy_image", s.path); e.target.textContent = "Copied ✓"; H.armCard(2000); };
        $("sUp").onclick = () => call("upload_file", s.path);
        $("sShow").onclick = () => { call("show_file", s.path); H.hideCard(); };
      }, { history: { app: "Screenshots", title: "Screenshot", text: s.name || "" } });
  }
  function rain(r) {
    popup("rain", `${chip("cloud-rain", "#5ac8fa")}<div class="ct"><div class="t">${esc(r.title)}</div><div class="s">${esc(r.text || "")}</div></div>`,
      300, 72, null, { history: { app: "Weather", title: r.title, text: r.text } });
  }
  // a pop-up's icon: a Tabler line icon in its colour, on a soft tint of it
  const chip = (icon, color) => `<div class="ic-chip" style="--c:${color}">${ICON(icon, 22)}</div>`;
  function simpleCard(kind, icon, color, title, text, histApp) {
    popup(kind, `${chip(icon, color)}<div class="ct"><div class="t">${esc(title)}</div>${text ? `<div class="s">${esc(text)}</div>` : ""}</div>`,
      300, 72, null, { history: { app: histApp, title, text } });
  }

  // ---- reminders you set (every N minutes between two times)
  const remLast = {};
  setInterval(() => {
    const Lx = L(), t = new Date(now()), m = hm(t);
    (Lx.reminders || []).forEach((r, i) => {
      if (!r.on) return;
      const inside = r.from <= r.to ? m >= r.from && m < r.to : m >= r.from || m < r.to;
      if (!inside) return;
      const k = i + r.text;
      if (!remLast[k]) { remLast[k] = now(); return; }
      if (now() - remLast[k] >= r.every * 60000) {
        remLast[k] = now();
        simpleCard("reminder", "bell", "#a5a3ff", r.text, `Every ${r.every} min`, "Reminder");
      }
    });
  }, 20000);

  // ---- Jumu'ah (Fridays, before Dhuhr) and Ramadan (iftar / suhoor on the pill)
  let jumuahDone = "";
  setInterval(() => {
    const Lx = L(), pr = H.prayers(), d = new Date(now());
    if (!Lx.jumuah || !pr || !pr.today || d.getDay() !== 5) return;
    const [h, m] = pr.today.Dhuhr.split(":").map(Number);
    const at = new Date(d); at.setHours(h, m, 0, 0);
    const mins = Math.round((at - d) / 60000);
    if (mins <= Lx.jumuahMins && mins > 0 && jumuahDone !== d.toDateString()) {
      jumuahDone = d.toDateString();
      simpleCard("reminder", "building-mosque", "#ffd479", "Jumu'ah", `Dhuhr at ${timeFmt.format(at)} · in ${mins} min`, "Prayer");
    }
  }, 30000);
  function ramadanText() {
    const Lx = L(), td = H.today(), pr = H.prayers();
    if (!Lx.ramadan || !td || !td.hijri || !/rama/i.test(td.hijri.month || "") || !pr || !pr.today) return "";
    const d = new Date(now());
    const at = (hmS, plus = 0) => { const [h, m] = hmS.split(":").map(Number); const x = new Date(d); x.setDate(x.getDate() + plus); x.setHours(h, m, 0, 0); return x; };
    const fajr = at(pr.today.Fajr), maghrib = at(pr.today.Maghrib);
    const left = (to) => { const s = Math.max(0, Math.floor((to - d) / 1000)); return `${Math.floor(s / 3600)}:${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}`; };
    if (d >= fajr && d < maghrib) return `Iftar · ${left(maghrib)}`;
    const nextFajr = d < fajr ? fajr : at((pr.tomorrow || pr.today).Fajr, 1);
    return nextFajr - d < 3 * 3600000 ? `Suhoor · ${left(nextFajr)}` : "";
  }
  // countdowns you add show on the Today page with Ramadan / Eid
  const baseToday = window.__islandToday;
  window.__islandToday = (d) => {
    const cds = (L().countdowns || []).map((c) => {
      const days = Math.round((new Date(c.date + "T00:00:00") - new Date(new Date(now()).toDateString())) / 86400000);
      return { name: c.name, date: c.date, days };
    }).filter((c) => c.days >= 0);
    if (d && d.hijri) d = { ...d, hijri: { ...d.hijri, events: [...cds, ...(d.hijri.events || [])].sort((a, b) => (a.days ?? 999) - (b.days ?? 999)) } };
    baseToday(d);
    paintSlots();
    paintWeatherW(); paintPrayerW(); paintDate();
  };

  // ================================================================ GESTURES
  const ACT = {
    playpause: () => document.getElementById("play").click(),
    next: () => api.playback("next"),
    mute: () => document.getElementById("volBtn").click(),
    settings: () => api.openSettings(),
    record: () => document.getElementById("rec").click(),
    snap: () => api.recenter(),
    timer: () => (T[T.view].running ? pauseTimer(T.view) : startTimer(T.view)),
  };
  island.addEventListener("dblclick", (e) => {
    if (e.target.closest("button, input, [contenteditable], .progress, .vol-row, .card")) return;
    const f = ACT[L().dblClick]; if (f) f();
  });
  island.addEventListener("auxclick", (e) => {
    if (e.button !== 1 || e.target.closest(".sh")) return;
    const f = ACT[L().middleClick]; if (f) { e.preventDefault(); f(); }
  });

  // ---- shuffle / repeat buttons around the player's controls
  const ctr = island.querySelector(".controls");
  const shuf = document.createElement("button");
  shuf.className = "sr"; shuf.id = "shuffle"; shuf.title = "Shuffle";
  shuf.innerHTML = '<svg viewBox="0 0 24 24"><path d="M3 7h3.5c3 0 4 2 5.5 5s2.5 5 5.5 5H21m0 0-2.5-2.5M21 17l-2.5 2.5M3 17h3.5c1.4 0 2.3-.4 3-1.1M14 8.1c.7-.7 1.6-1.1 3-1.1H21m0 0-2.5-2.5M21 7l-2.5 2.5"/></svg>';
  const rep = document.createElement("button");
  rep.className = "sr"; rep.id = "repeat"; rep.title = "Repeat";
  rep.innerHTML = '<svg viewBox="0 0 24 24"><path d="M4 11V9a3 3 0 0 1 3-3h12m0 0-3-3m3 3-3 3M20 13v2a3 3 0 0 1-3 3H5m0 0 3 3m-3-3 3-3"/></svg><b class="one" hidden>1</b>';
  ctr.insertBefore(shuf, ctr.firstChild);
  ctr.appendChild(rep);
  shuf.addEventListener("click", () => { shuf.classList.toggle("on"); api.playback("shuffle"); });
  rep.addEventListener("click", () => api.playback("repeat"));
  window.__hopPlayback = (pb) => {
    shuf.hidden = !pb || pb.shuffle == null;
    rep.hidden = !pb || pb.repeat == null;
    if (!pb) return;
    shuf.classList.toggle("on", !!pb.shuffle);
    rep.classList.toggle("on", pb.repeat && pb.repeat !== "off");
    rep.querySelector(".one").hidden = pb.repeat !== "one";
    idleReset();
  };

  // ================================================================ THE HOST'S EVENTS
  const ON = {
    notif, download, snip, rain, sports,
    agents: (d) => {
      const asking = (d.sessions || []).some((x) => x.status === "ask");
      if (asking && !state.agents.some((x) => x.status === "ask")) state.askSince = now();
      state.agents = d.sessions || []; state.usage = d.usage || null; if (H.pageId() === "agents") paintAgents(); liveTick(); },
    agentAsk: agentCard,
    agentEdit,
    privacy: (d) => {
      // an app that STARTS using the microphone or camera gets a 3 s pop-up; then just the dot
      const fresh = (now, was, what) => now.filter((a) => !was.includes(a)).map((a) => [a, what]);
      const news = [...fresh(d.cam || [], state.cam, "camera"), ...fresh(d.mic || [], state.mic, "microphone")];
      state.mic = d.mic || []; state.cam = d.cam || [];
      paintPrivacy(); liveTick();
      if (news.length && L().micCamDot !== false) {
        let [app, what] = news[0];
        if (news.some(([a, w]) => a === app && w !== what)) what = "camera and microphone";   // one app, both at once
        const c = what === "camera" ? "var(--hop-green)" : "var(--hop-orange)";
        activity("privacy", Math.min(330, 190 + app.length * 7), `<div class="side"><i class="pd" style="background:${c}"></i><span class="name">${esc(app)}</span></div>
          <div class="side"><span class="dim">is using your ${what}</span></div>`, (L().popups.privacy || {}).ms || 3000);
      }
    },
    game: (on) => {
      state.gaming = !!on;
      island.classList.toggle("gaming", state.gaming);
      if (!on && state.held.length) {
        const held = state.held.splice(0);
        const P = (L().popups || {}).game;
        if (P && P.on && held.length > 1) simpleCard("game", "device-gamepad-2", "#c7c7cc", `${held.length} pop-ups while you played`, "They are on the Notifications page", "Game mode");
        else { const [k, html, w, h, after, o] = held[held.length - 1]; popup(k, html, w, h, after, { ...o, history: null }); }
      }
    },
    focus: (on) => {
      state.focus = !!on;
      activity("focus", 150, `<div class="side"><span style="color:var(--hop-purple);display:flex">${ICON("moon", 16)}</span><span>Focus</span></div><div class="side"><span class="dim">${on ? "On" : "Off"}</span></div>`, 2200);
      liveTick();
    },
    calSet: (on) => { state.calSet = !!on; },
    calendar: (evs) => { state.calendar = (evs || []).sort((a, b) => a.start - b.start); if (H.pageId() === "calendar") paintCalendar(); },
    wifi: (w) => activity("wifi", w.ssid ? Math.min(280, 150 + w.ssid.length * 7) : 160,
      `<div class="side"><svg viewBox="0 0 24 24" fill="none" stroke="${w.ssid ? "#fff" : "#ff453a"}" stroke-width="2" stroke-linecap="round"><path d="M2 8.8a15 15 0 0 1 20 0M5.5 12.5a10 10 0 0 1 13 0M9 16a5 5 0 0 1 6 0"/><circle cx="12" cy="19" r="1" fill="#fff"/></svg><span class="name">${esc(w.ssid || "Wi-Fi off")}</span></div><div class="side"><span class="dim">${w.ssid ? "Connected" : "Disconnected"}</span></div>`),
    net: (n) => { state.net = n; paintSlots(); },
    battery: (b) => { state.battery = b; paintSlots(); if (H.pageId() === "battery") paintBattery(); },
    clipStats: (c) => { state.clipStats = c; paintSlots(); },
    shelf: (items) => { state.shelf = items || []; if (H.pageId() === "shelf") paintShelf(); },
    extensions: (xs) => { state.extensions = xs || []; applyExtensions(L()); H.applyLayout(); },
    drop: (d) => {                                      // a file dropped while "ask" is set: upload it, or keep it
      H.showCard(`<div class="drop"><svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 16V4m-5 5 5-5 5 5M4 17v2a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-2"/></svg></div>
        <div class="ct"><div class="t">${esc(d.name)}</div><div class="s">What should happen to it?</div>
        <div class="btns"><button class="pbtn go" id="dUp">Upload & copy link</button><button class="pbtn" id="dShelf">Keep on shelf</button></div></div>`, 340, 100, 8000, () => {
          $("dUp").onclick = () => call("drop_choice", d.path, "upload");
          $("dShelf").onclick = () => { call("drop_choice", d.path, "shelf"); H.hideCard(); };
        });
    },
    reminder: (r) => simpleCard("reminder", r.icon || "bell", r.bg || "#a5a3ff", r.title, r.text, r.app || "Reminder"),
    update: (u) => {                                     // an update that can install itself (the original card's look)
      const dl = u.state === "downloading", inst = u.state === "installing", pct = Math.round((u.progress || 0) * 100);
      const title = inst ? "Installing update" : dl ? "Downloading update" : "Update available";
      const sub = inst ? `Hop v${esc(u.latest)} · Hop restarts on its own` : dl ? `Hop v${esc(u.latest)} · ${pct}%` : `Hop v${esc(u.latest)} is ready`;
      H.showCard(`${chip("download", "#0a84ff")}<div class="ct"><div class="t">${title}</div><div class="s">${sub}</div>
        ${inst ? '<div class="prog busy"><i></i></div>' : dl ? `<div class="prog"><i style="width:${pct}%"></i></div>`
          : '<div class="btns"><button class="pbtn go" id="uIns">Install now</button><button class="pbtn" id="uLater2">Later</button></div>'}</div>`,
        300, 100, 0, () => {
          if ($("uIns")) $("uIns").onclick = () => call("install_update");
          if ($("uLater2")) $("uLater2").onclick = () => { api.updateAnswer(false); H.hideCard(); };
        });
    },
  };
  window.__hopEvent = (kind, data) => { const f = ON[kind]; if (f) { try { f(data); } catch (e) { console.error(kind, e); } } };

  // ================================================================ APPLY THE SETTINGS
  window.__hopApply = (Lx) => {
    applyLook(Lx);
    requestAnimationFrame(() => dots.classList.toggle("many", dots.children.length > 7));
    applySlots(Lx);
    paintPrivacy();
    idleReset();
    needs();
    liveTick();
  };
  window.__hopHover = (on) => {
    idleReset();
    if (on) { const id = H.pageId(); if (id) window.__hopPage(id); }
    else prompterRun(false);
  };
  // in the settings app's preview: say how big the island is right now, so
  // the preview can zoom to it (a small card or the closed pill fills the stage)
  if (window.__islandPreview && window.ResizeObserver) {
    let last = "";
    new ResizeObserver(() => {
      const r = island.getBoundingClientRect(), k = `${Math.round(r.width)}x${Math.round(r.height)}`;
      if (k === last) return;
      last = k;
      window.parent.postMessage({ t: "isl", w: r.width, h: r.height, top: r.top }, "*");
    }).observe(island);
  }
  if (H.layout()) window.__hopApply(H.layout());
  // the real shape is on: show the island (it fades in already the right size)
  requestAnimationFrame(() => requestAnimationFrame(() => root.classList.remove("booting")));
  // everything the host already knows, once at start
  call("hop_hello").then((d) => {
    if (!d) return;
    for (const [k, v] of Object.entries(d)) window.__hopEvent(k, v);
  });
  H.applyLayout();                              // the pages built above join the layout's order
})();
