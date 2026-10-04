// The settings app's newer sections (0.1.3): own your island. Built from one
// list (SECTIONS) of rows: switch, seg, range, color, select, time, text,
// and a few editors (lists, priority order, per-pop-up table). Every change
// goes through the settings app's own change(), so Undo, the live preview
// and saving work the same as for the older rows.
(() => {
  const S = window.__settings;
  if (!S) return;
  const $ = (id) => document.getElementById(id);
  const esc = S.esc;
  const panel = $("islandPanel");
  let extra = null;                       // the host's non-layout settings (calendar link, profiles, ...)

  // ---------------------------------------------------------------- row builders
  const lab = (t, d) => `<div class="label"><b>${esc(t)}</b>${d ? `<span>${esc(d)}</span>` : ""}</div>`;
  const R = {
    sw: (k, t, d) => `<div class="item" data-row="${k}">${lab(t, d)}<label class="sw"><input type="checkbox" data-k="${k}"><i></i></label></div>`,
    seg: (k, t, d, opts) => `<div class="item" data-row="${k}">${lab(t, d)}<div class="seg" data-k="${k}">${opts.map(([v, n]) => `<button data-v="${v}">${esc(n)}</button>`).join("")}</div></div>`,
    range: (k, t, d, min, max, step = 1, unit = "px", auto = false) => `<div class="item" data-row="${k}">${lab(t, d)}
      ${auto ? `<label class="hint" style="display:flex;align-items:center;gap:5px"><input type="checkbox" data-auto="${k}"> Auto</label>` : ""}
      <input type="range" data-k="${k}" min="${min}" max="${max}" step="${step}" data-unit="${unit}"><span class="val" data-val="${k}"></span></div>`,
    color: (k, t, d) => `<div class="item" data-row="${k}">${lab(t, d)}<input type="color" class="clr" data-k="${k}"><span class="val" data-val="${k}"></span></div>`,
    select: (k, t, d, opts) => `<div class="item" data-row="${k}">${lab(t, d)}<select class="field" data-k="${k}">${opts.map(([v, n]) => `<option value="${v}">${esc(n)}</option>`).join("")}</select></div>`,
    time2: (a, b, t, d) => `<div class="item" data-row="${a}">${lab(t, d)}<input type="time" class="field tm" data-k="${a}"><span class="hint">to</span><input type="time" class="field tm" data-k="${b}"></div>`,
    html: (h) => h,
  };
  const SLOT_OPTS = [["art", "Album cover"], ["clock", "Time"], ["bars", "Music bars"], ["timer", "Timer"], ["agents", "AI agents"], ["net", "Download speed"],
                     ["battery", "Battery"], ["weather", "Weather"], ["date", "Date"], ["rec", "Clips today"], ["none", "Nothing"]];
  const ACTIONS = [["none", "Nothing"], ["playpause", "Play / pause"], ["settings", "Open settings"], ["record", "Start / stop recording"], ["snap", "Snap to top middle"], ["timer", "Start / pause the timer"]];
  const POP_NAMES = {
    notif: ["Windows notifications", "Discord, mail, Teams…"], agent: ["AI agents", "Approvals, questions, done"], download: ["Downloads", "A file finished downloading"],
    snip: ["Screenshots", "After Win + Shift + S"], calendar: ["Calendar", "An event is about to start"], timer: ["Timer", "Time's up"],
    bt: ["Bluetooth", "Earbuds connect, with their battery"], wifi: ["Wi-Fi", "Connected / disconnected"],
    privacy: ["Microphone / camera", "An app starts using them (then just the dot)"],
    focus: ["Focus", "Windows focus starts or ends"], sports: ["Goals", "Your teams score"], rain: ["Rain", "Rain about to start"],
    reminder: ["Reminders", "Yours, and Jumu'ah"], clip: ["Clip saved", "After F8"], update: ["Updates", "A new Hop"], upload: ["Uploads", "Link copied"],
    game: ["After a game", "How many pop-ups waited"],
  };
  const SOUNDS = [["none", "No sound"], ["tick", "Tick"], ["pop", "Pop"], ["chime", "Chime"], ["bell", "Bell"]];
  const LIVE_NAMES = { rec: "Recording", prayer: "Prayer countdown, iftar / suhoor", timer: "Timer", agent: "An agent needs you", focus: "Focus" };
  const LEAGUES = [["epl", "Premier League"], ["laliga", "La Liga"], ["ucl", "Champions League"], ["mls", "MLS"], ["nba", "NBA"], ["nfl", "NFL"], ["nhl", "NHL"], ["mlb", "MLB"]];

  // where each new section goes: [id, title, after-section-id, rows]
  const SECTIONS = [
    // for the whole island, not one page: first in the list
    ["s-general", "General", "TOP", [
      R.seg("pageMode", "Island design", "New: widgets side by side on a few pages. Classic: the 0.1.2 island, one thing per page.",
            [["boards", "New"], ["pages", "Classic"]]),
      R.seg("wheel", "Scroll on the open island", "Lists scroll first; at their end the page changes", [["pages", "Changes page"], ["volume", "Changes volume"], ["none", "Nothing"]]),
    ]],
    ["s-boards", "Pages & widgets", "s-style", [
      R.html(`<div id="boardsEd"></div>`),
    ]],
    ["s-shape", "Shape & size", "s-boards", [
      R.range("pillW", "Pill width", "Closed, pill style", 96, 280),
      R.range("pillH", "Pill height", "", 26, 52),
      R.range("notchW", "Notch width", "Closed, notch style", 140, 340),
      R.range("notchH", "Notch height", "", 22, 48),
      R.range("openW", "Open width", "When it opens", 320, 760),
      R.range("openH", "Open height", "", 140, 340),
      R.range("radiusClosed", "Corners, closed", "", 0, 26, 1, "px", true),
      R.range("radiusOpen", "Corners, open", "", 0, 56, 1, "px", true),
      R.range("topGap", "Gap from the top", "Notch: 0, pill: 10", 0, 80, 1, "px", true),
    ]],
    ["s-colour", "Colours & font", "s-shape", [
      R.color("bg", "Background", "The island's colour"),
      R.range("bgOpacity", "Opacity", "Below 100 lets the desktop show through", 35, 100, 1, "%"),
      R.seg("bgStyle", "Fill", "", [["solid", "Solid"], ["gradient", "Gradient"], ["tint", "Album tint"]]),
      R.sw("border", "Outline", "A thin line around the island"),
      R.color("borderColor", "Outline colour", ""),
      R.range("borderOpacity", "Outline strength", "", 0, 100, 1, "%"),
      R.sw("glow", "Glow", "A soft glow in the accent colour"),
      R.seg("accentMode", "Accent", "Music bars, lyric line, glow", [["album", "From the album"], ["custom", "My colour"]]),
      R.color("accentColor", "My accent colour", ""),
      R.select("font", "Font", "", [["inter", "Inter (like iPhone)"], ["segoe", "Segoe UI (Windows)"], ["outfit", "Outfit (Hop)"], ["mono", "Cascadia Mono"], ["system", "System"]]),
      R.seg("clock24", "Clock", "", [["auto", "Like Windows"], ["12", "12-hour"], ["24", "24-hour"]]),
      R.sw("clockSeconds", "Show seconds", "On the pill's clock"),
    ]],
    ["s-motion", "Motion", "s-colour", [
      R.seg("anim", "Animations", "Reduced: quick fades, nothing moves", [["full", "Full"], ["subtle", "Subtle"], ["reduced", "Reduced"]]),
      R.range("bounce", "Bounce", "How springy opening is (Full only)", 0, 100, 1, "%"),
      R.range("speed", "Speed", "100% is normal", 50, 200, 5, "%"),
    ]],
    ["s-gestures", "Opening & gestures", "s-motion", [
      R.seg("openOn", "Opens", "", [["hover", "When the mouse rests on it"], ["click", "On a click"]]),
      R.range("hoverDelay", "Rest before opening", "Stops it popping open as you sweep past", 0, 1500, 50, "ms"),
      R.range("closeDelay", "Stay open after leaving", "", 0, 2000, 50, "ms"),
      R.seg("swipeUp", "Swipe a card up", "", [["dismiss", "Dismisses it"], ["nothing", "Does nothing"]]),
      R.select("dblClick", "Double-click", "", ACTIONS),
      R.select("middleClick", "Middle-click", "", [["none", "Nothing"], ["playpause", "Play / pause"], ["mute", "Mute the music"], ["next", "Next song"]]),
      R.sw("hotkey", "Shortcut to peek", "Opens the island from anywhere; press again to close"),
      R.select("hotkeyKey", "Shortcut", "", [["ctrl+alt+space", "Ctrl + Alt + Space"], ["ctrl+shift+space", "Ctrl + Shift + Space"], ["alt+`", "Alt + `"], ["win+alt+h", "Win + Alt + H"]]),
    ]],
    ["s-slots", "Closed pill: what goes where", "s-pill", [
      R.select("slotLeft", "Left", "", SLOT_OPTS),
      R.select("slotCenter", "Middle", "", SLOT_OPTS),
      R.select("slotRight", "Right", "", SLOT_OPTS),
      R.html(`<div class="item" data-row="priority"><div class="label"><b>What may take over the middle</b><span>Top wins when several happen at once. Drag to reorder.</span></div></div><div id="prio"></div>`),
      R.sw("micCamDot", "Privacy dot", "Orange: an app uses the microphone. Green: the camera."),
      R.sw("clipDot", "Clip buffer dot", "A red dot while Hop Clipper is recording the last moments"),
      R.sw("idleHide", "Tuck away when idle", "Nothing playing or happening for a while"),
      R.range("idleAfter", "After", "", 5, 300, 5, "s"),
      R.seg("idleStyle", "Tucked away as", "", [["line", "A thin line"], ["fade", "Faded"]]),
    ]],
    ["s-popsettings", "Each pop-up", "s-popups", [
      R.html(`<div id="popTable"></div>`),
      R.sw("quiet", "Quiet hours", "No pop-ups or sounds (timers and agents still come through)"),
      R.time2("quietFrom", "quietTo", "From", ""),
      R.sw("quietInFocus", "Quiet during Windows focus", ""),
      R.sw("gameMode", "Game mode", "In full-screen games pop-ups wait until you leave; nothing animates"),
    ]],
    ["s-agents", "AI agents", "s-popsettings", [
      R.html(`<div class="item"><div class="label"><b>Claude Code</b><span id="agState">Checking…</span></div><button class="btn primary" id="agConnect">Connect</button></div>`),
      R.sw("agentsOn", "Agent cards", "Status on the AI agents page and pop-ups when one needs you"),
      R.sw("agentApprove", "Approve from the island", "Allow / Deny permission requests without switching windows"),
      R.sw("agentSound", "Sound when one needs you", ""),
      R.sw("agentSuppress", "Not while I'm looking at it", "No pop-up if its terminal is already in front"),
      R.sw("usagePill", "Plan usage", "Your 5-hour and weekly Claude limits on the agents page (reads Claude Code's own sign-in)"),
    ]],
    ["s-calendar", "Calendar", "s-agents", [
      R.html(`<div class="item"><input class="field" id="calUrl" placeholder="Your calendar's iCal link (https://…/basic.ics)" spellcheck="false"><button class="btn" id="calSave">Save</button></div>
        <div class="item"><div class="label"><span>Google Calendar: Settings → your calendar → “Secret address in iCal format”. Outlook: Settings → Shared calendars → Publish → ICS.</span></div></div>`),
    ]],
    ["s-clipsisland", "Clips on the island", "s-calendar", [
      R.sw("clipTrim", "Trim button", "On the clip-saved card"),
      R.sw("clipUpload", "Upload button", "Uploads to mutate.lol and copies the link"),
      R.seg("dropAction", "A file dropped on the island", "", [["ask", "Ask"], ["upload", "Upload it"], ["shelf", "Keep it on the shelf"]]),
    ]],
    ["s-sports", "Sports", "s-clipsisland", [R.html(`<div id="teams"></div>`)]],
    ["s-prompter", "Teleprompter", "s-sports", [
      R.html(`<div class="item" style="display:block"><textarea class="field" id="prompterText" rows="5" style="width:100%;resize:vertical" placeholder="Your script…"></textarea></div>`),
      R.range("prompterSpeed", "Scroll speed", "", 10, 160, 5, " px/s"),
    ]],
    ["s-todaymore", "Today: more", "s-today", [
      R.sw("rainAlert", "Rain alert", "A pop-up when rain is about to start where you are"),
      R.sw("wifiPop", "Wi-Fi", "Shows on the pill when it connects or drops"),
      R.html(`<div id="countdowns"></div><div id="reminders"></div>`),
    ]],
    ["s-prayermore", "Prayer: more", "s-prayer", [
      R.html(`<div class="item" data-row="alarmPrayers"><div class="label"><b>Alarm for</b></div><div class="chips" id="alarmPrayers"></div></div>`),
      R.html(`<div class="item" data-row="alarmSound"><div class="label"><b>Alarm sound</b></div><div class="seg" data-k="alarmSound"><button data-v="chime">Chime</button><button data-v="bell">Bell</button><button data-v="soft">Soft</button><button data-v="none">None</button></div><button class="btn" id="soundTest">▶</button></div>`),
      R.sw("jumuah", "Jumu'ah reminder", "Fridays, before Dhuhr"),
      R.range("jumuahMins", "How long before", "", 10, 120, 5, " min"),
      R.sw("ramadan", "Ramadan on the pill", "Iftar countdown during the day, suhoor before Fajr"),
    ]],
    ["s-playermore", "Player: more", "s-player", [R.sw("shuffleRepeat", "Shuffle and repeat buttons", "Beside play / skip, when the app supports them")]],
    ["s-where", "Where it shows", "s-size", [
      R.seg("monitor", "Screen", "", [["primary", "Main screen"], ["cursor", "Follows the mouse"], ["fixed", "This one:"]]),
      R.html(`<div class="item" data-row="monitorIndex"><div class="label"><b>Which screen</b></div><select class="field" data-k="monitorIndex" id="monSel"></select></div>`),
      R.html(`<div id="hideApps"></div>`),
      R.seg("power", "Battery use", "Smart and Low refresh less while the island is closed", [["normal", "Normal"], ["smart", "Smart"], ["low", "Low"]]),
    ]],
    ["s-extensions", "Extensions", "s-where", [
      R.html(`<div id="extList"></div><div class="item"><div class="label"><span>An extension is a folder with a manifest.json and a page, in %APPDATA%\\Hop\\extensions. It gets its own page on the island.</span></div><button class="btn" id="extFolder">Open folder</button></div>`),
    ]],
    ["s-profiles", "Profiles & themes", "s-extensions", [
      R.html(`<div class="item"><div class="label"><b>Profiles</b><span>Save everything as it is now, and switch back any time</span></div></div>
        <div class="item"><select class="field" id="profSel"></select><button class="btn" id="profLoad">Switch</button><button class="btn" id="profDel">Delete</button></div>
        <div class="item"><input class="field" id="profName" placeholder="New profile name (e.g. Gaming)"><button class="btn primary" id="profSave">Save current</button></div>
        <div id="profRules"></div>
        <div class="item"><div class="label"><b>Theme code</b><span>Your look (shape, colours, motion, slots) as text to share</span></div><button class="btn" id="themeCopy">Copy</button></div>
        <div class="item"><input class="field" id="themeIn" placeholder="Paste a theme code"><button class="btn" id="themeApply">Apply</button></div>`),
      R.html(`<div class="item" style="display:block"><div class="label" style="margin-bottom:6px"><b>Custom CSS</b><span>For everything else: it is added to the island's page</span></div>
        <textarea class="field" id="customCss" rows="4" style="width:100%;font-family:Consolas,monospace;font-size:12px;resize:vertical" placeholder=".island { box-shadow: 0 0 0 2px hotpink; }"></textarea>
        <div style="margin-top:6px;display:flex;gap:8px"><button class="btn" id="cssSave">Apply CSS</button>
          <button class="btn" id="cssCopy" title="Your whole look as CSS, for someone else to paste here">Copy as CSS</button></div></div>`),
    ]],
    ["s-lastfm", "Last.fm", "s-profiles", [
      R.sw("scrobble", "Scrobble what plays", "Every song you listen to past half way goes to your Last.fm"),
      R.html(`<div class="item"><input class="field" id="lfUser" placeholder="Username"><input class="field" id="lfPass" type="password" placeholder="Password"></div>
        <div class="item"><input class="field" id="lfKey" placeholder="API key"><input class="field" id="lfSecret" type="password" placeholder="Shared secret"><button class="btn" id="lfGo">Connect</button></div>
        <div class="item"><div class="label"><span id="lfState">Make a free API account at last.fm/api/account/create</span></div></div>`),
    ]],
    ["s-backup", "Startup, backup & help", "s-reset", [
      R.html(`<div class="item"><div class="label"><b>Start with Windows</b><span>Hop Island opens when you sign in</span></div>
          <label class="sw"><input type="checkbox" id="startup"><i></i></label></div>
        <div class="item"><div class="label"><b>Back up settings</b><span>Everything, to a file on your Desktop</span></div><button class="btn" id="bkExport">Export</button><button class="btn" id="bkImport">Import…</button></div>
        <div class="item"><div class="label"><b>Diagnostics</b><span>Hop's logs in one zip on your Desktop, for a bug report</span></div><button class="btn" id="diag">Make zip</button></div>`),
    ]],
  ];

  // ---------------------------------------------------------------- build
  for (const [id, title, after, rows] of SECTIONS) {
    const sec = document.createElement("section");
    sec.id = id;
    const cards = [];
    let cur = [];
    for (const r of rows) { if (r.startsWith('<div id=') || r.startsWith('<div class="item" style="display:block"')) { if (cur.length) cards.push(cur); cards.push([r]); cur = []; } else cur.push(r); }
    if (cur.length) cards.push(cur);
    sec.innerHTML = `<h2>${esc(title)}</h2>` + cards.map((c, i) => `<div class="card"${i ? ' style="margin-top:10px"' : ""}>${c.join("")}</div>`).join("");
    const ref = $(after);
    if (after === "TOP") panel.prepend(sec);
    else ref ? ref.after(sec) : panel.appendChild(sec);
  }
  // SHORTER: the newer rows join the sections they belong to (no "Player: more")
  for (const [from, into, first] of [["s-playermore", "s-player"], ["s-todaymore", "s-today"], ["s-prayermore", "s-prayer"],
                                     ["s-slots", "s-pill"], ["s-popsettings", "s-popups"], ["s-style", "s-shape", true]]) {
    const a = $(from), b = $(into);
    if (!a || !b) continue;
    const cards = [...a.querySelectorAll(":scope > .card")];
    cards.forEach((c, k) => { c.style.marginTop = "10px"; if (first) b.querySelector("h2").after(...(k ? [] : cards)); else b.appendChild(c); });
    if (first) { cards.forEach((c, k) => (c.style.marginTop = k ? "10px" : "")); const nx = cards[cards.length - 1].nextElementSibling; if (nx && nx.classList.contains("card")) nx.style.marginTop = "10px"; }
    a.remove();
  }
  { const sh = $("s-shape"); if (sh) sh.querySelector("h2").textContent = "Style, shape & size"; }
  // "Album colours" is the same thing as Accent: From the album / My colour
  { const x = panel.querySelector('input[data-key="artColor"]'); if (x) x.closest(".item").remove(); }
  // the per-pop-up table starts folded: the common ones, then "Show all"
  { const pt = $("popTable");
    if (pt) {
      const more = document.createElement("div");
      more.className = "item";
      more.innerHTML = '<button class="btn" id="popAll">Show every pop-up</button><span class="hint">Time, sound and on / off for each kind</span>';
      pt.after(more);
      pt.classList.add("folded");
      more.querySelector("button").onclick = () => { const f = pt.classList.toggle("folded"); more.querySelector("button").textContent = f ? "Show every pop-up" : "Show fewer"; };
    } }

  // the table of contents and the search follow the new sections
  const toc = $("toc");
  // the live preview: the island's real window, ZOOMED to whatever the island
  // shows right now (open, a small card, the closed pill), centred in the stage
  let isl = null;
  function fitPreview(L) {
    const f = $("pv"), stage = f && f.parentElement;
    if (!stage || !L) return;
    const glow = L.glow ? 24 : 0;
    const w = Math.max(L.openW, L.style === "notch" ? L.notchW : L.pillW) + glow, h = L.openH + 46 + glow / 2;
    const iw = isl ? isl.w : w, ih = isl ? isl.h : h, top = isl ? isl.top : 0;
    const k = Math.min(2.2, (stage.clientWidth - 40) / iw, (stage.clientHeight - 40) / ih);
    const y = (stage.clientHeight - ih * k) / 2 - top * k - 14;     // the frame sits 14 px down in the stage
    Object.assign(f.style, { width: w + "px", height: h + "px", transformOrigin: "50% 0",
      transform: `translateX(-50%) translateY(${y.toFixed(1)}px) scale(${k.toFixed(3)})` });
  }
  // it never moves while the mouse is on it (hovering the volume button grows
  // the island; re-zooming then slid the button out from under the pointer)
  let held = false;
  window.addEventListener("message", (e) => {
    if (!(e.data && e.data.t === "isl" && e.source === $("pv").contentWindow)) return;
    isl = e.data;
    if ($("pv").parentElement.matches(":hover")) { held = true; return; }
    fitPreview(S.L);
  });
  $("pv").parentElement.addEventListener("pointerleave", () => { if (held) { held = false; fitPreview(S.L); } });
  window.addEventListener("resize", () => S.L && fitPreview(S.L));
  function buildToc() {
    toc.innerHTML = [...panel.querySelectorAll("section")].filter((s) => !s.hidden).map((s) => `<a href="#${s.id}">${esc(s.querySelector("h2").textContent)}</a>`).join("");
  }
  buildToc();
  const SP = S.SECTION_PAGE;
  // hovering one of these newer sections shows its page in the preview: the
  // widget page that holds it (none: the preview stays where it is)
  for (const [id] of SECTIONS) {
    const sec = $(id), w = SP[id];
    if (!sec || !w) continue;
    sec.addEventListener("pointerenter", () => {
      const L = S.L; if (!L) return;
      const i = L.pageMode === "boards" ? (L.boards || []).findIndex((b) => b.widgets.some((x) => x.w === w))
        : L.pages.filter((p) => !L.hidden.includes(p)).indexOf(w);
      const chip = document.querySelectorAll("#chips .chip")[i];
      if (i >= 0 && chip && !chip.classList.contains("on")) chip.click();
    });
  }
  // ---- search: forgiving. Exact words, typos ("notifcations"), and what people
  // mean ("dnd" -> quiet hours, "colour" -> background). With no real match it
  // still shows the closest settings instead of an empty page.
  const SYN = {
    color: "colour background accent fill", colour: "color background accent fill", dark: "background theme colour", light: "theme background",
    size: "width height scale size", big: "size scale width height", small: "size scale width", wide: "width", tall: "height",
    round: "corners radius", corner: "corners radius", radius: "corners", shape: "notch pill style corners",
    sound: "chime sound bell volume", loud: "volume sound", mute: "volume sound", volume: "volume sound",
    quiet: "quiet hours focus", dnd: "quiet hours focus", silent: "quiet hours", sleep: "quiet hours",
    notification: "notifications pop-up pop-ups", notif: "notifications pop-up", popup: "pop-up pop-ups", alert: "pop-up notifications",
    music: "player song spotify", song: "player music", spotify: "player music shuffle repeat", lyrics: "lyric line",
    clip: "clipper clips trim", record: "clipper recording record", mic: "microphone privacy", camera: "privacy camera",
    ai: "agents claude", claude: "agents claude code", chatgpt: "agents codex", codex: "agents", agent: "agents",
    monitor: "screen", display: "screen", screen: "screen monitor", hide: "hide in these apps idle", hotkey: "shortcut", keyboard: "shortcut",
    font: "font text clock", text: "font", clock: "clock 24-hour seconds", time: "clock 24-hour", speed: "motion speed animations",
    animation: "motion animations bounce", anim: "motion animations", bounce: "bounce motion", smooth: "motion animations",
    game: "game mode", gaming: "game mode", weather: "weather rain", rain: "rain alert", prayer: "prayer alarm jumu'ah",
    adhan: "prayer alarm sound", azan: "prayer alarm sound", salah: "prayer", islam: "prayer ramadan", update: "updates",
    backup: "back up export import", export: "export back up", theme: "theme code css colours", css: "custom css",
    pomodoro: "timer focus", stopwatch: "timer", battery: "battery power", power: "battery use", wifi: "wi-fi", bluetooth: "bluetooth earbuds",
    earbuds: "bluetooth", headphones: "bluetooth", move: "position", drag: "position", position: "position across the screen",
    top: "gap from the top", notch: "style shape notch", pill: "style shape pill", widget: "pages widgets", page: "pages widgets",
    calendar: "calendar ical", meeting: "calendar join", sport: "sports scores teams", football: "sports scores teams", soccer: "sports scores",
    lastfm: "last.fm scrobble", scrobble: "last.fm", lyrics: "lyric", lyric: "lyric",
    transparent: "opacity", transparency: "opacity", "see-through": "opacity", border: "outline", outline: "outline",
    shadow: "glow", blur: "glow opacity", smaller: "size scale width", bigger: "size scale width", larger: "size scale width",
    tiny: "size scale", huge: "size scale", startup: "start with windows", autostart: "start with windows", boot: "start with windows", login: "start with windows", gaming: "game mode", games: "game mode", fullscreen: "game mode", extension: "extensions", plugin: "extensions", profile: "profiles", preview: "live preview",
    open: "opens hover click", hover: "opens hover rest", click: "opens click", scroll: "mouse wheel", wheel: "mouse wheel",
  };
  const STOP = new Set(["a", "an", "the", "is", "are", "to", "of", "in", "on", "off", "for", "it", "my", "me", "i", "and", "or", "how", "do",
    "where", "what", "when", "can", "turn", "make", "set", "change", "while", "with", "this", "that", "be", "get", "show", "want"]);
  const words = (t) => t.toLowerCase().normalize("NFKD").replace(/[^a-z0-9.'+ -]/g, " ").split(/\s+/).filter((w) => w.length > 1);
  function lev(a, b) {                              // edit distance, small words only
    if (Math.abs(a.length - b.length) > 3) return 9;
    const d = Array.from({ length: a.length + 1 }, (_, i) => [i]);
    for (let j = 1; j <= b.length; j++) d[0][j] = j;
    for (let i = 1; i <= a.length; i++) for (let j = 1; j <= b.length; j++)
      d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    return d[a.length][b.length];
  }
  // exact > starts with > contains > a typo (5+ letters: 1 wrong, 8+: 2)
  const wordScore = (q, w, typos = true) => w === q ? 1 : w.startsWith(q) ? 0.92 : q.length >= 4 && w.includes(q) ? 0.8
    : typos && q.length >= 5 && lev(q, w) <= (q.length >= 8 ? 2 : 1) ? 0.72 : 0;
  function score(query, text) {
    const T = words(text);
    if (!T.length) return 0;
    let Q = words(query);
    const content = Q.filter((q) => !STOP.has(q));
    if (content.length) Q = content;                // "where is the clock" is about the clock
    if (!Q.length) return 0;
    let total = 0, top = 0;
    for (const q of Q) {
      let best = Math.max(0, ...T.map((w) => wordScore(q, w)));
      const syn = SYN[q] || SYN[q.replace(/s$/, "")];
      // related words count, but only as written (no typo-matching on them: "fill" must not find "pill")
      if (syn) best = Math.max(best, 0.85 * Math.max(0, ...words(syn).filter((sq) => !STOP.has(sq) && sq.length > 2)
        .map((sq) => Math.max(0, ...T.map((w) => wordScore(sq, w, false))))));
      total += best;
      top = Math.max(top, best);
    }
    return 0.6 * top + 0.4 * (total / Q.length);   // the best-matching word counts most
  }
  function searchFor(q) {
    q = q.trim();
    const secs = [...panel.querySelectorAll("section")];
    $("searchNote").hidden = true;
    $("searchNote").innerHTML = "";
    if (!q) {
      secs.forEach((sec) => { sec.classList.remove("no-match"); sec.querySelectorAll(".item").forEach((i) => i.classList.remove("no-match", "near")); });
      return;
    }
    const hits = [];
    for (const sec of secs) {
      if (sec.hidden) continue;
      const title = sec.querySelector("h2").textContent;
      for (const it of sec.querySelectorAll(".card > .item, .card > div > .item")) {
        // its title counts most, then its description and choices, then the section's name
        // (as separate words: textContent glues "notificationsDiscord")
        const name = [...it.querySelectorAll(".label b")].map((e) => e.textContent).join(" ");
        const rest = [...it.querySelectorAll(".label span, .seg button")].map((e) => e.textContent).join(" ") || (name ? "" : it.textContent);
        const sc = Math.max(score(q, name), 0.85 * score(q, rest), 0.8 * score(q, title));
        hits.push([sc, it, sec]);
      }
    }
    let show = hits.filter((h) => h[0] >= 0.6);
    const near = !show.length;
    if (near) {                                     // nothing really matches: the closest few, marked as such
      show = hits.filter((h) => h[0] > 0.15).sort((a, b) => b[0] - a[0]).slice(0, 6);

    }
    const on = new Set(show.map((h) => h[1]));
    for (const sec of secs) {
      let any = false;
      sec.querySelectorAll(".item").forEach((it) => {
        const hit = on.has(it) || (it.closest(".card") && [...on].some((o) => o.closest(".card") === it.closest(".card") && it.closest("#popTable, #prio, #boardsEd") && o.closest("#popTable, #prio, #boardsEd")));
        it.classList.toggle("no-match", !on.has(it));
        it.classList.toggle("near", near && on.has(it));
        any = any || on.has(it);
      });
      sec.classList.toggle("no-match", !any);
    }
    // the best few, as buttons on top (the page itself stays in its order)
    const best = show.sort((a, b) => b[0] - a[0]).slice(0, 3);
    const note = $("searchNote");
    const nm = (it) => ((it.querySelector(".label b") || it).textContent || "").trim().slice(0, 40);
    note.hidden = !best.length && !near;
    note.innerHTML = (near ? `<span>No setting called “${esc(q)}”. Closest:</span>` : "<span>Best matches:</span>") +
      best.map(([, it], k) => `<button class="chip ${k ? "" : "on"}" data-k="${k}">${esc(nm(it))}</button>`).join("");
    if (near && !best.length) note.innerHTML = `<span>Nothing like “${esc(q)}” in the settings.</span>`;
    note.querySelectorAll("[data-k]").forEach((btn) => btn.onclick = () => {
      const it = best[+btn.dataset.k][1];
      it.scrollIntoView({ block: "center", behavior: "smooth" });
      it.classList.remove("flash"); void it.offsetWidth; it.classList.add("flash");
    });
    if (best[0]) best[0][1].scrollIntoView({ block: "center" });
  }
  let searchT = 0;
  $("search").addEventListener("input", () => { clearTimeout(searchT); searchT = setTimeout(() => searchFor($("search").value), 120); });
  $("search").addEventListener("keydown", (e) => { if (e.key === "Escape") { $("search").value = ""; searchFor(""); } });
  { const note = document.createElement("p"); note.id = "searchNote"; note.className = "hint search-note"; note.hidden = true; panel.prepend(note); }
  window.__settingsSearch = searchFor;

  // ---------------------------------------------------------------- generic controls
  const unit = (el, v) => {
    const u = el.dataset.unit || "px";
    return u === "%" || u === "ms" || u === "s" ? `${v}${u === "%" ? "%" : " " + u}` : `${v}${u}`;
  };
  panel.addEventListener("change", (e) => {
    const t = e.target;
    if (t.dataset.k && t.type === "checkbox") S.change({ [t.dataset.k]: t.checked });
    else if (t.dataset.k && t.type === "range") S.change({ [t.dataset.k]: +t.value });
    else if (t.dataset.k && t.type === "color") S.change({ [t.dataset.k]: t.value });
    else if (t.dataset.k && t.tagName === "SELECT") S.change({ [t.dataset.k]: isNaN(+t.value) || t.dataset.k.startsWith("slot") || t.dataset.k === "font" ? t.value : +t.value });
    else if (t.dataset.k && t.type === "time") S.change({ [t.dataset.k]: t.value });
    else if (t.dataset.auto) {
      const k = t.dataset.auto, range = panel.querySelector(`input[type=range][data-k="${k}"]`);
      S.change({ [k]: t.checked ? -1 : +range.value < 0 ? 0 : +range.value });
    }
  });
  panel.addEventListener("input", (e) => {
    const t = e.target;
    if (t.dataset.k && t.type === "range") { const v = panel.querySelector(`[data-val="${t.dataset.k}"]`); if (v) v.textContent = unit(t, t.value); }
  });
  panel.addEventListener("click", (e) => {
    const b = e.target.closest(".seg[data-k] button");
    if (!b) return;
    const k = b.parentElement.dataset.k;
    if (S.L[k] === b.dataset.v) return;
    // the design brings its own open size: Classic is 0.1.2's island
    if (k === "pageMode") S.change({ pageMode: b.dataset.v, ...(b.dataset.v === "pages" ? { openW: 360, openH: 150 } : { openW: 640, openH: 236 }) });
    else S.change({ [k]: b.dataset.v });
  });

  function renderControls(L) {
    panel.querySelectorAll("input[type=checkbox][data-k]").forEach((c) => { c.checked = !!L[c.dataset.k]; });
    panel.querySelectorAll("input[type=range][data-k]").forEach((r) => {
      const v = L[r.dataset.k]; const auto = panel.querySelector(`[data-auto="${r.dataset.k}"]`);
      if (auto) { auto.checked = v < 0; r.disabled = v < 0; }
      r.value = v < 0 ? r.min : v;
      const out = panel.querySelector(`[data-val="${r.dataset.k}"]`); if (out) out.textContent = v < 0 ? "Auto" : unit(r, v);
    });
    panel.querySelectorAll("input[type=color][data-k]").forEach((c) => { c.value = L[c.dataset.k]; const o = panel.querySelector(`[data-val="${c.dataset.k}"]`); if (o) o.textContent = L[c.dataset.k]; });
    panel.querySelectorAll("select[data-k]").forEach((s) => { s.value = String(L[s.dataset.k]); });
    panel.querySelectorAll("input[type=time][data-k]").forEach((t) => { t.value = L[t.dataset.k]; });
    panel.querySelectorAll(".seg[data-k]").forEach((seg) => [...seg.children].forEach((b) => b.classList.toggle("on", b.dataset.v === String(L[seg.dataset.k]))));
    // rows that only matter when another is on
    const dim = (k, on) => { const r = panel.querySelector(`[data-row="${k}"]`); if (r) r.style.opacity = on ? "" : 0.45; };
    dim("borderColor", L.border); dim("borderOpacity", L.border); dim("accentColor", L.accentMode === "custom");
    dim("bounce", L.anim === "full"); dim("hoverDelay", L.openOn === "hover"); dim("hotkeyKey", L.hotkey);
    dim("idleAfter", L.idleHide); dim("idleStyle", L.idleHide); dim("quietFrom", L.quiet); dim("jumuahMins", L.jumuah);
    dim("monitorIndex", L.monitor === "fixed");
    if (document.activeElement !== $("customCss")) $("customCss").value = L.customCss || "";
    {   // a light background is shown darker (the island's text is light): say so under the picker
      const n = parseInt(L.bg.slice(1), 16), r = (n >> 16) / 255, g = ((n >> 8) & 255) / 255, b = (n & 255) / 255;
      const light = (Math.max(r, g, b) + Math.min(r, g, b)) / 2 > 0.22;
      const row = panel.querySelector('[data-row="bg"] .label span');
      if (row) row.textContent = light ? "Shown a little darker on the island, so its text stays readable" : "The island's colour";
    }
    renderPrio(L); renderPopTable(L); renderLists(L); renderAlarmChips(L); renderExtensions(L); renderBoards(L);
    fitPreview(L);
    buildToc();
  }

  // ---------------------------------------------------------------- widget pages (boards)
  const SIZE_NAMES = { s: "Small", w: "Wide", t: "Tall", b: "Big", f: "Full width" };
  const CELLS = { s: [1, 1], w: [2, 1], t: [1, 2], b: [2, 2], f: [4, 1] };
  const WIDGET_SIZES = {
    music: ["b", "w", "f"], today: ["t", "w", "b", "s"], prayer: ["t", "w", "b"], weather: ["t", "s", "w"], clips: ["w", "b", "f"],
    pc: ["w", "f", "b"], agents: ["b", "w", "t", "f"], timer: ["t", "w", "s", "b"], calendar: ["b", "w", "t"], alerts: ["b", "t", "w"],
    shelf: ["w", "b", "f"], notes: ["b", "w", "t", "f"], sports: ["w", "b"], prompter: ["b", "f", "w"], battery: ["w", "s", "b"],
  };
  const WNAME = { music: "Now playing", today: "Today: the date, Hijri date, countdowns", prayer: "Next prayer", weather: "Weather", clips: "Recent clips", pc: "PC: CPU, GPU, RAM, ping",
                  agents: "AI agents", timer: "Timer", calendar: "Calendar", alerts: "Notifications", shelf: "Shelf", notes: "Notes",
                  sports: "Scores", prompter: "Teleprompter", battery: "Battery" };
  const WCOLOR = { music: "#ff375f", today: "#ffd479", prayer: "#ffd479", weather: "#64d2ff", clips: "#0a84ff", pc: "#30d158", agents: "#d97757", timer: "#ff9f0a",
                   calendar: "#ff453a", alerts: "#5e5ce6", shelf: "#64d2ff", notes: "#ffd60a", sports: "#32d74b", prompter: "#bf5af2", battery: "#30d158" };
  const allWidgets = () => [...Object.keys(WIDGET_SIZES), ...((extra && extra.extensions) || []).map((x) => "ext-" + x.id)];
  const sizesOf = (w) => WIDGET_SIZES[w] || ["b", "w", "f", "s"];
  const wname = (w) => WNAME[w] || (((extra && extra.extensions) || []).find((x) => "ext-" + x.id === w) || {}).name || w;
  const used = (b) => b.widgets.reduce((n, x) => n + CELLS[x.s][0] * CELLS[x.s][1], 0);
  // does a page's set of widgets fit the 4 x 2 grid (packed like the island's grid)?
  function fits(ws) {
    const g = [[0, 0, 0, 0], [0, 0, 0, 0]];
    return ws.every((x) => {
      const [w, h] = CELLS[x.s];
      for (let r = 0; r <= 2 - h; r++) for (let c = 0; c <= 4 - w; c++) {
        let free = true;
        for (let y = 0; y < h; y++) for (let k = 0; k < w; k++) if (g[r + y][c + k]) free = false;
        if (free) { for (let y = 0; y < h; y++) for (let k = 0; k < w; k++) g[r + y][c + k] = 1; return true; }
      }
      return false;
    });
  }
  function renderBoards(L) {
    const box = $("boardsEd");
    if (!box) return;
    box.hidden = L.pageMode !== "boards";
    const sec = $("s-boards");
    if (sec) sec.hidden = box.hidden;               // Classic has no widget pages to arrange
    const classic = $("s-pages");
    if (classic) classic.hidden = L.pageMode === "boards";
    if (box.hidden) return;
    if (box.contains(document.activeElement) && document.activeElement.tagName === "INPUT") return;   // typing a name
    const B = L.boards || [];
    box.innerHTML = B.map((b, i) => {
      const free = 8 - used(b);
      const addable = allWidgets().filter((w) => !b.widgets.some((x) => x.w === w) && sizesOf(w).some((z) => fits([...b.widgets, { w, s: z }])));
      return `<div class="board" data-b="${i}">
        <div class="item bhead"><input class="field bname" data-bn="${i}" value="${esc(b.name)}" maxlength="20" placeholder="Page name">
          <span class="hint">${free} of 8 free</span>
          <button class="mv" data-bm="-1" data-b="${i}" ${i === 0 ? "disabled" : ""} title="Move page up">▲</button>
          <button class="mv" data-bm="1" data-b="${i}" ${i === B.length - 1 ? "disabled" : ""} title="Move page down">▼</button>
          <button class="btn warn" data-bdel="${i}" ${B.length < 2 ? "disabled" : ""} title="Delete page">Delete</button></div>
        <div class="bmap" data-map="${i}" style="grid-template-rows: repeat(2, 34px)">${b.widgets.map((x, j) => `<i class="m-${x.s}" draggable="true" data-mb="${i}" data-mj="${j}" title="Drag onto another widget to swap them, or onto an empty spot on any page" style="--c:${WCOLOR[x.w] || "#8e8e93"}">${esc(wname(x.w).split(":")[0])}</i>`).join("")}</div>
        ${b.widgets.map((x, j) => `<div class="item wrow"><span class="wdot" style="background:${WCOLOR[x.w] || "#8e8e93"}"></span>
          <div class="label"><b>${esc(wname(x.w))}</b></div>
          <div class="seg">${sizesOf(x.w).map((z) => {
            const ok = z === x.s || fits(b.widgets.map((y, k) => (k === j ? { ...y, s: z } : y)));
            return `<button data-ws="${z}" data-b="${i}" data-j="${j}" class="${z === x.s ? "on" : ""}" ${ok ? "" : "disabled"} title="${ok ? `${CELLS[z][0]}×${CELLS[z][1]} cells` : "No room on this page"}">${SIZE_NAMES[z]}</button>`;
          }).join("")}</div>
          <button class="mv" data-wm="-1" data-b="${i}" data-j="${j}" ${j === 0 ? "disabled" : ""}>▲</button>
          <button class="mv" data-wm="1" data-b="${i}" data-j="${j}" ${j === b.widgets.length - 1 ? "disabled" : ""}>▼</button>
          <button class="btn warn" data-wdel="${i}" data-j="${j}" title="Remove from this page">×</button></div>`).join("")}
        ${addable.length ? `<div class="item"><select class="field" data-wadd="${i}"><option value="">Add a widget…</option>${addable.map((w) => `<option value="${w}">${esc(wname(w))}</option>`).join("")}</select></div>` : ""}
      </div>`;
    }).join("") + (B.length < 6 ? `<div class="item"><button class="btn primary" id="boardAdd">Add a page</button><span class="hint">Up to 6 pages, 8 cells each (4 across, 2 down)</span></div>` : "");
  }
  // ---- drag a widget in the maps: onto another widget = swap them (same page
  // or another), onto a page's empty space = move it there. Anything that
  // wouldn't fit, or would put a widget twice on one page, is refused.
  let dragW = null;
  function tryBoards(B, msg) {
    for (const b of B) if (!fits(b.widgets) || new Set(b.widgets.map((x) => x.w)).size !== b.widgets.length) { S.status(msg); return false; }
    S.change({ boards: B.filter((b) => b.widgets.length) });
    return true;
  }
  panel.addEventListener("dragstart", (e) => {
    const t = e.target.closest && e.target.closest(".bmap [data-mb]"); if (!t) return;
    dragW = { b: +t.dataset.mb, j: +t.dataset.mj };
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", "hop-widget");
    requestAnimationFrame(() => t.classList.add("dragging"));
  });
  panel.addEventListener("dragend", () => { dragW = null; panel.querySelectorAll(".bmap .dragging, .bmap .over, .bmap.over").forEach((x) => x.classList.remove("dragging", "over")); });
  panel.addEventListener("dragover", (e) => {
    if (!dragW) return;
    const map = e.target.closest && e.target.closest(".bmap"); if (!map) return;
    e.preventDefault();
    const blk = e.target.closest("[data-mb]");
    panel.querySelectorAll(".bmap .over, .bmap.over").forEach((x) => x.classList.remove("over"));
    (blk || map).classList.add("over");
  });
  panel.addEventListener("drop", (e) => {
    if (!dragW) return;
    const map = e.target.closest && e.target.closest(".bmap"); if (!map) return;
    e.preventDefault();
    const blk = e.target.closest("[data-mb]");
    const B = structuredClone(S.L.boards), from = dragW;
    const src = B[from.b].widgets[from.j];
    if (blk) {
      const to = { b: +blk.dataset.mb, j: +blk.dataset.mj };
      if (to.b === from.b && to.j === from.j) return;
      const dst = B[to.b].widgets[to.j];
      if (to.b === from.b) {                          // same page: swap their places
        B[from.b].widgets[from.j] = dst; B[to.b].widgets[to.j] = src;
      } else {                                        // two pages: each takes the other's spot, keeping its own size if it fits
        const fitSize = (w, list, k) => [w.s, ...sizesOf(w.w).filter((z) => z !== w.s)].find((z) => fits(list.map((y, n) => (n === k ? { ...w, s: z } : y))));
        const a = { ...dst }, c = { ...src };
        B[from.b].widgets[from.j] = a; B[to.b].widgets[to.j] = c;
        const sa = fitSize(a, B[from.b].widgets, from.j), sc = fitSize(c, B[to.b].widgets, to.j);
        if (!sa || !sc) { S.status("Those two can't swap: one wouldn't fit on the other page"); return; }
        a.s = sa; c.s = sc;
      }
      if (tryBoards(B, "That swap doesn't fit")) S.status(`Swapped ${wname(src.w)} and ${wname(dst.w)}`, true);
    } else {
      const to = +map.dataset.map;
      if (to === from.b) return;
      if (B[to].widgets.some((x) => x.w === src.w)) { S.status(`${wname(src.w)} is already on that page`); return; }
      B[from.b].widgets.splice(from.j, 1);
      const size = [src.s, ...sizesOf(src.w).filter((z) => z !== src.s)].find((z) => fits([...B[to].widgets, { w: src.w, s: z }]));
      if (!size) { S.status("No room on that page"); return; }
      B[to].widgets.push({ w: src.w, s: size });
      if (tryBoards(B, "No room on that page")) S.status(`Moved ${wname(src.w)} to ${B[to].name}`, true);
    }
  });

  const setBoards = (fn) => { const B = structuredClone(S.L.boards); fn(B); S.change({ boards: B }); };
  panel.addEventListener("click", (e) => {
    const t = e.target.closest("button"); if (!t || !t.closest("#boardsEd")) return;
    const i = +t.dataset.b, j = +t.dataset.j;
    if (t.id === "boardAdd") setBoards((B) => B.push({ name: `Page ${B.length + 1}`, widgets: [{ w: "notes", s: "b" }] }));
    else if (t.dataset.bm) setBoards((B) => { const [x] = B.splice(i, 1); B.splice(i + +t.dataset.bm, 0, x); });
    else if (t.dataset.bdel != null) setBoards((B) => B.splice(+t.dataset.bdel, 1));
    else if (t.dataset.ws) {
      const ws = S.L.boards[i].widgets.map((y, k) => (k === j ? { ...y, s: t.dataset.ws } : y));
      if (!fits(ws)) { S.status("No room for that size on this page"); return; }   // nothing saved, and it says so
      setBoards((B) => { B[i].widgets[j].s = t.dataset.ws; });
    }
    else if (t.dataset.wm) setBoards((B) => { const ws = B[i].widgets; const [x] = ws.splice(j, 1); ws.splice(j + +t.dataset.wm, 0, x); });
    else if (t.dataset.wdel != null) setBoards((B) => { B[+t.dataset.wdel].widgets.splice(j, 1); if (!B[+t.dataset.wdel].widgets.length) B.splice(+t.dataset.wdel, 1); });
  });
  panel.addEventListener("change", (e) => {
    const t = e.target;
    if (t.dataset.wadd != null && t.value) {
      e.stopPropagation();
      const i = +t.dataset.wadd, w = t.value;
      setBoards((B) => { B[i].widgets.push({ w, s: sizesOf(w).find((z) => fits([...B[i].widgets, { w, s: z }])) }); });
    } else if (t.dataset.bn != null) {
      e.stopPropagation();
      setBoards((B) => { B[+t.dataset.bn].name = t.value.trim() || `Page ${+t.dataset.bn + 1}`; });
    }
  }, true);

  // ---------------------------------------------------------------- priority order (drag)
  function renderPrio(L) {
    $("prio").innerHTML = L.priority.map((k, i) => `<div class="item pg-row" draggable="true" data-p="${k}"><span class="grip">⋮⋮</span>
      <div class="label"><b>${i + 1}. ${esc(LIVE_NAMES[k] || k)}</b></div>
      <button class="mv" data-pm="-1" data-p="${k}" ${i === 0 ? "disabled" : ""}>▲</button><button class="mv" data-pm="1" data-p="${k}" ${i === L.priority.length - 1 ? "disabled" : ""}>▼</button></div>`).join("");
  }
  const movePrio = (k, to) => { const p = S.L.priority.filter((x) => x !== k); p.splice(Math.max(0, Math.min(p.length, to)), 0, k); S.change({ priority: p }); };
  $("prio").addEventListener("click", (e) => { const b = e.target.closest("[data-pm]"); if (b) movePrio(b.dataset.p, S.L.priority.indexOf(b.dataset.p) + +b.dataset.pm); });
  let dragP = null;
  $("prio").addEventListener("dragstart", (e) => { const r = e.target.closest("[data-p]"); if (r) dragP = r.dataset.p; });
  $("prio").addEventListener("dragover", (e) => { if (dragP) e.preventDefault(); });
  $("prio").addEventListener("drop", (e) => { const r = e.target.closest(".pg-row"); if (r && dragP && r.dataset.p !== dragP) movePrio(dragP, S.L.priority.filter((x) => x !== dragP).indexOf(r.dataset.p)); dragP = null; });

  // ---------------------------------------------------------------- every pop-up: on, how long, which sound
  function renderPopTable(L) {
    const P = L.popups || {};
    $("popTable").innerHTML = Object.entries(POP_NAMES).map(([k, [t, d]]) => {
      const p = P[k] || { on: true, ms: 5000, sound: "none" };
      const secs = [...new Set([0, 1500, 2500, 4000, 5000, 7000, 10000, 12000, 15000, 30000, p.ms])].sort((x, y) => x - y);
      return `<div class="item" data-row="pop-${k}">${lab(t, d)}
        <select class="field mini-sel" data-pk="${k}" data-pf="ms" title="How long it stays">${secs.map((s) => `<option value="${s}" ${s === p.ms ? "selected" : ""}>${s ? s / 1000 + " s" : "Until closed"}</option>`).join("")}</select>
        <select class="field mini-sel" data-pk="${k}" data-pf="sound" title="Sound">${SOUNDS.map(([v, n]) => `<option value="${v}" ${v === p.sound ? "selected" : ""}>${n}</option>`).join("")}</select>
        <label class="sw"><input type="checkbox" data-pk="${k}" data-pf="on" ${p.on ? "checked" : ""}><i></i></label></div>`;
    }).join("");
  }
  $("popTable").addEventListener("change", (e) => {
    const t = e.target, k = t.dataset.pk, f = t.dataset.pf; if (!k) return;
    e.stopPropagation();
    const P = structuredClone(S.L.popups);
    P[k][f] = f === "on" ? t.checked : f === "ms" ? +t.value : t.value;
    S.change({ popups: P });
    if (f === "sound" && t.value !== "none") S.api.play_sound(t.value);
  });

  // ---------------------------------------------------------------- small list editors
  function listEditor(box, key, title, hint, fields, blank) {
    const items = S.L[key] || [];
    $(box).innerHTML = `<div class="item"><div class="label"><b>${esc(title)}</b><span>${esc(hint)}</span></div>${key === "hideApps" ? '<input class="field" id="hideIn" placeholder="app.exe" style="max-width:150px">' : ""}<button class="btn" data-add="${key}">Add</button></div>` +
      items.map((it, i) => `<div class="item" data-li="${i}">${fields.map(([f, type, ph, opts]) => type === "select"
        ? `<select class="field" data-lk="${key}" data-lf="${f}" data-li="${i}">${opts.map(([v, n]) => `<option value="${v}" ${String(it[f]) === v ? "selected" : ""}>${esc(n)}</option>`).join("")}</select>`
        : type === "check" ? `<label class="sw"><input type="checkbox" data-lk="${key}" data-lf="${f}" data-li="${i}" ${it[f] !== false ? "checked" : ""}><i></i></label>`
        : `<input class="field" type="${type}" data-lk="${key}" data-lf="${f}" data-li="${i}" value="${esc(it[f] ?? "")}" placeholder="${esc(ph || "")}" ${type === "number" ? 'style="max-width:80px"' : ""}>`).join("")}
        <button class="btn warn" data-del="${key}" data-li="${i}">×</button></div>`).join("");
    $(box).dataset.blank = JSON.stringify(blank);
  }
  function renderLists(L) {
    if (panel.contains(document.activeElement) && document.activeElement.dataset.lk) return;      // don't redraw under the cursor
    listEditor("countdowns", "countdowns", "Countdowns", "Days to a date, on the Today page", [["name", "text", "Birthday"], ["date", "date"]], { name: "New countdown", date: new Date(Date.now() + 864e6).toISOString().slice(0, 10) });
    listEditor("reminders", "reminders", "Reminders", "A pop-up every few minutes between two times", [["text", "text", "Drink water"], ["every", "number", "min"], ["from", "time"], ["to", "time"], ["on", "check"]], { text: "Stretch", every: 45, from: "09:00", to: "21:00", on: true });
    listEditor("teams", "teams", "Your teams", "The Scores page and goal pop-ups", [["league", "select", "", LEAGUES], ["team", "text", "Team name, e.g. Arsenal"]], { league: "epl", team: "Arsenal" });
    listEditor("hideApps", "hideApps", "Hide in these apps", "The island steps aside while one of these is in front (e.g. powerpnt.exe)", [["exe", "text", "app.exe"]], { exe: "" });
  }
  // hideApps is a list of names; the editor works on objects
  const asObjs = (key, v) => key === "hideApps" ? v.map((exe) => ({ exe })) : v;
  const fromObjs = (key, v) => key === "hideApps" ? v.map((o) => o.exe).filter(Boolean) : v;
  panel.addEventListener("click", (e) => {
    const add = e.target.closest("[data-add]"), del = e.target.closest("[data-del]");
    if (add) {
      const key = add.dataset.add, box = add.closest("[id]");
      const blank = JSON.parse(box.dataset.blank);
      if (key === "hideApps") {
        const name = ($("hideIn").value || "").trim().toLowerCase();
        if (!/^[\w .()+-]{1,80}\.exe$/i.test(name)) { S.status("Type the app's .exe name, e.g. powerpnt.exe"); return; }
        $("hideIn").value = "";
        S.change({ hideApps: [...S.L.hideApps, name] });
        return;
      }
      S.change({ [key]: [...asObjs(key, S.L[key]), blank] });
    }
    if (del) { const key = del.dataset.del; S.change({ [key]: fromObjs(key, asObjs(key, S.L[key]).filter((_, i) => i !== +del.dataset.li)) }); }
  });
  panel.addEventListener("change", (e) => {
    const t = e.target; if (!t.dataset.lk) return;
    e.stopPropagation();
    const key = t.dataset.lk, list = structuredClone(asObjs(key, S.L[key]));
    list[+t.dataset.li][t.dataset.lf] = t.type === "checkbox" ? t.checked : t.type === "number" ? +t.value : t.value;
    S.change({ [key]: fromObjs(key, list) });
  }, true);

  // ---------------------------------------------------------------- prayer chips + sound test
  function renderAlarmChips(L) {
    $("alarmPrayers").innerHTML = ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"].map((n) => `<button class="chip ${L.alarmPrayers.includes(n) ? "on" : ""}" data-pr="${n}">${n}</button>`).join("");
  }
  $("alarmPrayers").addEventListener("click", (e) => {
    const b = e.target.closest("[data-pr]"); if (!b) return;
    const set = new Set(S.L.alarmPrayers); set.has(b.dataset.pr) ? set.delete(b.dataset.pr) : set.add(b.dataset.pr);
    S.change({ alarmPrayers: ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"].filter((n) => set.has(n)) });
  });
  $("soundTest").addEventListener("click", () => S.L.alarmSound !== "none" && S.api.play_sound(S.L.alarmSound));

  // ---------------------------------------------------------------- extensions
  function renderExtensions(L) {
    const xs = (extra && extra.extensions) || [];
    $("extList").innerHTML = xs.length ? xs.map((x) => `<div class="item">${lab(x.name, x.description)}<label class="sw"><input type="checkbox" data-ext="${esc(x.id)}" ${L.extensions.includes(x.id) ? "checked" : ""}><i></i></label></div>`).join("")
      : `<div class="item"><div class="label"><span>No extensions installed yet.</span></div></div>`;
  }
  $("extList").addEventListener("change", (e) => {
    const id = e.target.dataset.ext; if (!id) return;
    e.stopPropagation();
    const on = new Set(S.L.extensions); e.target.checked ? on.add(id) : on.delete(id);
    S.change({ extensions: [...on] });
  });
  $("extFolder").addEventListener("click", () => S.api.open_extensions_folder());

  // ---------------------------------------------------------------- the host's other settings
  function renderExtra() {
    if (!extra) return;
    const a = extra.agents || {};
    $("agState").textContent = a.connected ? "Connected: Hop hears your Claude Code sessions" : "Not connected. Connect adds Hop's hooks to Claude Code's settings (a backup is kept).";
    $("agConnect").textContent = a.connected ? "Disconnect" : "Connect";
    $("agConnect").classList.toggle("primary", !a.connected);
    if (document.activeElement !== $("calUrl")) $("calUrl").value = extra.calendarUrl || "";
    if (document.activeElement !== $("prompterText")) $("prompterText").value = extra.prompter || "";
    $("monSel").innerHTML = (extra.monitors || []).map((m) => `<option value="${m.index}">${esc(m.name)}${m.primary ? " (main)" : ""}</option>`).join("");
    if (S.L) $("monSel").value = String(S.L.monitorIndex);
    $("profSel").innerHTML = (extra.profiles || []).map((p) => `<option ${p === extra.activeProfile ? "selected" : ""}>${esc(p)}</option>`).join("") || "<option disabled>No profiles yet</option>";
    $("profRules").innerHTML = `<div class="item"><div class="label"><b>Switch profile by app</b><span>When one of these apps is in front, its profile is used</span></div><button class="btn" id="ruleAdd">Add</button></div>` +
      (extra.profileRules || []).map((r, i) => `<div class="item"><input class="field" data-rule="${i}" data-rf="exe" value="${esc(r.exe)}" placeholder="robloxplayerbeta.exe">
        <select class="field" data-rule="${i}" data-rf="profile">${(extra.profiles || []).map((p) => `<option ${p === r.profile ? "selected" : ""}>${esc(p)}</option>`).join("")}</select>
        <button class="btn warn" data-ruledel="${i}">×</button></div>`).join("");
    const lf = extra.lastfm || {};
    $("lfState").textContent = lf.connected ? `Connected as ${lf.user}` : "Make a free API account at last.fm/api/account/create, then connect";
    renderExtensions(S.L || { extensions: [] });
  }
  const setExtra = async (patch) => { S.status("Saving…"); extra = await S.api.set_extra(patch); renderExtra(); S.status("Saved", true); };
  $("agConnect").addEventListener("click", async () => {
    S.status("Saving…");
    extra.agents = await S.api.agents_connect(!(extra.agents || {}).connected);
    renderExtra(); S.status(extra.agents.connected ? "Connected · start a new Claude Code session" : "Disconnected", true);
  });
  $("calSave").addEventListener("click", () => setExtra({ calendarUrl: $("calUrl").value.trim() }));
  let prTimer = 0;
  $("prompterText").addEventListener("input", () => { clearTimeout(prTimer); prTimer = setTimeout(() => setExtra({ prompter: $("prompterText").value }), 600); });
  $("profSave").addEventListener("click", async () => { const n = $("profName").value.trim(); if (!n) return; extra.profiles = await S.api.profile_save(n); extra.activeProfile = n; $("profName").value = ""; renderExtra(); S.status(`Saved as “${n}”`, true); });
  $("profLoad").addEventListener("click", async () => { const n = $("profSel").value; if (!n) return; await S.commit(await S.api.profile_load(n)); extra.activeProfile = n; renderExtra(); S.status(`Switched to “${n}”`, true); });
  $("profDel").addEventListener("click", async () => { const n = $("profSel").value; if (!n) return; extra.profiles = await S.api.profile_delete(n); renderExtra(); S.status("Deleted", true); });
  panel.addEventListener("click", (e) => {
    if (e.target.id === "ruleAdd") setExtra({ profileRules: [...(extra.profileRules || []), { exe: "", profile: (extra.profiles || [])[0] || "" }] });
    const d = e.target.closest("[data-ruledel]"); if (d) setExtra({ profileRules: extra.profileRules.filter((_, i) => i !== +d.dataset.ruledel) });
  });
  panel.addEventListener("change", (e) => {
    const t = e.target; if (t.dataset.rule == null) return;
    e.stopPropagation();
    const rules = structuredClone(extra.profileRules);
    rules[+t.dataset.rule][t.dataset.rf] = t.dataset.rf === "exe" ? t.value.trim().toLowerCase() : t.value;
    setExtra({ profileRules: rules });
  }, true);
  $("themeCopy").addEventListener("click", async () => {
    const code = await S.api.theme_code();
    try { await navigator.clipboard.writeText(code); S.status("Theme code copied", true); } catch { $("themeIn").value = code; S.status("Theme code is in the box below", true); }
  });
  $("themeApply").addEventListener("click", async () => {
    const L = await S.api.theme_apply($("themeIn").value);
    if (!L) { S.status("That isn't a Hop theme code"); return; }
    await S.commit(L); $("themeIn").value = ""; S.status("Theme applied", true);
  });
  $("cssSave").addEventListener("click", () => S.change({ customCss: $("customCss").value }));
  // the island page builds it (it knows the exact values in use) and answers by message
  $("cssCopy").addEventListener("click", () => {
    const pv = $("pv").contentWindow;
    const got = (e) => {
      if (!e.data || e.data.t !== "themecss") return;
      window.removeEventListener("message", got);
      navigator.clipboard.writeText(e.data.css).then(() => S.status("CSS copied: paste it into Custom CSS", true),
        () => { $("customCss").value = e.data.css; S.status("Clipboard blocked: the CSS is in the box above", true); });
    };
    window.addEventListener("message", got);
    pv.postMessage({ t: "themecss" }, "*");
  });
  $("lfGo").addEventListener("click", async () => {
    $("lfState").textContent = "Connecting…";
    const r = await S.api.lastfm_login($("lfUser").value, $("lfPass").value, $("lfKey").value, $("lfSecret").value);
    $("lfPass").value = "";
    if (r && r.connected) { extra.lastfm = r; renderExtra(); } else $("lfState").textContent = (r && r.error) || "Couldn't connect";
  });
  S.ready.then(() => S.api.get_startup()).then((on) => { $("startup").checked = !!on; });
  $("startup").addEventListener("change", async (e) => {
    e.stopPropagation();
    S.status("Saving…");
    $("startup").checked = !!(await S.api.set_startup($("startup").checked));
    S.status($("startup").checked ? "Hop Island will start with Windows" : "Hop Island won't start with Windows", true);
  });
  $("bkExport").addEventListener("click", async () => { const p = await S.api.export_settings(); S.status(p ? "Saved to " + p : "Couldn't save", !!p); });
  $("bkImport").addEventListener("click", async () => { const L = await S.api.import_settings(); if (L) { await S.commit(L); S.status("Settings imported", true); } });
  $("diag").addEventListener("click", async () => { $("diag").textContent = "Zipping…"; const p = await S.api.diagnostics(); $("diag").textContent = "Make zip"; S.status(p ? "Saved to " + p : "Couldn't make it", !!p); });

  // ---------------------------------------------------------------- start
  window.__settingsRender = (L) => renderControls(L);
  window.__demoLayout = () => {};
  S.ready.then(async () => {
    extra = await S.api.get_extra();
    renderExtra();
    if (S.L) renderControls(S.L);
  });
  const style = document.createElement("style");
  style.textContent = `
    input[type=color].clr { width: 38px; height: 26px; padding: 0; border: 1px solid var(--line); border-radius: 7px; background: none; cursor: pointer; }
    input[type=color].clr::-webkit-color-swatch-wrapper { padding: 2px; } input[type=color].clr::-webkit-color-swatch { border: 0; border-radius: 5px; }
    .field.tm { flex: 0 0 auto; max-width: 120px; }
    .field.mini-sel { flex: 0 0 auto; max-width: 118px; padding: 5px 8px; font-size: 12.5px; }
    #popTable .item .label span { font-size: 12px; }
    .item input[type=range]:disabled { opacity: 0.35; }
    .stage iframe { transition: transform 320ms cubic-bezier(.3, 1.1, .5, 1); }
    .search-note { position: sticky; top: -22px; z-index: 3; margin: -22px -26px 14px; padding: 12px 26px; display: flex; flex-wrap: wrap; align-items: center; gap: 8px;
      font-size: 13px; color: var(--dim); background: var(--bg); border-bottom: 1px solid var(--line); }
    .item.flash { animation: flash 1.2s ease; }
    @keyframes flash { 0%, 40% { background: color-mix(in srgb, var(--blue) 22%, transparent); } 100% { background: transparent; } }
    .item.near { box-shadow: inset 3px 0 0 var(--blue); }
    .board { border-top: 1px solid var(--line); }
    .board:first-child { border-top: 0; }
    .board .bhead .bname { max-width: 220px; font-weight: 600; }
    .board .wrow { padding-left: 22px; }
    #popTable.folded .item:nth-child(n + 6) { display: none; }
    .board .seg button:disabled { opacity: 0.35; cursor: not-allowed; }
    .board .wdot { width: 9px; height: 9px; border-radius: 3px; flex: none; }
    .bmap { display: grid; grid-template-columns: repeat(4, 1fr); grid-template-rows: repeat(2, 34px); grid-auto-flow: dense; gap: 4px;
      margin: 2px 14px 8px; padding: 6px; border-radius: 12px; background: #000; }
    .bmap i { font-style: normal; font-size: 12px; font-weight: 600; color: #fff; border-radius: 7px; display: grid; place-items: center;
      background: color-mix(in srgb, var(--c) 34%, #1c1c1e); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--c) 55%, transparent);
      overflow: hidden; white-space: nowrap; text-overflow: ellipsis; padding: 0 6px; }
    .bmap .m-s { grid-column: span 1; } .bmap .m-w { grid-column: span 2; } .bmap .m-t { grid-row: span 2; }
    .bmap .m-b { grid-column: span 2; grid-row: span 2; } .bmap .m-f { grid-column: span 4; }
    .bmap i[draggable] { cursor: grab; transition: transform 140ms ease, opacity 140ms ease, box-shadow 140ms ease; }
    .bmap i[draggable]:active { cursor: grabbing; }
    .bmap i.dragging { opacity: 0.35; }
    .bmap i.over { transform: scale(1.04); box-shadow: inset 0 0 0 2px #fff, 0 0 0 2px var(--blue); }
    .bmap.over { box-shadow: 0 0 0 2px var(--blue); }`;
  document.head.appendChild(style);
})();
