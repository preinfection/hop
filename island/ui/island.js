// The island: compact pill that opens while the mouse is over it.
// Talks to the host through window.lyricsIsland (bridge.js).
(() => {
  const api = window.lyricsIsland;
  const $ = (id) => document.getElementById(id);
  const island = $("island");
  const els = {
    miniArt: $("miniArt"), title: $("title"), artist: $("artist"),
    cur: $("cur"), left: $("left"), fill: $("fill"), progress: $("progress")
  };

  let pb = null;            // latest playback from the host
  let sampledAt = 0;        // when pb.progressMs was true
  let artUrl = "";
  let isOpen = false;
  let ticker = 0;

  // ---- a title / artist too long for its line scrolls instead of ending in
  // "…": hold 1.6 s, glide left at a steady speed, and a copy trailing one gap
  // behind lands exactly where the text started, so the loop has no seam.
  // Runs only while the island is open.
  const MQ_GAP = 36, MQ_SPEED = 34, MQ_HOLD = 1600;
  function marquee(box) {
    const track = box.querySelector(".mq-track"), a = track.querySelector(".mq-a");
    let anim = null, copy = null, key = "", live = false;
    function measure() {
      const text = a.textContent, over = a.scrollWidth - (box.clientWidth - parseFloat(getComputedStyle(box).paddingLeft)) > 1;
      const k = over ? text + "|" + a.scrollWidth : "";
      if (k === key) return;
      key = k;
      if (anim) { anim.cancel(); anim = null; }
      if (copy) { copy.remove(); copy = null; }
      box.classList.toggle("mq-on", over);
      if (!over) return;
      copy = a.cloneNode(true);
      copy.removeAttribute("id");
      copy.querySelectorAll("[id]").forEach((n) => n.removeAttribute("id"));
      copy.setAttribute("aria-hidden", "true");
      track.appendChild(copy);
      const dist = a.offsetWidth + MQ_GAP, glide = (dist / MQ_SPEED) * 1000, total = MQ_HOLD + glide;
      anim = track.animate([
        { transform: "translateX(0)", offset: 0 },
        { transform: "translateX(0)", offset: MQ_HOLD / total },
        { transform: `translateX(${-dist}px)`, offset: 1 }
      ], { duration: total, iterations: Infinity, easing: "linear" });
      if (!live) anim.pause();
    }
    const ro = new ResizeObserver(measure);
    ro.observe(box);
    ro.observe(a);
    return {
      run(on) {
        live = on;
        measure();
        if (!anim) return;
        if (on) { anim.currentTime = 0; anim.play(); } else anim.pause();
      }
    };
  }
  const marquees = [...document.querySelectorAll(".mq")].map(marquee);

  const fmt = (ms) => {
    const s = Math.max(0, Math.floor(ms / 1000));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  };

  const progressNow = () => {
    if (!pb) return 0;
    const p = pb.progressMs + (pb.isPlaying ? performance.now() - sampledAt : 0);
    return Math.min(p, pb.durationMs || p);
  };

  function paintProgress() {
    paintLyric();
    if (!pb || !pb.durationMs) return;
    const p = progressNow();
    els.fill.style.transform = `scaleX(${p / pb.durationMs})`;
    els.cur.textContent = fmt(p);
    els.left.textContent = "-" + fmt(pb.durationMs - p);
  }

  // The waveform takes its colour from the artwork, like iOS does.
  function accentFrom(img) {
    if (layout && layout.accentMode === "custom") { island.style.setProperty("--accent", layout.accentColor); return; }
    if (off("artColor")) { island.style.setProperty("--accent", "#fff"); return; }
    try {
      const c = document.createElement("canvas");
      c.width = c.height = 8;
      const g = c.getContext("2d");
      g.drawImage(img, 0, 0, 8, 8);
      const d = g.getImageData(0, 0, 8, 8).data;
      let r = 0, gr = 0, b = 0, n = 0;
      for (let i = 0; i < d.length; i += 4) {
        const max = Math.max(d[i], d[i + 1], d[i + 2]), min = Math.min(d[i], d[i + 1], d[i + 2]);
        const w = 1 + (max - min) / 32;           // favour colourful pixels
        r += d[i] * w; gr += d[i + 1] * w; b += d[i + 2] * w; n += w;
      }
      r /= n; gr /= n; b /= n;
      const lift = 200 / Math.max(r, gr, b, 1);   // keep it bright on black
      const k = Math.max(1, lift);
      island.style.setProperty("--accent", `rgb(${Math.min(255, r * k) | 0}, ${Math.min(255, gr * k) | 0}, ${Math.min(255, b * k) | 0})`);
    } catch {
      island.style.setProperty("--accent", "#fff");
    }
  }

  function render(state) {
    const p = state && state.playback;
    pb = p && !p.empty ? p : null;
    sampledAt = performance.now();
    island.classList.toggle("empty", !pb);
    island.classList.toggle("playing", !!(pb && pb.isPlaying));
    if (!pb) {
      els.title.textContent = "Nothing playing";
      els.artist.textContent = "";
      $("by").textContent = "";
      // FORGET the last song: its cover, accent and position stayed on screen
      // until the next song or a restart (seen 2026-10-01 after a video ended)
      if (artUrl) {
        artUrl = "";
        for (const img of [els.miniArt, $("headArt")]) { img.onerror = null; img.removeAttribute("src"); img.style.visibility = "hidden"; }
        island.style.setProperty("--accent", "#fff");
      }
      els.fill.style.transform = "scaleX(0)";
      els.cur.textContent = "0:00";
      els.left.textContent = "-0:00";
      if (lyr.key) setLyrics({ key: "", lines: [] });
      if (window.__hopPlayback) window.__hopPlayback(null);
      return;
    }
    els.title.textContent = pb.track;
    els.artist.textContent = pb.artist;
    $("by").textContent = pb.artist || "";
    if (lyr.key && lyr.key !== pb.uri) setLyrics({ key: "", lines: [] });
    if ((pb.artworkUrl || "") !== artUrl) {
      artUrl = pb.artworkUrl || "";
      for (const img of [els.miniArt, $("headArt")]) {
        img.style.visibility = artUrl ? "" : "hidden";      // a grey tile, not a broken-image icon
        if (!artUrl) { img.removeAttribute("src"); continue; }
        let retried = false;
        img.onerror = () => {                                 // written a moment late: one more try
          if (retried) return;
          retried = true;
          setTimeout(() => { img.src = artUrl + "?r=" + Date.now(); }, 300);
        };
        img.src = artUrl;
      }
      if (artUrl) els.miniArt.onload = () => accentFrom(els.miniArt);
    }
    if (window.__hopPlayback) window.__hopPlayback(pb);
    paintProgress();
  }

  // ---- hover open / close. The host watches the real cursor and resizes the
  // window (page mouse events misfire while the window changes size); this
  // only runs the animation.
  window.__islandHover = (on) => {
    if (on === isOpen) return;
    isOpen = on;
    if (window.__hopHover) window.__hopHover(on);
    clearInterval(ticker);
    marquees.forEach((m) => m.run(on && !off("marquee")));
    if (on) {
      requestAnimationFrame(() => island.classList.add("open"));
      paintProgress();
      ticker = setInterval(paintProgress, 250);
    } else {
      island.classList.remove("open");
      closeVol(true);
      setTimeout(() => { if (!isOpen) setPage(0); }, 420);   // back to the first page for next time
      pcActive(false);
    }
  };

  // ---- pages: scroll down on the open island for Today, up for the player
  // pages: 0 player, 1 Today, 2 recent clips, 3 PC & utility
  // Which pages show, and in what order, comes from the layout (settings app).
  const full = document.querySelector(".full");
  let ALL_PAGES = [...document.querySelectorAll(".full .pg")];
  let PAGES = ALL_PAGES.slice();
  let page = 0, pageAt = 0;
  const pageId = (n) => PAGES[n] && PAGES[n].dataset.id;
  function setPage(n, force) {
    n = Math.max(0, Math.min(PAGES.length - 1, n));
    if (n === page && !force) return;
    page = n;
    PAGES.forEach((p, i) => { p.classList.toggle("on", i === n); p.classList.toggle("above", i < n); });
    document.querySelectorAll(".pg-dots i").forEach((d, i) => d.classList.toggle("on", i === n));
    const id = pageId(n);
    // a widget page (board) shows several kinds at once: each one wakes up
    const ids = PAGES[n] && PAGES[n].dataset.widgets ? PAGES[n].dataset.widgets.split(",") : [id];
    if (!ids.includes("music")) closeVol(true);
    if (ids.includes("today")) paintToday();
    if (ids.includes("clips")) loadClips();
    pcActive(ids.includes("pc"));
    if (window.__hopPage) ids.forEach((w) => window.__hopPage(w));
    if (window.__hopTab) window.__hopTab(n);
    if (window.__hopDividers) requestAnimationFrame(window.__hopDividers);
    island.classList.toggle("on-last", n === PAGES.length - 1);
    island.classList.toggle("last-music", pageId(PAGES.length - 1) === "music");
  }
  window.__islandSetPage = (n) => setPage(n, true);
  window.__islandPageIds = () => PAGES.map((p) => p.dataset.id);

  let layout = null;
  const FLAGS = { lyricLine: "no-lyric", progress: "no-progress", controls: "no-controls", volume: "no-vol",
                  snap: "no-snap", pillArt: "pill-no-art", pillClock: "pill-no-clock", pillBars: "pill-no-bars",
                  todayHijri: "no-hij", todayEvents: "no-evts", todayWeather: "no-wx", todayPrayers: "no-strip",
                  gCpu: "no-g-cpu", gGpu: "no-g-gpu", gRam: "no-g-ram", gDiskC: "no-g-diskC", gDiskE: "no-g-diskE",
                  gPing: "no-g-ping" };
  const off = (k) => !!layout && layout[k] === false;       // a feature switched off in settings
  function applyLayout(L) {
    if (!L) return;
    layout = L;
    // widget pages: features.js builds the boards first (their widgets move into them)
    if (window.__hopBoards) window.__hopBoards(L);
    const boards = L.pageMode === "boards" && document.querySelector(".full .pg-board");
    const hidden = new Set(boards ? [] : L.hidden || []);
    ALL_PAGES = [...document.querySelectorAll(".full .pg")];       // extension pages may have been added
    const ext = ALL_PAGES.filter((p) => p.dataset.ext).map((p) => p.dataset.id);
    const order = (boards ? ALL_PAGES.filter((p) => p.classList.contains("pg-board")).map((p) => p.dataset.id)
                          : [...(L.pages || []), ...ext]).filter((id) => ALL_PAGES.some((p) => p.dataset.id === id));
    document.documentElement.classList.toggle("boards", !!boards);
    const byId = Object.fromEntries(ALL_PAGES.map((p) => [p.dataset.id, p]));
    const dots = document.querySelector(".pg-dots");
    order.forEach((id) => full.insertBefore(byId[id], dots));      // DOM order = page order
    ALL_PAGES.forEach((p) => p.classList.toggle("pg-off", hidden.has(p.dataset.id)));
    PAGES = order.filter((id) => !hidden.has(id)).map((id) => byId[id]);
    if (!PAGES.length) PAGES = [byId.music || ALL_PAGES[0]];
    ALL_PAGES.forEach((p) => { if (!PAGES.includes(p)) p.classList.remove("on", "above"); });
    dots.innerHTML = PAGES.map(() => "<i></i>").join("");
    dots.style.display = PAGES.length > 1 ? "" : "none";
    const cur = PAGES.indexOf(ALL_PAGES.find((p) => p.classList.contains("on")));
    setPage(cur >= 0 ? cur : 0, true);
    ["left-rec", "left-art", "left-none"].forEach((c) => island.classList.remove(c));
    ["right-prayer", "right-bars", "right-clock", "right-none"].forEach((c) => island.classList.remove(c));
    island.classList.add("left-" + (L.musicLeft || "rec"), "right-" + (L.musicRight || "prayer"));
    for (const [k, cls] of Object.entries(FLAGS)) island.classList.toggle(cls, L[k] === false);
    // the style: a notch flush with the top edge, or the floating pill
    const wasNotch = document.documentElement.classList.contains("notch");
    document.documentElement.classList.toggle("notch", L.style === "notch");
    if (wasNotch !== (L.style === "notch") && typeof settlePill === "function") settlePill();
    // the island's size: the host resizes the window by the same factor
    if (!window.__islandPreview) document.documentElement.style.zoom = String(L.scale || 1);
    marquees.forEach((m) => m.run(isOpen && !off("marquee")));
    if (L.accentMode === "custom") island.style.setProperty("--accent", L.accentColor);
    else if (off("artColor")) island.style.setProperty("--accent", "#fff");
    else if (els.miniArt.complete && els.miniArt.naturalWidth) accentFrom(els.miniArt);
    if (typeof tickClock === "function" && clockReady) tickClock();
    if (window.__hopApply) window.__hopApply(L);
  }
  window.__islandLayout = applyLayout;
  $("gear").addEventListener("click", () => api.openSettings());
  $("reload").addEventListener("click", () => api.restartApp());
  island.addEventListener("wheel", (e) => {
    if (!isOpen || e.target.closest(".vol-btn, .vol-row, .tm-big")) return;   // the speaker scrolls the volume, the timer its time
    // a list (agents, calendar, notes...) scrolls itself while it can; at its
    // end, or if it's too short to scroll, the wheel moves to the next page
    const sc = e.target.closest(".scrolls, .rows, .plan, textarea");
    if (sc && sc.scrollHeight > sc.clientHeight + 1) {
      const can = e.deltaY > 0 ? sc.scrollTop + sc.clientHeight < sc.scrollHeight - 1 : sc.scrollTop > 0;
      if (can) return;
    }
    e.preventDefault();
    const how = (layout && layout.wheel) || "pages";
    if (how === "none") return;
    if (how === "volume") {
      vol.level = Math.min(1, Math.max(0, Math.round((vol.level + (e.deltaY < 0 ? 0.05 : -0.05)) * 100) / 100));
      vol.muted = false; paintVol(); sendVol(vol.level, null);
      return;
    }
    if (performance.now() - pageAt < 350 || Math.abs(e.deltaY) < 4) return;
    pageAt = performance.now();
    setPage(page + (e.deltaY > 0 ? 1 : -1));
  }, { passive: false });

  // ---- one synced lyric line (LRCLIB via the host, once per song)
  let lyr = { key: "", lines: [] }, lyrIdx = -2;
  function setLyrics(d) {
    lyr = d || { key: "", lines: [] };
    lyrIdx = -2;
    island.classList.toggle("has-lyrics", !!(lyr.lines && lyr.lines.length && pb && lyr.key === pb.uri));
    paintLyric();
  }
  window.__islandLyrics = setLyrics;
  function paintLyric() {
    if (!isOpen || !lyr.lines.length || !pb || lyr.key !== pb.uri) return;
    const p = progressNow();
    let i = -1;
    for (let k = 0; k < lyr.lines.length && lyr.lines[k][0] <= p + 250; k++) i = k;
    if (i === lyrIdx) return;
    lyrIdx = i;
    const el = $("lyric"), text = i < 0 ? "♪" : (lyr.lines[i][1] || "♪");
    el.classList.add("out");
    setTimeout(() => { el.textContent = text; el.classList.remove("out"); }, 200);
  }

  // ---- page 2: Hijri date, Ramadan / Eid, weather, today's prayers
  let today = null;
  const wxIcon = (c, size) => window.ICON(c === 0 ? "sun" : c <= 3 ? "cloud" : c <= 48 ? "cloud-fog" : c <= 67 ? "cloud-rain" : c <= 77 ? "snowflake" : c <= 82 ? "cloud-rain" : "cloud-storm", size || 20);
  function paintToday() {
    if (!today) return;
    const h = today.hijri, w = today.weather, pr = today.prayers && today.prayers.today;
    if (h) {
      $("hij").textContent = `${h.day} ${h.month} ${h.year}`;
      const until = (e) => e.days ?? Math.round((new Date(e.date + "T00:00:00") - new Date(new Date(nowMs()).toDateString())) / 86400000);
      $("evts").innerHTML = h.events.slice(0, 2).map((e) => { const d = until(e); return `${e.name} in <b>${d} day${d === 1 ? "" : "s"}</b>`; }).join("<br>");
    }
    if (w) {
      $("wxTemp").innerHTML = `<span class="wx-ic">${wxIcon(w.code, 22)}</span>${Math.round(w.temp)}°`;
      $("wxDetail").textContent = `H ${Math.round(w.high)}° · L ${Math.round(w.low)}°`;
    }
    if (pr) {
      const names = ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"], now = new Date(nowMs());
      const mins = now.getHours() * 60 + now.getMinutes();
      const next = names.find((n) => { const [a, b] = pr[n].split(":").map(Number); return a * 60 + b > mins; }) || "Fajr";
      const fmt12 = (hm) => { const [a, b] = hm.split(":").map(Number); return `${(a % 12) || 12}:${String(b).padStart(2, "0")}`; };
      $("strip").innerHTML = names.map((n) => `<div class="${n === next ? "nx" : ""}">${n}<b>${fmt12(pr[n])}</b></div>`).join("");
    }
  }
  window.__islandToday = (d) => { today = d; paintToday(); };

  // ---- page 3: recent clips
  const COPY_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><rect x="8.5" y="8.5" width="11" height="11" rx="2"/><path d="M15.5 8.5V6a1.5 1.5 0 0 0-1.5-1.5H6A1.5 1.5 0 0 0 4.5 6v8A1.5 1.5 0 0 0 6 15.5h2.5"/></svg>`;
  const ago = (t) => {
    const s = Math.max(0, Date.now() / 1000 - t);
    return s < 60 ? "just now" : s < 3600 ? `${Math.floor(s / 60)}m ago` : s < 86400 ? `${Math.floor(s / 3600)}h ago` : `${Math.floor(s / 86400)}d ago`;
  };
  function loadClips() {
    Promise.resolve(api.getClips()).then((list) => {
      const box = $("thumbs");
      if (!list || !list.length) { box.innerHTML = '<div class="none">No clips yet. Press F8 in a game.</div>'; return; }
      box.innerHTML = list.slice(0, 3).map((c, i) => `
        <div class="tcol"><div class="thumb" data-i="${i}">
          ${c.thumb ? `<img src="${esc(c.thumb)}" alt="">` : ""}
          <span class="len">${c.seconds ? clipLen(c.seconds) : c.kind === "recording" ? "REC" : ""}</span>
          <button class="tcopy" title="Copy the file">${COPY_SVG}</button>
        </div><div class="ago">${ago(c.at)}</div></div>`).join("");
      box.querySelectorAll(".thumb").forEach((el) => {
        const c = list[+el.dataset.i];
        // The video exists only while the pointer is on it (a picture otherwise).
        el.addEventListener("mouseenter", () => {
          if (el.querySelector("video")) return;
          const v = document.createElement("video");
          Object.assign(v, { src: c.url, muted: true, autoplay: true, loop: true, playsInline: true });
          v.addEventListener("playing", () => v.classList.add("on"));
          el.insertBefore(v, el.querySelector(".len"));
        });
        el.addEventListener("mouseleave", () => {
          const v = el.querySelector("video");
          if (v) { v.pause(); v.removeAttribute("src"); v.load(); v.remove(); }
        });
        el.addEventListener("click", () => api.openFile(c.path));
        el.querySelector(".tcopy").addEventListener("click", (e) => {
          e.stopPropagation();
          api.copyFile(c.path);
          const btn = e.currentTarget;
          btn.classList.add("ok");
          setTimeout(() => btn.classList.remove("ok"), 2000);
        });
      });
    });
  }
  $("clipsFolder").addEventListener("click", () => api.openClipsFolder());

  // ---- page 4: PC load + ping (only polled while this page is showing)
  let pcTimer = 0, pingTimer = 0, speedBusy = false;
  const gb = (b) => `${(b / 1073741824).toFixed(b >= 107374182400 ? 0 : 1)} GB`;
  function gauge(k, pct, text, label) {
    const g = document.querySelector(`.g[data-k="${k}"]`);
    if (!g) return;
    const ring = g.querySelector(".gring");
    ring.style.setProperty("--p", pct == null ? 0 : Math.round(pct));
    ring.classList.toggle("hot", pct != null && pct >= 90);
    ring.querySelector("span").textContent = text;
    if (label) g.querySelector(".gl").textContent = label;
  }
  function pcTick() {
    Promise.resolve(api.getSys()).then((s) => {
      if (!s) return;
      gauge("cpu", s.cpu, `${Math.round(s.cpu)}%`);
      gauge("gpu", s.gpu, s.gpu == null ? "–" : `${Math.round(s.gpu)}%`);
      if (s.ram) {
        gauge("ram", (100 * s.ram.used) / s.ram.total, `${Math.round((100 * s.ram.used) / s.ram.total)}%`, "RAM");
        const g = document.querySelector('.g[data-k="ram"]'); if (g) g.title = `${gb(s.ram.used)} of ${gb(s.ram.total)} in use`;
      }
      for (const slot of ["C", "E"]) {
        const d = (s.disks || {})[slot], g = document.querySelector(`.g[data-k=disk${slot}]`);
        if (g) g.hidden = !d;                   // one drive only: the second gauge goes
        if (d) {
          gauge(`disk${slot}`, 100 - (100 * d.free) / d.total, `${Math.round(d.free / 1073741824)}G`, `${d.letter || slot}:`);
          g.title = `${gb(d.free)} free of ${gb(d.total)}`;
        }
      }
    });
  }
  function pingTick() {
    if (speedBusy) return;
    Promise.resolve(api.ping()).then((ms) => {
      if (speedBusy) return;
      const b = $("aPing");
      b.querySelector("span").textContent = ms == null ? "–" : `${ms}`;
      b.style.setProperty("--p", ms == null ? 100 : Math.max(6, Math.min(100, Math.round(ms / 2))));   // 200 ms = full
      $("pingLabel").textContent = ms == null ? "Offline" : "Ping";
      b.classList.toggle("slow", ms != null && ms >= 80 && ms < 150);
      b.classList.toggle("bad", ms == null || ms >= 150);
    });
  }
  function pcActive(on) {
    clearInterval(pcTimer); clearInterval(pingTimer);
    if (!on) return;
    pcTick(); pingTick();
    pcTimer = setInterval(pcTick, 2000);
    pingTimer = setInterval(pingTick, 4000);
  }
  $("aPing").addEventListener("click", () => {
    if (speedBusy) return;
    speedBusy = true;
    const b = $("aPing");
    b.classList.remove("slow", "bad");
    b.querySelector("span").textContent = "…";
    $("pingLabel").textContent = "Testing";
    Promise.resolve(api.speedtest()).then((mbps) => {
      b.querySelector("span").textContent = mbps == null ? "–" : `${mbps}`;
      $("pingLabel").textContent = mbps == null ? "Test failed" : "Mbps ↓";
      setTimeout(() => { speedBusy = false; pingTick(); }, 5000);
    });
  });

  // ---- the closed pill's width: a live activity > the prayer countdown > normal.
  // The host's click-through region grows first and shrinks after the animation.
  // closed widths (host.py COMPACT / NOTCH / COMPACT_WIDE): the notch is one width
  const notchOn = () => document.documentElement.classList.contains("notch");
  // the closed width comes from the CSS (settings: pill / notch size, and
  // features.js widens it to fit what the slots show)
  const cssPx = (v, d) => parseFloat(getComputedStyle(document.documentElement).getPropertyValue(v)) || d;
  const PILL_W_NOW = () => cssPx("--w", notchOn() ? 200 : 126), PRAY_W_NOW = () => Math.max(cssPx("--w-wide", 176), PILL_W_NOW());
  let actW = 0, pillShrink = 0;
  const wantedPill = () => actW || (island.classList.contains("pray-show") || shown ? PRAY_W_NOW() : PILL_W_NOW());
  function growPill(w) { clearTimeout(pillShrink); return Promise.resolve(api.setPillWidth(Math.max(w, wantedPill()))); }
  function settlePill() { clearTimeout(pillShrink); pillShrink = setTimeout(() => api.setPillWidth(wantedPill()), 460); }

  // ---- live activities: charging, low battery, a Bluetooth output
  const ICON = {
    bolt: '<svg viewBox="0 0 24 24" fill="#30d158"><path d="M13 2 4.5 13.5H11L10 22l8.5-11.5H12L13 2Z"/></svg>',
    batt: (c, lvl) => `<svg viewBox="0 0 24 24" fill="none" stroke="${c}" stroke-width="2"><rect x="2.5" y="7" width="17" height="10" rx="2.5"/><path d="M22 10.5v3" stroke-linecap="round"/><rect x="5" y="9.5" width="${Math.max(1.5, 12 * lvl)}" height="5" rx="1" fill="${c}" stroke="none"/></svg>`,
    phones: '<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round"><path d="M4 13v-1a8 8 0 0 1 16 0v1"/><rect x="3" y="13" width="4.5" height="7" rx="2"/><rect x="16.5" y="13" width="4.5" height="7" rx="2"/></svg>',
  };
  const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  let actTimer = 0;
  window.__islandActivity = (a) => {
    if (off({ charge: "actCharge", low: "actLow", bt: "actBt" }[a.kind])) return;
    let w, html;
    if (a.kind === "charge") {
      w = 150;
      html = `<div class="side">${ICON.bolt}</div><div class="side"><span style="color:#30d158">${a.pct ?? ""}%</span>${ICON.batt("#30d158", (a.pct || 0) / 100)}</div>`;
    } else if (a.kind === "low") {
      w = 170;
      html = `<div class="side">${ICON.batt("#ff453a", (a.pct || 0) / 100)}</div><div class="side"><span style="color:#ff453a">${a.pct}%</span><span class="dim">Low</span></div>`;
    } else if (a.kind === "bt") {
      w = a.pct != null ? 250 : 220;
      html = `<div class="side">${ICON.phones}<span class="name">${esc(a.name)}</span></div>` +
             (a.pct != null ? `<div class="side"><span class="dim">${a.pct}%</span><div class="ring" style="--p:${a.pct}"></div></div>` : `<div class="side"><span class="dim">Connected</span></div>`);
    } else return;
    clearTimeout(actTimer);
    w = Math.max(w, PILL_W_NOW());
    actW = w;
    growPill(w).then(() => {
      $("actView").innerHTML = html;
      island.style.setProperty("--act-w", w + "px");
      island.classList.add("act");
    });
    actTimer = setTimeout(() => {
      island.classList.add("act-out");
      setTimeout(() => { actW = 0; island.classList.remove("act", "act-out"); settlePill(); }, 130);
    }, a.kind === "low" ? 5000 : 3500);
  };

  // ---- expanded cards: clip saved, drop to upload
  const card = $("card");
  let cardTimer = 0, cardOn = false, cardOff = 0;
  let cardSeq = 0;                                   // bumped by every new card (a swipe-away checks it)
  function showCard(html, w, h, ms, after) {
    cardSeq++;
    clearTimeout(cardTimer); clearTimeout(cardOff);
    if (isOpen) window.__islandHover(false);
    const draw = () => {
      card.innerHTML = html;
      // Fit the card to what is in it (no empty space): measure its natural
      // width, then fix it, so long names still end in "…" at 360.
      fitCard();                                     // its size comes from its content (h is only a fallback)
      island.classList.add("carding");
      if (after) { after(); fitCard(); }             // what after() added counts too
    };
    if (cardOn) draw(); else { cardOn = true; Promise.resolve(api.setBig(true)).then(draw); }
    if (ms) armCard(ms);
  }
  function fitCard(heightOnly) {
    card.style.width = "max-content";
    // up to the open island's width: a long line makes the card wider, not wrapped
    const w = heightOnly ? parseFloat(island.style.getPropertyValue("--card-w")) || 312
      : Math.min(Math.max(360, ((layout && layout.openW) || 360) - 20), 560,
                 Math.max(160, card.offsetWidth + (card.querySelector(".body.one") ? 10 : 3)));   // fonts can measure a hair narrow (a one-line command more)
    card.style.width = w + "px";
    card.style.height = "auto";
    const maxH = ((layout && layout.openH) || 150) + 42;          // the window's room below the open island
    const h = Math.min(maxH, Math.max(56, Math.ceil(card.scrollHeight) + 1));
    card.style.width = card.style.height = "";
    island.style.setProperty("--card-w", w + "px");
    island.style.setProperty("--card-h", h + "px");
  }
  window.__islandFitCard = fitCard;

  function armCard(ms) {
    clearTimeout(cardTimer);
    cardTimer = setTimeout(function hide() {
      if (card.matches(":hover")) { cardTimer = setTimeout(hide, 800); return; }
      hideCard();
    }, ms);
  }
  function hideCard() {
    clearTimeout(cardTimer);
    if (!cardOn) return;
    island.classList.remove("carding");
    const v = card.querySelector("video"); if (v) v.pause();
    cardOff = setTimeout(() => { cardOn = false; card.innerHTML = ""; api.setBig(false); }, 460);
  }
  const clipLen = (s) => { s = Math.max(0, Math.round(s)); return s >= 60 ? `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}` : `${s}s`; };

  window.__islandClip = (c) => {
    if (off("clipCard")) return;
    const label = c.kind === "recording" ? "Recording saved" : "Clip saved";
    showCard(`<video src="${esc(c.url)}" muted autoplay loop playsinline></video>
      <div class="ct"><div class="t">${label}</div><div class="s">${clipLen(c.seconds)} · just now</div>
      <div class="btns"><button class="pbtn" id="cOpen">Open</button><button class="pbtn" id="cCopy">Copy</button></div></div>`,
      312, 100, 7000, () => {
        const v = card.querySelector("video");
        v.addEventListener("loadeddata", () => api.log(`clip video loaded ${v.videoWidth}x${v.videoHeight}`));
        let again = false;
        v.addEventListener("error", () => {
          api.log(`clip video error ${v.error && v.error.code} ${v.error && v.error.message} src=${v.currentSrc} page=${location.href}`);
          if (again) return;                       // clips.island not mapped (yet): map it and try once more
          again = true;
          Promise.resolve(api.remapHosts()).then(() => setTimeout(() => { v.src = c.url + "?r=" + Date.now(); }, 800));
        });
        $("cOpen").onclick = () => { api.openFile(c.path); hideCard(); };
        $("cCopy").onclick = (e) => { api.copyFile(c.path); e.target.classList.add("ok"); e.target.textContent = "Copied ✓"; fitCard(); armCard(2500); };
      });
  };

  // ---- updates: "Update available" stays until a button is pressed; after an
  // update, "Updated to vX" once.
  const UPD = '<svg viewBox="0 0 24 24" fill="none" stroke="#0a84ff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10" stroke-opacity=".4"/><path d="M12 6.8v9M8.2 12.3 12 16.1l3.8-3.8"/></svg>';
  window.__islandUpdate = (u) => {
    showCard(`<div class="upd-mark">${UPD}</div><div class="ct"><div class="t">Update available</div>
      <div class="s">Hop v${esc(u.latest)} is ready</div>
      <div class="btns"><button class="pbtn go" id="uGo">Update now</button><button class="pbtn" id="uLater">Later</button></div></div>`,
      300, 100, 0, () => {
        $("uGo").onclick = () => { api.updateAnswer(true); hideCard(); };
        $("uLater").onclick = () => { api.updateAnswer(false); hideCard(); };
      });
  };
  window.__islandUpdated = (v) => {
    showCard(`<div class="upd-mark ok">${OK_GREEN}</div><div class="ct"><div class="t">Updated to v${esc(v)}</div>
      <div class="s">Hop Island and Hop Clipper</div></div>`, 280, 64, 4500);
  };
  const OK_GREEN = '<svg viewBox="0 0 24 24" fill="none" stroke="#30d158" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="m7.4 12.4 3 3 6.2-6.6"/></svg>';

  // drop a file on the island: it uploads to mutate.lol and the link is copied
  const UP = '<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 16V4m-5 5 5-5 5 5M4 17v2a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-2"/></svg>';
  const OK = '<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg>';
  const NO = '<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round"><path d="M7 7l10 10M17 7 7 17"/></svg>';
  let dragDepth = 0, uploading = false;
  const dropCard = (title, sub, extra = "") => showCard(`<div class="drop">${UP}</div><div class="ct"><div class="t">${esc(title)}</div><div class="s">${esc(sub)}</div>${extra}</div>`, 312, 88, 0);
  const hasFiles = (e) => e.dataTransfer && [...(e.dataTransfer.types || [])].includes("Files");
  document.addEventListener("dragenter", (e) => {
    if (!hasFiles(e) || uploading) return;
    e.preventDefault();
    const how = (layout && layout.dropAction) || "upload";
    if (dragDepth++ === 0) dropCard(how === "shelf" ? "Drop to keep it" : how === "ask" ? "Drop it here" : "Drop to upload",
                                    how === "shelf" ? "On the island's shelf" : how === "ask" ? "Upload it or keep it on the shelf" : "mutate.lol · link gets copied");
  });
  document.addEventListener("dragover", (e) => { if (hasFiles(e)) e.preventDefault(); });
  document.addEventListener("dragleave", () => { if (uploading) return; if (--dragDepth <= 0) { dragDepth = 0; hideCard(); } });
  document.addEventListener("drop", (e) => { e.preventDefault(); dragDepth = 0; uploading = true; dropCard("Uploading…", "", '<div class="prog busy"><i></i></div>'); });
  window.__islandUpload = (u) => {
    if (u.state === "cancel") { uploading = false; hideCard(); return; }   // not uploaded: the shelf, or "what should happen?"
    if (u.state === "uploading") {
      uploading = true;
      const mb = u.size ? `${(u.size / 1048576).toFixed(u.size < 10485760 ? 1 : 0)} MB` : "";
      const bar = u.progress > 0 && u.progress < 1 ? `<div class="prog"><i style="width:${Math.round(u.progress * 100)}%"></i></div>` : '<div class="prog busy"><i></i></div>';
      dropCard(`Uploading ${u.name}`, mb, bar);
    } else if (u.state === "done") {
      uploading = false;
      showCard(`<div class="badge" style="background:#30d158">${OK}</div><div class="ct"><div class="t">Link copied</div><div class="s">${esc(u.link.replace(/^https:\/\//, ""))}</div></div>`, 312, 88, 4000);
    } else {
      uploading = false;
      showCard(`<div class="badge" style="background:#ff453a">${NO}</div><div class="ct"><div class="t">Upload failed</div><div class="s">${esc(u.message || "")}</div></div>`, 312, 88, 5000);
    }
  };

  // ---- volume (Spotify's own, via the host). Hovering the speaker grows the
  // island down over the slider row; leaving the speaker and the row closes it.
  const VOL_H = 42;                               // island.css --vol-h
  const vol = { level: 1, muted: false, open: false, dragging: false };
  const volBtn = $("volBtn"), volRow = $("volRow"), volRail = $("volRail");
  let volCloseTimer = 0, volShrinkTimer = 0, volSend = 0, volPending = null;

  function paintVol() {
    const shown = vol.muted ? 0 : vol.level;
    $("volFill").style.width = `${vol.level * 100}%`;
    $("volKnob").style.left = `${vol.level * 100}%`;
    $("volPct").textContent = Math.round(shown * 100);
    volRail.classList.toggle("muted-level", vol.muted);
    volBtn.classList.toggle("muted", vol.muted || vol.level === 0);
    volBtn.classList.toggle("low", !vol.muted && vol.level > 0 && vol.level < 0.5);
  }

  function readVol() {
    api.getVolume().then((v) => {
      if (!v || vol.dragging) return;
      vol.level = v.level; vol.muted = v.muted;
      paintVol();
    });
  }

  function openVol() {
    clearTimeout(volCloseTimer);
    clearTimeout(volShrinkTimer);
    if (vol.open || !isOpen) return;
    vol.open = true;
    api.setExtra(VOL_H);                          // the host counts the grown part as "on the island"
    island.classList.add("vol");
    readVol();
  }

  function closeVol(now) {
    clearTimeout(volCloseTimer);
    const shut = () => {
      if (!vol.open || vol.dragging) return;
      vol.open = false;
      island.classList.remove("vol");
      clearTimeout(volShrinkTimer);
      volShrinkTimer = setTimeout(() => { if (!vol.open) api.setExtra(0); }, 420);
    };
    if (now === true) { vol.dragging = false; shut(); } else volCloseTimer = setTimeout(shut, 350);
  }

  // send at most one change per frame while dragging
  function sendVol(level, muted) {
    volPending = { level, muted };
    if (volSend) return;
    volSend = requestAnimationFrame(() => {
      volSend = 0;
      const p = volPending;
      volPending = null;
      api.setVolume(p.level, p.muted);
    });
  }

  function setFromX(clientX) {
    const r = volRail.getBoundingClientRect();
    vol.level = Math.round(Math.min(1, Math.max(0, (clientX - r.left) / r.width)) * 100) / 100;
    const unmute = vol.muted;
    vol.muted = false;
    paintVol();
    sendVol(vol.level, unmute ? false : null);
  }

  for (const el of [volBtn, volRow]) {
    el.addEventListener("mouseenter", openVol);
    // on a widget page the row is far below the speaker: leaving the speaker
    // doesn't close it (the mouseover below does, on another widget)
    el.addEventListener("mouseleave", () => { if (!volBtn.closest(".tile")) closeVol(); });
    el.addEventListener("wheel", (e) => {        // scroll = 5 % steps
      e.preventDefault();
      vol.level = Math.min(1, Math.max(0, Math.round((vol.level + (e.deltaY < 0 ? 0.05 : -0.05)) * 100) / 100));
      const unmute = vol.muted;
      vol.muted = false;
      paintVol();
      sendVol(vol.level, unmute ? false : null);
    }, { passive: false });
  }
  // on a widget page the speaker is top right of the player and the row is
  // at the island's bottom: it stays open on the way down, and closes when
  // the mouse moves onto another widget or the tabs
  island.addEventListener("mouseover", (e) => {
    const t = volBtn.closest(".tile");
    if (!vol.open || !t || volRow.contains(e.target)) return;
    const other = e.target.closest(".tile, .topbar");
    if (other && other !== t) closeVol();
  });
  island.addEventListener("mouseleave", () => { if (volBtn.closest(".tile")) closeVol(); });
  volBtn.addEventListener("click", () => {
    vol.muted = !vol.muted;
    paintVol();
    api.setVolume(null, vol.muted);
  });
  volRail.addEventListener("pointerdown", (e) => {
    vol.dragging = true;
    volRail.classList.add("drag");
    volRail.setPointerCapture(e.pointerId);
    setFromX(e.clientX);
  });
  volRail.addEventListener("pointermove", (e) => { if (vol.dragging) setFromX(e.clientX); });
  const endDrag = () => {
    if (!vol.dragging) return;
    vol.dragging = false;
    volRail.classList.remove("drag");
    if (!volRow.matches(":hover") && !(volBtn.closest(".tile") || volBtn).matches(":hover")) closeVol();
  };
  volRail.addEventListener("pointerup", endDrag);
  volRail.addEventListener("pointercancel", endDrag);

  // ---- record (the clipper). The host polls the clipper twice a second and
  // calls __islandRec(available, startedMs); a click flips the button at once
  // and the host confirms.
  const recBtn = $("rec"), recTime = $("recTime");
  let rec = { available: false, started: 0 }, recTick = 0;
  const fmtLen = (ms) => {
    const s = Math.max(0, Math.floor(ms / 1000));
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), ss = String(s % 60).padStart(2, "0");
    return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
  };
  function paintRec() {
    island.classList.toggle("recording", !!rec.started);
    island.classList.toggle("no-clipper", !rec.available);
    recBtn.setAttribute("aria-label", rec.started ? "Stop recording" : "Start recording");
    clearTimeout(recTick);
    if (!rec.started) return;
    const tick = () => {
      const ms = Date.now() - rec.started;
      recTime.textContent = fmtLen(ms);
      recTick = setTimeout(tick, 1000 - (ms % 1000) + 5);   // on each whole second
    };
    tick();
  }
  window.__islandRec = (available, started) => {
    if (available === rec.available && started === rec.started) return;
    rec = { available, started };
    paintRec();
  };
  recBtn.addEventListener("click", () => {
    const on = !rec.started;
    rec.started = on ? Date.now() : 0;
    paintRec();
    api.record(on).then((r) => { if (r) window.__islandRec(r.available, r.started); });
  });

  // ---- prayer times (the city from settings; fetched daily by the host, saved on disk
  // so they still show offline). 15 min before a prayer the pill's clock
  // becomes "Asr · 12m"; at the time the island opens by itself, chimes once
  // and closes again. Sunrise is shown but never alarms.
  const ALARM_ALL = ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"];
  // which prayers alarm comes from the settings (all five by default)
  const ALARMS = { includes: (n) => ALARM_ALL.includes(n) && (!layout || !layout.alarmPrayers || layout.alarmPrayers.includes(n)) };
  const SOON_MS = 15 * 60 * 1000, ALERT_MS = 12000;
  const nowMs = () => Date.now() + (window.__timeShift || 0);   // the browser demo moves time
  const timeFmt = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" });
  let prayers = null, alertTimer = 0, alerting = false, lastSig = "";
  const alerted = new Set();

  function schedule() {
    const out = [];
    for (const key of ["today", "tomorrow"]) {
      const day = prayers && prayers[key];
      if (!day) continue;
      const base = new Date(prayers.date + "T00:00:00");
      if (key === "tomorrow") base.setDate(base.getDate() + 1);
      for (const [name, hm] of Object.entries(day)) {
        const [h, m] = hm.split(":").map(Number);
        const at = new Date(base);
        at.setHours(h, m, 0, 0);
        out.push({ name, at: at.getTime(), id: `${base.toDateString()} ${name}` });
      }
    }
    return out.sort((a, b) => a.at - b.at);
  }

  function prayerTick() {
    const list = schedule(), now = nowMs();
    const next = list.find((p) => p.at > now);
    const nextAlarm = list.find((p) => p.at > now && ALARMS.includes(p.name));
    // the alarm: a prayer that began within the last minute and has not chimed yet
    const due = list.find((p) => ALARMS.includes(p.name) && now >= p.at && now - p.at < 60000 && !alerted.has(p.id));
    if (due) startAlert(due);
    const soon = !!nextAlarm && nextAlarm.at - now <= SOON_MS;
    island.classList.toggle("pray-soon", soon);
    const mins = soon ? Math.max(1, Math.ceil((nextAlarm.at - now) / 60000)) : 0;
    // Flash the countdown for FLASH_MS each time the minute changes; from the
    // last minute on it stays until the alarm.
    if (!soon || alerting || off("prayCountdown")) {
      flashMin = 0;
      showCountdown(false);
    } else if (mins !== flashMin) {
      flashMin = mins;
      showCountdown(true);
      clearTimeout(flashTimer);
      if (mins > 1) flashTimer = setTimeout(() => showCountdown(false), FLASH_MS);
    }
    const sig = `${next && next.id}|${soon}|${mins}`;
    if (sig === lastSig) return;
    lastSig = sig;
    $("prayTime").textContent = soon ? `${nextAlarm.name} · ${mins}m` : "";
    $("npName").textContent = next ? (soon && next === nextAlarm ? `${next.name} in ${mins}m` : `Next · ${next.name}`) : "";
    $("npTime").textContent = next ? timeFmt.format(next.at) : "";
  }

  // The pill widens while it shows the countdown; the host's click-through
  // region has to widen first (and narrow only after the shrink animation),
  // or the wider pill would be clipped.
  let flashMin = 0, flashTimer = 0, shown = false, narrowTimer = 0;
  const FLASH_MS = 5000;
  function showCountdown(on) {
    if (on === shown) return;
    shown = on;
    clearTimeout(narrowTimer);
    if (on) {
      growPill(PRAY_W_NOW()).then(() => { if (shown) island.classList.add("pray-show"); });
    } else {
      clearTimeout(flashTimer);
      island.classList.remove("pray-show");
      settlePill();
    }
  }

  function startAlert(p) {
    alerted.add(p.id);
    if (off("prayerAlarm")) return;
    alerting = true;
    showCountdown(false);
    $("alName").textContent = p.name;
    $("alSub").textContent = `${timeFmt.format(p.at)} · time to pray`;
    island.classList.add("alerting");
    api.holdOpen(true);                          // the host opens the island and keeps it open
    if (!off("prayerChime") && (!layout || layout.alarmSound !== "none")) api.chime((layout && layout.alarmSound) || "chime");
    clearTimeout(alertTimer);
    alertTimer = setTimeout(stopAlert, ALERT_MS);
  }

  function stopAlert() {
    if (!alerting) return;
    alerting = false;
    clearTimeout(alertTimer);
    api.holdOpen(false);                         // closes unless the mouse is on it
    setTimeout(() => { if (!alerting) island.classList.remove("alerting"); }, 450);   // after the shrink
  }
  $("alStop").addEventListener("click", stopAlert);

  // the browser demo jumps through time: every jump starts fresh
  window.__islandPrayerReset = () => {
    alerted.clear();
    flashMin = 0;
    lastSig = "";
    prayerTick();
  };

  window.__islandPrayers = (data) => {
    prayers = data;
    lastSig = "";
    prayerTick();
  };
  setInterval(prayerTick, 1000);

  // ---- controls
  $("center").addEventListener("click", () => (window.__hopSnap ? window.__hopSnap() : api.recenter()));
  $("prev").addEventListener("click", () => api.playback("previous"));
  $("next").addEventListener("click", () => api.playback("next"));
  $("play").addEventListener("click", () => {
    if (!pb) return;
    pb.progressMs = progressNow();
    sampledAt = performance.now();
    pb.isPlaying = !pb.isPlaying;             // flip at once, the host confirms
    island.classList.toggle("playing", pb.isPlaying);
    api.playback(pb.isPlaying ? "play" : "pause");
  });
  els.progress.addEventListener("click", (e) => {
    if (!pb || !pb.durationMs) return;
    const r = els.progress.querySelector(".rail").getBoundingClientRect();
    const f = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
    pb.progressMs = f * pb.durationMs;
    sampledAt = performance.now();
    paintProgress();
    api.seek(Math.round(pb.progressMs));
  });

  // ---- SWIPE UP TO DISMISS (left mouse button held), like the iPhone's
  // Dynamic Island: the black shape follows the pointer, squashing up into
  // the top; let go past a short distance (or flick) and the card or alarm
  // blurs away while the shape springs back into the pill. Not far enough:
  // it springs back. Works on every card (clip saved, update, upload) and
  // on prayer alarms.
  let sw = null;
  const swipeTarget = () => island.classList.contains("alerting") ? "alert"
    : island.classList.contains("carding") ? "card" : null;
  island.addEventListener("contextmenu", (e) => e.preventDefault());
  island.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || !swipeTarget() || (layout && layout.swipeUp === "nothing")) return;
    // armed, not started: a plain click (Open, Copy, Update now, Dismiss)
    // still clicks; the swipe only takes over once the pointer really moves
    sw = { y: e.clientY, t: performance.now(), dy: 0, v: 0, lastT: performance.now(), target: swipeTarget(),
           id: e.pointerId, live: false };
  });
  island.addEventListener("pointermove", (e) => {
    if (!sw || !(e.buttons & 1)) return;
    let dy = e.clientY - sw.y;
    if (!sw.live) {
      if (Math.abs(dy) < 5) return;
      sw.live = true;
      try { island.setPointerCapture(sw.id); } catch {}
      island.classList.add("swiping");
      sw.el = island.querySelector(sw.target === "alert" ? ".alert" : ".card");
    }
    dy = dy < 0 ? dy : dy * 0.2;                          // downward: a stiff rubber band
    const now = performance.now();
    sw.v = (dy - sw.dy) / Math.max(1, now - sw.lastT);    // speed of the LAST move (px/ms), like a phone
    sw.lastT = now;
    sw.dy = dy;
    // SMOOTH: drawn at most once per frame, and only transform + opacity
    // (the GPU moves them; nothing is laid out again). A CSS variable here
    // re-styled the whole island on every mouse event and made it lag.
    if (!sw.frame) sw.frame = requestAnimationFrame(() => {
      if (!sw) return;
      sw.frame = 0;
      const k = Math.max(-1, Math.min(0, sw.dy) / 110);     // 0 .. -1 as it goes up
      island.style.transform = `translate3d(0, ${(sw.dy * 0.32).toFixed(1)}px, 0) scale(${(1 + k * 0.1).toFixed(3)}, ${(1 + k * 0.22).toFixed(3)})`;
      if (sw.el) sw.el.style.opacity = Math.max(0, 1 + k * 1.4).toFixed(3);
    });
  });
  function endSwipe() {
    if (!sw) return;
    if (!sw.live) { sw = null; return; }                    // it was a click
    const fresh = performance.now() - sw.lastT < 90;           // still moving when let go
    const go = sw.dy < -26 || (fresh && sw.v < -0.2 && sw.dy < -8);    // far enough, or a flick
    const target = sw.target, el = sw.el, dy = sw.dy, seq = cardSeq;
    if (sw.frame) cancelAnimationFrame(sw.frame);
    sw = null;
    island.classList.remove("swiping");
    if (!go) {                                                // not far enough: springs back
      island.style.transform = "";
      if (el) el.style.opacity = "";
      return;
    }
    api.swiped();
    // SMOOTH AWAY: the card shrinks to the pill with a GPU scale only (no
    // width/height/radius animation, no blur), its video stops at once, and
    // the real size snaps to the pill in one step when the scale is done.
    const v = el && el.querySelector("video");
    if (v) { try { v.pause(); v.removeAttribute("src"); v.load(); } catch {} }
    const r = island.getBoundingClientRect();
    const root = getComputedStyle(document.documentElement);
    const pw = parseFloat(root.getPropertyValue("--w")) || 126, ph = parseFloat(root.getPropertyValue("--h")) || 37;
    const sx = Math.min(1, pw / Math.max(1, r.width)), sy = Math.min(1, ph / Math.max(1, r.height));
    island.classList.add("swipe-away");
    if (el) { el.style.transition = "opacity 140ms ease"; el.style.opacity = "0"; }
    island.style.transition = "transform 230ms cubic-bezier(.2, .8, .2, 1)";
    void island.offsetWidth;                                  // start from where the finger left it
    island.style.transform = `translate3d(0, ${Math.min(0, dy * 0.32 * 0.4).toFixed(1)}px, 0) scale(${sx.toFixed(3)}, ${sy.toFixed(3)})`;
    setTimeout(() => {
      island.style.transition = "none";                        // the size change below is instant
      // a NEW card that arrived during the shrink stays: only the swiped one goes
      if (target === "alert") stopAlert(); else if (cardSeq === seq) hideCard();
      island.style.transform = "";
      if (el) { el.style.transition = ""; el.style.opacity = ""; }
      void island.offsetWidth;
      island.style.transition = "";
      island.classList.remove("swipe-away");
    }, 230);
  }
  island.addEventListener("pointerup", endSwipe);
  island.addEventListener("pointercancel", endSwipe);
  window.__islandSwipeState = () => ({ swiping: !!sw, target: swipeTarget() });

  // ---- the clock in the compact pill: h:mm like the iPhone status bar
  // (12- or 24-hour as Windows is set, without AM/PM), redrawn on the minute.
  // 12- or 24-hour (or as Windows is set), with or without seconds (settings)
  let clockTimer = 0, clockKey = "", clockFmt = null, clockReady = false;
  function tickClock() {
    clockReady = true;
    clearTimeout(clockTimer);
    const h = (layout && layout.clock24) || "auto", secs = !!(layout && layout.clockSeconds);
    if (clockKey !== h + secs) {
      clockKey = h + secs;
      clockFmt = new Intl.DateTimeFormat(undefined, { hour: h === "24" ? "2-digit" : "numeric", minute: "2-digit",
        ...(secs ? { second: "2-digit" } : {}), ...(h === "auto" ? {} : { hourCycle: h === "24" ? "h23" : "h12" }) });
    }
    const now = new Date(Date.now() + (window.__timeShift || 0));   // the browser demo moves time
    $("clock").textContent = clockFmt.formatToParts(now)
      .filter((p) => p.type !== "dayPeriod").map((p) => p.value).join("").trim();
    $("headClock").textContent = $("clock").textContent;
    const step = secs ? 1000 - now.getMilliseconds() + 20 : 60000 - (now.getSeconds() * 1000 + now.getMilliseconds()) + 50;
    clockTimer = setTimeout(tickClock, step);
  }
  window.__islandClock = tickClock;
  // features.js (the newer pages, pop-ups and looks) builds on these
  window.__hop = {
    api, $, esc, island, showCard, hideCard, armCard, fitCard, growPill, settlePill, setPage,
    off: (k) => off(k), layout: () => layout, isOpen: () => isOpen, pageId: () => pageId(page),
    // is this widget on the page in view? (a widget page holds several)
    widgets: () => !PAGES[page] ? [] : PAGES[page].dataset.widgets ? PAGES[page].dataset.widgets.split(",") : [pageId(page)],
    showing: (id) => !!PAGES[page] && (PAGES[page].dataset.id === id || (PAGES[page].dataset.widgets || "").split(",").includes(id)),
    clipLen, ago, vol, paintVol, sendVol, nowMs, playback: () => pb, today: () => today, prayers: () => prayers,
    applyLayout: () => applyLayout(layout), cardSeq: () => cardSeq, cardOn: () => cardOn,
  };
  tickClock();
  applyLayout(window.__layout || null);

  api.getPrayers().then((d) => d && window.__islandPrayers(d));
  api.getToday().then((d) => d && window.__islandToday(d));
  api.onState(render);
  api.getState().then(render);
})();
