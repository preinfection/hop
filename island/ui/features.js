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
  function applyLook(L) {
    const notch = L.style === "notch";
    const st = root.style;
    st.setProperty("--w", (notch ? L.notchW : L.pillW) + "px");
    fitW = 0;
    st.setProperty("--h", (notch ? L.notchH : L.pillH) + "px");
    st.setProperty("--w-wide", Math.max(notch ? L.notchW : 176, notch ? L.notchW : L.pillW) + "px");
    st.setProperty("--open-w", L.openW + "px");
    st.setProperty("--open-h", L.openH + "px");
    const rc = L.radiusClosed >= 0 ? L.radiusClosed : notch ? 10 : Math.round(L.pillH / 2);
    const ro = L.radiusOpen >= 0 ? L.radiusOpen : notch ? 24 : 40;
    st.setProperty("--r-closed", rc + "px");
    st.setProperty("--r-open", ro + "px");
    const a = L.bgOpacity / 100;
    const [r, g, b] = rgb(L.bg);
    const dark = `rgba(${r * 0.55 | 0}, ${g * 0.55 | 0}, ${b * 0.55 | 0}, ${a})`;
    st.setProperty("--isl-bg", L.bgStyle === "gradient" ? `linear-gradient(180deg, ${rgba(L.bg, a)}, ${dark})`
      : L.bgStyle === "tint" ? `linear-gradient(180deg, color-mix(in srgb, var(--accent) 22%, ${rgba(L.bg, a)}), ${rgba(L.bg, a)})`
      : rgba(L.bg, a));
    st.setProperty("--isl-ring", L.border ? `inset 0 0 0 1px ${rgba(L.borderColor, L.borderOpacity / 100)}` : "0 0 0 0 transparent");
    st.setProperty("--isl-glow", L.glow ? "0 4px 22px -2px color-mix(in srgb, var(--accent) 55%, transparent)" : "0 0 0 0 transparent");
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
  let slotKey = "";
  function applySlots(L) {
    const want = { l: L.slotLeft, c: L.slotCenter, r: L.slotRight };
    const key = JSON.stringify(want);
    if (key === slotKey) return;
    slotKey = key;
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
    if (slotted("timer")) NODES.timer.textContent = timer.running || timer.left > 0 || timer.mode === "watch" && timer.elapsed > 0 ? fmtTimer() : "–:––";
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
      NODES.battery.innerHTML = b && b.pct != null ? `${b.pct}<span class="u">%${b.charging ? "⚡" : ""}</span>` : "–";
    }
    if (slotted("weather")) {
      const w = H.today() && H.today().weather;
      NODES.weather.textContent = w ? `${wxIcon(w.code)} ${Math.round(w.temp)}°` : "–";
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
  let fitW = 0;
  function fitPill() {
    const Lx = L(); if (!Lx.pillW) return;
    const base = Lx.style === "notch" ? Lx.notchW : Lx.pillW;
    const l = slotBox.l.offsetWidth, c = slotBox.c.offsetWidth, r = slotBox.r.offsetWidth;
    const need = Math.ceil(c ? c + 2 * Math.max(14 + l, 17 + r) : l + r + 34);
    const w = Math.max(base, Math.min(Lx.openW, need));
    if (w === fitW) return;
    fitW = w;
    root.style.setProperty("--w", w + "px");
    if (!Lx.style || Lx.style !== "notch") root.style.setProperty("--w-wide", Math.max(176, w) + "px");
    H.settlePill();
  }
  const speed = (bps) => bps >= 1e6 ? `${(bps / 1e6).toFixed(bps >= 1e7 ? 0 : 1)}M` : bps >= 1e3 ? `${Math.round(bps / 1e3)}K` : `${Math.round(bps || 0)}B`;
  const wxIcon = (c) => c === 0 ? "☀️" : c <= 2 ? "🌤️" : c === 3 ? "☁️" : c <= 48 ? "🌫️" : c <= 67 ? "🌧️" : c <= 77 ? "❄️" : c <= 82 ? "🌦️" : "⛈️";

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
      if (kind === "timer" && (timer.running || (timer.mode === "watch" && timer.elapsed > 0 && timer.running))) { text = fmtTimer(); color = "var(--hop-orange)"; break; }
      if (kind === "agent" && state.agents.some((s) => s.status === "ask")) { text = "Agent waiting"; color = "var(--hop-orange)"; pulse = true; break; }
      if (kind === "focus" && state.focus) { text = "☾ Focus"; color = "var(--hop-purple)"; break; }
      if (kind === "mic" && state.mic.length) { text = "● Mic on"; color = "var(--hop-orange)"; break; }
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
    pdot.className = "pdot" + (on && state.cam.length ? " cam" : on && state.mic.length ? " mic" : "");
    pdot.title = [...state.cam.map((a) => a + " · camera"), ...state.mic.map((a) => a + " · microphone")].join("\n");
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
    if (quietNow() && kind !== "caps") return;
    clearTimeout(actTimer);
    H.growPill(w).then(() => {
      $("actView").innerHTML = html;
      island.style.setProperty("--act-w", w + "px");
      island.classList.add("act");
    });
    actTimer = setTimeout(() => { island.classList.remove("act"); H.settlePill(); }, ms || (P && P.ms) || 2500);
    idleReset();
  }

  // ================================================================ PAGES (built here, ordered by the layout)
  const PAGE_HTML = {
    agents: `<div class="ph"><span>Agents</span><span class="sub" id="agSub"></span></div>
      <div class="rows scrolls" id="agRows"></div><div class="usage" id="agUsage" hidden></div>`,
    timer: `<div class="tm-modes" id="tmModes"><button data-m="timer" class="on">Timer</button><button data-m="watch">Stopwatch</button><button data-m="pomo">Focus</button></div>
      <div class="tm-big scrolls" id="tmBig" title="Scroll to change">5:00</div><div class="tm-sub" id="tmSub"></div>
      <div class="tm-row" id="tmRow"></div>`,
    calendar: `<div class="ph"><span id="calHead">Today</span><button class="lnk" id="calOpen">Open calendar</button></div><div class="rows scrolls" id="calRows"></div>`,
    alerts: `<div class="ph"><span>Notifications</span><button class="lnk" id="alClear">Clear</button></div><div class="rows scrolls" id="alRows"></div>`,
    shelf: `<div class="ph"><span>Shelf</span><span class="sub" id="shSub">Drop files on the island</span></div><div class="sh-items" id="shItems"></div>`,
    notes: `<div class="ph"><span>Notes</span><span class="sub" id="ntSub">Saved</span></div><div class="notes scrolls" id="notes" contenteditable="plaintext-only" spellcheck="false"></div>`,
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
  window.__hopPage = (id) => {
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
  const AGENT = {
    claude: ["#d97757", "C"], codex: ["#10a37f", "X"], gemini: ["#4f8cf7", "G"], cursor: ["#e6e6e6", "Cu"],
    copilot: ["#8957e5", "Co"], other: ["#8e8e93", "•"],
  };
  const ST = { work: "Working", ask: "Needs you", done: "Done", idle: "Idle" };
  const mascot = (tool, status) => { const [c, l] = AGENT[tool] || AGENT.other; return `<span class="mascot ${status}" style="background:${c}">${l}</span>`; };
  function paintAgents() {
    const rows = $("agRows");
    if (!rows) return;
    const ss = state.agents;
    $("agSub").textContent = ss.length ? `${ss.filter((s) => s.status === "work").length} working` : "";
    rows.innerHTML = ss.length ? ss.slice(0, 6).map((s, i) => `<div class="row click" data-i="${i}">${mascot(s.tool, s.status)}
        <div class="grow"><div class="t1">${esc(s.name)}</div><div class="t2">${esc(s.detail || "")}</div></div>
        <span class="ag-st ${s.status}">${ST[s.status] || s.status}</span></div>`).join("")
      : `<div class="empty-note">No agents running.<br>Connect Claude Code in Settings → AI agents, then start a session.</div>`;
    rows.querySelectorAll(".row[data-i]").forEach((r) => r.addEventListener("click", () => call("agent_jump", ss[+r.dataset.i].id)));
    const u = state.usage, box = $("agUsage");
    box.hidden = !u;
    if (u) box.innerHTML = [["5-hour", u.five, u.fiveReset], ["Week", u.week, u.weekReset]].map(([n, p, r]) =>
      `<div style="flex:1">${n} · ${Math.round(p)}%${r ? ` · resets ${esc(r)}` : ""}<div class="bar"><i class="${p >= 80 ? "hot" : ""}" style="width:${Math.min(100, p)}%"></i></div></div>`).join("");
  }
  function agentCard(a) {
    if (!L().agentsOn) return;
    const head = (t) => `${mascot(a.tool, "ask").replace("mascot", "ic-sq mascot")}<div class="ct"><div class="t">${esc(t)}</div>`;
    if (a.kind === "permission") {
      popup("agent", `${head(`${a.name} wants to ${a.verb || "run"}`)}<div class="body">${esc(a.summary || "")}</div>
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
        <input class="fb" id="aFb" placeholder="Feedback (optional), then Keep planning">
        <div class="btns"><button class="pbtn ok2" id="aGo">Approve</button><button class="pbtn" id="aMore">Keep planning</button></div></div>`,
        360, 196, () => {
          document.querySelector(".card").classList.add("tall");
          $("aGo").onclick = () => { call("agent_answer", a.id, "allow"); H.hideCard(); };
          $("aMore").onclick = () => { call("agent_answer", a.id, { deny: $("aFb").value || "Keep planning." }); H.hideCard(); };
        }, { sticky: true, history: { app: a.name, title: "Plan", text: (a.plan || "").slice(0, 80) } });
    } else if (a.kind === "done") {
      popup("agent", `${mascot(a.tool, "done").replace("mascot", "ic-sq mascot")}<div class="ct"><div class="t">${esc(a.name)} is done</div>
        <div class="body">${esc(a.summary || "Finished its turn")}</div>
        <div class="btns"><button class="pbtn go" id="aJump">Jump to it</button></div></div>`, 320, 100, () => {
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
  const timer = store.get("timer", { mode: "timer", set: 300000, left: 300000, elapsed: 0, running: false, endAt: 0, startAt: 0, pomo: { phase: "work", round: 1 } });
  timer.running = false;                              // a restart doesn't resume a countdown silently
  const POMO = { work: 25 * 60000, break: 5 * 60000, long: 15 * 60000 };
  function fmtTimer() {
    const ms = timer.mode === "watch" ? (timer.running ? now() - timer.startAt + timer.elapsed : timer.elapsed)
      : timer.running ? Math.max(0, timer.endAt - now()) : timer.left;
    const s = Math.floor((timer.mode === "watch" ? ms : ms + 999) / 1000);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), ss = String(s % 60).padStart(2, "0");
    return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
  }
  function paintTimer() {
    if (!$("tmBig")) return;
    $("tmBig").textContent = fmtTimer();
    $("tmBig").classList.toggle("run", timer.running);
    [...$("tmModes").children].forEach((b) => b.classList.toggle("on", b.dataset.m === timer.mode));
    $("tmSub").textContent = timer.mode === "pomo" ? `${timer.pomo.phase === "work" ? "Focus" : "Break"} · round ${timer.pomo.round} of 4` : "";
    const presets = timer.mode === "timer" ? [1, 5, 10, 25].map((m) => `<button class="lnk" data-p="${m}">${m}m</button>`).join("") : "";
    $("tmRow").innerHTML = `${presets}<button class="lnk go" id="tmGo">${timer.running ? "Pause" : "Start"}</button><button class="lnk" id="tmReset">Reset</button>`;
    $("tmGo").onclick = () => (timer.running ? pauseTimer() : startTimer());
    $("tmReset").onclick = resetTimer;
    $("tmRow").querySelectorAll("[data-p]").forEach((b) => b.onclick = () => { timer.set = timer.left = +b.dataset.p * 60000; save(); paintTimer(); });
  }
  const save = () => store.set("timer", timer);
  function startTimer() {
    if (timer.mode === "watch") { timer.startAt = now(); }
    else { if (timer.left <= 0) timer.left = timer.mode === "pomo" ? POMO[timer.pomo.phase] : timer.set; timer.endAt = now() + timer.left; }
    timer.running = true; save(); paintTimer();
  }
  function pauseTimer() {
    if (timer.mode === "watch") timer.elapsed += now() - timer.startAt;
    else timer.left = Math.max(0, timer.endAt - now());
    timer.running = false; save(); paintTimer();
  }
  function resetTimer() {
    timer.running = false; timer.elapsed = 0;
    timer.pomo = { phase: "work", round: 1 };
    timer.left = timer.mode === "pomo" ? POMO.work : timer.set;
    save(); paintTimer();
  }
  function timerDone() {
    timer.running = false; timer.left = 0;
    let title = "Time's up", sub = `${H.clipLen(timer.set / 1000)} timer`;
    if (timer.mode === "pomo") {
      const was = timer.pomo.phase;
      if (was === "work") { timer.pomo.phase = timer.pomo.round % 4 === 0 ? "long" : "break"; title = "Focus done"; sub = "Time for a break"; }
      else { timer.pomo.phase = "work"; timer.pomo.round = timer.pomo.round % 4 + 1; title = "Break over"; sub = `Round ${timer.pomo.round}`; }
      timer.left = POMO[timer.pomo.phase];
    }
    save(); paintTimer();
    popup("timer", `<div class="ic-sq" style="background:var(--hop-orange)">⏱</div><div class="ct"><div class="t">${title}</div><div class="s">${sub}</div>
      <div class="btns">${timer.mode === "pomo" ? '<button class="pbtn warn" id="tNext">Start next</button>' : '<button class="pbtn" id="tAgain">Again</button>'}<button class="pbtn" id="tOk">OK</button></div></div>`,
      280, 100, () => {
        $("tOk").onclick = () => H.hideCard();
        if ($("tNext")) $("tNext").onclick = () => { startTimer(); H.hideCard(); };
        if ($("tAgain")) $("tAgain").onclick = () => { timer.left = timer.set; startTimer(); H.hideCard(); };
      }, { history: { app: "Timer", title, text: sub } });
  }
  $("tmModes").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-m]"); if (!b || timer.running) return;
    timer.mode = b.dataset.m; resetTimer();
  });
  $("tmBig").addEventListener("wheel", (e) => {
    e.preventDefault();
    if (timer.running || timer.mode !== "timer") return;
    timer.set = timer.left = Math.max(60000, Math.min(99 * 60000, timer.left + (e.deltaY < 0 ? 60000 : -60000)));
    save(); paintTimer();
  }, { passive: false });
  setInterval(() => {
    if (!timer.running) return;
    if (timer.mode !== "watch" && now() >= timer.endAt) timerDone();
    if (H.pageId() === "timer" && H.isOpen()) $("tmBig").textContent = fmtTimer();
  }, 250);
  paintTimer();
  window.__hopTimer = { start: (ms) => { timer.mode = "timer"; timer.set = timer.left = ms; startTimer(); }, state: () => ({ ...timer }) };

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
    rows.querySelectorAll("[data-j]").forEach((b) => b.onclick = () => call("open_url", soon[+b.dataset.j].link));
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
      340, n.text ? 96 : 72, null, { history: { app: n.app, title: n.title, text: n.text } });
  }
  function paintAlerts() {
    const rows = $("alRows");
    if (!rows) return;
    rows.innerHTML = state.history.length ? state.history.slice(0, 20).map((h) => `<div class="row">
        <span class="ic-sq" style="width:20px;height:20px;border-radius:6px;font-size:10px;background:${APPC[h.app] || "#3a3a3c"};color:#fff;display:grid;place-items:center">${esc(letter(h.app))}</span>
        <div class="grow"><div class="t1">${esc(h.title || h.app)}</div><div class="t2">${esc(h.text || h.app || "")}</div></div>
        <span class="tm">${H.ago(h.at / 1000)}</span></div>`).join("")
      : `<div class="empty-note">Nothing yet. Pop-ups you get (and the ones held back in quiet hours or games) land here.</div>`;
  }
  $("alClear").addEventListener("click", () => { state.history = []; store.set("history", []); paintAlerts(); });

  // ---------------------------------------------------------------- SHELF (files parked on the island)
  const ext = (n) => (n.split(".").pop() || "").slice(0, 4).toUpperCase();
  function loadShelf() { call("get_shelf").then((items) => { state.shelf = items || []; paintShelf(); }); }
  function paintShelf() {
    const box = $("shItems");
    if (!box) return;
    $("shSub").textContent = state.shelf.length ? `${state.shelf.length} item${state.shelf.length === 1 ? "" : "s"}` : "Drop files on the island";
    box.innerHTML = state.shelf.length ? state.shelf.slice(0, 5).map((it, i) => `<div class="sh" data-i="${i}" title="${esc(it.path)}">
        ${it.pinned ? '<span class="pin">📌</span>' : ""}<button class="x" data-x="${i}" title="Remove">×</button>
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
        popup("sports", `<div class="ic-sq" style="background:#fff">⚽</div><div class="ct"><div class="s">${esc(m.league)} · ${esc(m.status)}</div>
          <div class="t">${esc(m.home)} ${m.hs} – ${m.as} ${esc(m.away)}</div></div>`, 320, 72, null,
          { history: { app: "Scores", title: `${m.home} ${m.hs} – ${m.as} ${m.away}`, text: m.status } });
      }
      lastScores[k] = sc;
    }
    state.sports = ms;
    if (H.pageId() === "sports") paintSports();
  }

  // ---------------------------------------------------------------- TELEPROMPTER
  let prY = 0, prAnim = 0, prLast = 0;
  function loadPrompter() {
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
      $("prText").style.transform = `translateY(${(48 - prY).toFixed(1)}px)`;
      $("prInfo").textContent = `${L().prompterSpeed || 40} px/s`;
      if (state.prompter.playing) prAnim = requestAnimationFrame(step);
    };
    prAnim = requestAnimationFrame(step);
  }
  $("prPlay").addEventListener("click", () => { state.prompter.playing = !state.prompter.playing; prompterRun(state.prompter.playing); });
  $("prBack").addEventListener("click", () => { prY = 0; $("prText").style.transform = "translateY(48px)"; });
  $("prText").style.transform = "translateY(48px)";

  // ---------------------------------------------------------------- BATTERY
  function paintBattery() {
    const b = state.battery;
    if (!b || !$("btPct")) return;
    $("btPct").textContent = b.pct == null ? "No battery" : `${b.pct}%`;
    $("btFill").style.width = `${b.pct || 0}%`;
    $("btFill").classList.toggle("low", (b.pct || 0) <= 15);
    const left = b.minutes ? `${Math.floor(b.minutes / 60)}h ${b.minutes % 60}m ${b.charging ? "to full" : "left"}` : b.charging ? "Charging" : "";
    $("btMeta").innerHTML = [left && `<b>${left}</b>`, b.health != null && `Health <b>${b.health}%</b>${b.cycles ? ` · ${b.cycles} cycles` : ""}`,
      b.design && `${(b.full / 1000).toFixed(1)} of ${(b.design / 1000).toFixed(1)} Wh`].filter(Boolean).join("<br>");
    const ds = (b.drainers || []).slice(0, 3);
    $("btRows").innerHTML = ds.length ? `<div class="bt-chips"><span class="lbl">Using most</span>${ds.map((d) => `<span class="chip">${esc(d.name)} <b>${d.cpu.toFixed(0)}%</b></span>`).join("")}</div>` : "";
  }

  // ---------------------------------------------------------------- EXTENSIONS (your own pages)
  function applyExtensions(L) {
    const on = new Set(L.extensions || []);
    document.querySelectorAll(".pg[data-ext]").forEach((p) => { if (!on.has(p.dataset.ext)) p.remove(); });
    for (const x of state.extensions) {
      if (!on.has(x.id) || document.querySelector(`.pg[data-ext="${x.id}"]`)) continue;
      const pg = document.createElement("div");
      pg.className = "pg pg-ext";
      pg.dataset.id = "ext-" + x.id;
      pg.dataset.ext = x.id;
      pg.innerHTML = `<iframe sandbox="allow-scripts" src="${esc(x.url)}" title="${esc(x.name)}"></iframe>`;
      full.insertBefore(pg, dots);
    }
  }
  // an extension may ask for a pop-up: postMessage({hop: "popup", title, text})
  window.addEventListener("message", (e) => {
    const m = e.data || {};
    if (m.hop !== "popup" || !document.querySelector(".pg-ext iframe")) return;
    const frame = [...document.querySelectorAll(".pg-ext iframe")].find((f) => f.contentWindow === e.source);
    if (!frame) return;
    popup("notif", `<div class="ic-sq" style="background:#3a3a3c;color:#fff">${esc(letter(frame.title))}</div><div class="ct"><div class="s">${esc(frame.title)}</div>
      <div class="t">${esc(String(m.title || "").slice(0, 80))}</div>${m.text ? `<div class="body">${esc(String(m.text).slice(0, 200))}</div>` : ""}</div>`,
      320, m.text ? 96 : 72, null, { history: { app: frame.title, title: m.title, text: m.text } });
  });

  // ================================================================ CARDS
  // ---- the clip-saved card: Open / Copy / Upload & copy link / Trim
  const UPLOAD_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 15V4m-4.5 4.5L12 4l4.5 4.5M5 15v3.5A1.5 1.5 0 0 0 6.5 20h11a1.5 1.5 0 0 0 1.5-1.5V15"/></svg>';
  const TRIM_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="6" r="2.6"/><circle cx="6" cy="18" r="2.6"/><path d="M8.2 7.4 20 17M8.2 16.6 20 7"/></svg>';
  window.__islandClip = (c) => {
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
      }, { history: { app: "Clipper", title: label, text: c.name || "" } });
  };
  function trimCard(c) {
    const dur = c.seconds || 30;
    let a = 0, b = dur;
    H.showCard(`<video src="${esc(c.url)}" muted autoplay loop playsinline></video>
      <div class="ct" style="min-width:170px"><div class="t">Trim</div>
      <div class="trim" id="trim"><div class="tr-rail"></div><div class="tr-sel" id="trSel"></div><div class="tr-h" id="trA"></div><div class="tr-h" id="trB"></div></div>
      <div class="trim-lbl" id="trLbl"></div>
      <div class="btns"><button class="pbtn warn" id="trSave">Save</button><button class="pbtn" id="trNo">Cancel</button></div></div>`,
      360, 112, 0, () => {
        const v = document.querySelector(".card video"), bar = $("trim");
        const paint = () => {
          const w = bar.offsetWidth;
          $("trA").style.left = (a / dur) * w + "px"; $("trB").style.left = (b / dur) * w + "px";
          $("trSel").style.left = (a / dur) * w + "px"; $("trSel").style.width = ((b - a) / dur) * w + "px";
          $("trLbl").textContent = `${a.toFixed(1)}s – ${b.toFixed(1)}s · ${(b - a).toFixed(1)}s`;
        };
        const drag = (which) => (e) => {
          e.stopPropagation();
          const h = e.currentTarget; h.setPointerCapture(e.pointerId);
          const move = (ev) => {
            const r = bar.getBoundingClientRect(), t = Math.min(dur, Math.max(0, ((ev.clientX - r.left) / r.width) * dur));
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
        $("trNo").onclick = () => H.hideCard();
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
    popup("download", `<div class="ic-sq" style="background:var(--hop-blue)">${DL}</div><div class="ct"><div class="s">Downloaded · ${esc(d.size || "")}</div>
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
    popup("rain", `<div class="ic-sq" style="background:#0a3d7a;font-size:22px">🌧️</div><div class="ct"><div class="t">${esc(r.title)}</div><div class="s">${esc(r.text || "")}</div></div>`,
      300, 72, null, { history: { app: "Weather", title: r.title, text: r.text } });
  }
  function simpleCard(kind, icon, bg, title, text, histApp) {
    popup(kind, `<div class="ic-sq" style="background:${bg};font-size:20px">${icon}</div><div class="ct"><div class="t">${esc(title)}</div>${text ? `<div class="s">${esc(text)}</div>` : ""}</div>`,
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
        simpleCard("reminder", "🔔", "#5e5ce6", r.text, `Every ${r.every} min`, "Reminder");
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
      simpleCard("reminder", "🕌", "#3a2f10", "Jumu'ah", `Dhuhr at ${timeFmt.format(at)} · in ${mins} min`, "Prayer");
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
  };

  // ================================================================ GESTURES
  const ACT = {
    playpause: () => document.getElementById("play").click(),
    next: () => api.playback("next"),
    mute: () => document.getElementById("volBtn").click(),
    settings: () => api.openSettings(),
    record: () => document.getElementById("rec").click(),
    snap: () => api.recenter(),
    timer: () => (timer.running ? pauseTimer() : startTimer()),
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
    agents: (d) => { state.agents = d.sessions || []; state.usage = d.usage || null; if (H.pageId() === "agents") paintAgents(); liveTick(); },
    agentAsk: agentCard,
    agentEdit,
    privacy: (d) => { state.mic = d.mic || []; state.cam = d.cam || []; paintPrivacy(); liveTick(); },
    game: (on) => {
      state.gaming = !!on;
      island.classList.toggle("gaming", state.gaming);
      if (!on && state.held.length) {
        const held = state.held.splice(0);
        const P = (L().popups || {}).game;
        if (P && P.on && held.length > 1) simpleCard("game", "🎮", "#30363d", `${held.length} pop-ups while you played`, "They are on the Notifications page", "Game mode");
        else { const [k, html, w, h, after, o] = held[held.length - 1]; popup(k, html, w, h, after, { ...o, history: null }); }
      }
    },
    focus: (on) => {
      state.focus = !!on;
      activity("focus", 150, `<div class="side"><span style="color:var(--hop-purple)">☾</span><span>Focus</span></div><div class="side"><span class="dim">${on ? "On" : "Off"}</span></div>`, 2200);
      liveTick();
    },
    calSet: (on) => { state.calSet = !!on; },
    calendar: (evs) => { state.calendar = (evs || []).sort((a, b) => a.start - b.start); if (H.pageId() === "calendar") paintCalendar(); },
    caps: (on) => activity("caps", 150, `<div class="side"><span class="kbd">⇪</span><span>Caps Lock</span></div><div class="side"><span style="color:${on ? "var(--hop-green)" : "var(--dim)"}">${on ? "On" : "Off"}</span></div>`),
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
    reminder: (r) => simpleCard("reminder", r.icon || "🔔", r.bg || "#5e5ce6", r.title, r.text, r.app || "Reminder"),
    update: (u) => {                                     // an update that can install itself
      H.showCard(`<div class="upd-mark"><svg viewBox="0 0 24 24" fill="none" stroke="#0a84ff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10" stroke-opacity=".4"/><path d="M12 6.8v9M8.2 12.3 12 16.1l3.8-3.8"/></svg></div>
        <div class="ct"><div class="t">${u.state === "downloading" ? `Downloading v${esc(u.latest)}…` : `Hop v${esc(u.latest)}`}</div>
        <div class="s">${u.state === "downloading" ? `${Math.round((u.progress || 0) * 100)}%` : "Installs in the background, then restarts"}</div>
        ${u.state === "downloading" ? `<div class="prog"><i style="width:${Math.round((u.progress || 0) * 100)}%"></i></div>` : '<div class="btns"><button class="pbtn go" id="uIns">Install now</button><button class="pbtn" id="uLater2">Later</button></div>'}</div>`,
        320, 100, 0, () => {
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
  if (H.layout()) window.__hopApply(H.layout());
  // everything the host already knows, once at start
  call("hop_hello").then((d) => {
    if (!d) return;
    for (const [k, v] of Object.entries(d)) window.__hopEvent(k, v);
  });
  H.applyLayout();                              // the pages built above join the layout's order
})();
