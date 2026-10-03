"""The settings app and the island page in a real browser (Chromium, as in
WebView2), wired to the REAL host API: every click goes through the same
Python code the app runs, and is checked both on screen and in the saved
settings. The island's window is a real (hidden) Windows window."""
import ctypes
import itertools
import os

import pytest

import host

playwright = pytest.importorskip("playwright.sync_api")

BRIDGE = """
window.pywebview = { api: new Proxy({}, { get: (_, name) => (...args) => window.__hopcall(name, args) }) };
window.addEventListener('DOMContentLoaded', () => window.dispatchEvent(new Event('pywebviewready')));
"""


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture()
def app(browser, sandbox):
    """The settings app, with a real Island behind it."""
    for f in (host.CONFIG, host.CLIPPER_SETTINGS):
        if os.path.exists(f):
            os.remove(f)
    isl = host.Island()
    isl.set_layout({"pageMode": "pages"})          # these tests are about the classic pages (boards: test_boards.py)
    u32 = ctypes.windll.user32
    u32.CreateWindowExW.restype = ctypes.c_void_p
    hwnd = u32.CreateWindowExW(0x80, "STATIC", "hop-test-island", 0x80000000, 100, 10, 360, 196, None, None, None, None)
    isl.hwnd = hwnd
    api = host.SettingsApi(isl)
    page = host.build_web()
    pg = browser.new_page(viewport={"width": 1100, "height": 800})
    pg.expose_function("__hopcall", lambda name, args: getattr(api, name)(*args))
    pg.add_init_script(BRIDGE)
    pg.goto("file:///" + os.path.join(os.path.dirname(page), "settings.html").replace("\\", "/"))
    pg.wait_for_function("document.getElementById('status').textContent.includes('saved')", timeout=20000)
    frame = next(f for f in pg.frames if "preview" in f.url)
    frame.wait_for_function("document.getElementById('island').className.includes('open')", timeout=20000)
    yield pg, frame, isl
    pg.close()
    u32.DestroyWindow(ctypes.c_void_p(hwnd))


def saved():
    return host.clean_layout(host.read_config().get("layout"))


def classes(frame):
    return frame.evaluate("document.getElementById('island').className").split()


# ================================================================ it opens
def test_opens_with_everything(app):
    pg, frame, _ = app
    assert pg.locator("#pages .pg-row").count() == len(host.PAGE_IDS)   # every page listed...
    assert pg.locator("#chips .chip").count() == 4                     # ...the 4 classic ones showing (newer ones start hidden)
    assert pg.get_attribute("#brandImg", "src").startswith("brand-island")
    assert "playing" in classes(frame) or "empty" in classes(frame)


# ================================================================ every switch
FLAG = {"lyricLine": "no-lyric", "progress": "no-progress", "controls": "no-controls", "volume": "no-vol",
        "snap": "no-snap", "pillArt": "pill-no-art", "pillClock": "pill-no-clock", "pillBars": "pill-no-bars",
        "todayHijri": "no-hij", "todayEvents": "no-evts", "todayWeather": "no-wx", "todayPrayers": "no-strip",
        "gCpu": "no-g-cpu", "gGpu": "no-g-gpu", "gRam": "no-g-ram", "gDiskC": "no-g-diskC", "gDiskE": "no-g-diskE",
        "gPing": "no-g-ping"}
SWITCHES = [k for k in host.BOOL_KEYS]


@pytest.mark.parametrize("key", SWITCHES)
def test_switch_off_and_on(app, key):
    pg, frame, _ = app
    box = pg.locator(f"#tab-island input[data-key={key}]")
    box.scroll_into_view_if_needed()
    box.click(force=True)
    pg.wait_for_function(f"document.getElementById('status').textContent.startsWith('Saved')")
    assert saved()[key] is False
    if key in FLAG:
        frame.wait_for_function(f"document.getElementById('island').classList.contains('{FLAG[key]}')")
    box.click(force=True)
    pg.wait_for_timeout(250)
    assert saved()[key] is True
    if key in FLAG:
        assert FLAG[key] not in classes(frame)


# ================================================================ slots and theme
@pytest.mark.parametrize("key,value", [("musicLeft", v) for v in ("art", "none", "rec")]
                         + [("musicRight", v) for v in ("bars", "clock", "none", "prayer")])
def test_slots(app, key, value):
    pg, frame, _ = app
    pg.click(f".seg[data-key={key}] button[data-v={value}]")
    side = "left" if key == "musicLeft" else "right"
    frame.wait_for_function(f"document.getElementById('island').classList.contains('{side}-{value}')")
    assert saved()[key] == value


@pytest.mark.parametrize("theme", ["light", "dark", "system"])
def test_theme(app, theme):
    pg, _, _ = app
    pg.locator(".seg[data-key=appTheme]").scroll_into_view_if_needed()
    pg.click(f".seg[data-key=appTheme] button[data-v={theme}]")
    pg.wait_for_function(f"document.documentElement.dataset.theme === '{theme}'")
    assert saved()["appTheme"] == theme
    if theme == "light":
        assert pg.get_attribute("#brandImg", "src").endswith("-ink.png")
    if theme == "dark":
        assert not pg.get_attribute("#brandImg", "src").endswith("-ink.png")


# ================================================================ pages
@pytest.mark.parametrize("page", host.CORE_PAGES)
def test_hide_each_page(app, page):
    pg, frame, _ = app
    pg.click(f".pg-row[data-id={page}] .sw input", force=True)
    frame.wait_for_function(f"!window.__islandPageIds().includes('{page}')")
    assert page in saved()["hidden"]
    assert pg.locator("#chips .chip").count() == 3


def test_cannot_hide_last_page(app):
    pg, frame, _ = app
    for page in ("today", "clips", "pc"):
        pg.click(f".pg-row[data-id={page}] .sw input", force=True)
        pg.wait_for_timeout(250)
    pg.click(".pg-row[data-id=music] .sw input", force=True)
    pg.wait_for_timeout(300)
    assert frame.evaluate("window.__islandPageIds()") == ["music"]
    assert "music" not in saved()["hidden"]


@pytest.mark.parametrize("page,direction", [(p, d) for p in host.CORE_PAGES for d in (-1, 1)])
def test_move_page(app, page, direction):
    pg, frame, _ = app
    before = saved()["pages"]
    i = before.index(page)
    btn = pg.locator(f".pg-row[data-id={page}] .mv[data-mv='{direction}']")
    if btn.is_disabled():
        assert (i == 0 and direction == -1) or (i == 3 and direction == 1)
        return
    btn.click()
    pg.wait_for_timeout(300)
    after = saved()["pages"]
    assert after.index(page) == i + direction
    shown = [p for p in after if p not in saved()["hidden"]]
    assert frame.evaluate("window.__islandPageIds()") == shown


# the 4 core pages: 4! = 24 orders (all 13 pages would be 6 billion, which ran the PC out of memory)
@pytest.mark.parametrize("order", list(itertools.permutations(host.CORE_PAGES)))
def test_gear_on_last_page_any_order(app, order):
    """Whatever the order, the settings gear and refresh button sit on the last page."""
    pg, frame, isl = app
    L = isl.set_layout({**isl.layout, "pages": list(order)})
    pg.evaluate("L => document.getElementById('pv').contentWindow.postMessage({t:'cmd', fn:'Layout', args:[L]}, '*')", L)
    pg.evaluate("n => document.getElementById('pv').contentWindow.postMessage({t:'cmd', fn:'SetPage', args:[n]}, '*')", 3)
    frame.wait_for_function("document.getElementById('island').classList.contains('on-last')")
    assert frame.evaluate("window.__islandPageIds()") == list(order)
    # both fade in (0.2 s): wait for the end of the fade
    frame.wait_for_function("getComputedStyle(document.getElementById('gear')).opacity === '1'")
    frame.wait_for_function("getComputedStyle(document.getElementById('reload')).opacity === '1'")


# ================================================================ undo / reset
@pytest.mark.parametrize("steps", [1, 2, 3])
def test_undo(app, steps):
    pg, _, _ = app
    start = saved()
    for v in ("art", "none", "rec")[:steps]:
        pg.click(f".seg[data-key=musicLeft] button[data-v={v}]")
        pg.wait_for_timeout(250)
    for _ in range(steps):
        pg.click("#undo")
        pg.wait_for_timeout(300)
    assert saved()["musicLeft"] == start["musicLeft"]


def test_reset_layout_needs_two_clicks(app):
    pg, _, _ = app
    pg.click(".seg[data-key=musicRight] button[data-v=clock]")
    pg.wait_for_timeout(250)
    pg.locator("#resetLayout").scroll_into_view_if_needed()
    pg.click("#resetLayout")
    pg.wait_for_timeout(250)
    assert saved()["musicRight"] == "clock"                      # one click only arms it
    pg.click("#resetLayout")
    pg.wait_for_timeout(400)
    assert saved()["musicRight"] == "prayer"


# ================================================================ size and position (a real window)
@pytest.mark.parametrize("pct", [70, 85, 100, 120, 150])
def test_size(app, pct):
    pg, _, isl = app
    pg.locator("#scale").scroll_into_view_if_needed()
    pg.eval_on_selector("#scale", "(e, v) => { e.value = v; e.dispatchEvent(new Event('change')); }", pct)
    pg.wait_for_timeout(400)
    assert saved()["scale"] == pct / 100


@pytest.mark.parametrize("preset", ["0", "50", "100"])
def test_position_presets(app, preset):
    pg, _, isl = app
    pg.locator("#xPreset").scroll_into_view_if_needed()
    pg.click(f"#xPreset button[data-v='{preset}']")
    pg.wait_for_timeout(400)
    x = isl.get_position()["x"]
    l, t, r, b = isl.work_area()
    _, _, w, _ = isl.rect()
    half = w / 2 / (r - l) * 100
    assert abs(x - min(100 - half, max(half, float(preset)))) < 1.0   # clamped to stay on screen


@pytest.mark.parametrize("top", [0, 40, 200])
def test_position_from_top(app, top):
    pg, _, isl = app
    pg.eval_on_selector("#posTop", "(e, v) => { e.value = v; e.dispatchEvent(new Event('input')); }", top)
    pg.wait_for_timeout(500)
    assert abs(isl.get_position()["top"] - top) <= 1


# ================================================================ location, for real
@pytest.mark.network
def test_pick_a_city(app):
    pg, frame, isl = app
    pg.locator("#placeQ").scroll_into_view_if_needed()
    pg.fill("#placeQ", "Istanbul")
    pg.click("#placeGo")
    pg.wait_for_selector("#placeList button[data-i='0']", timeout=15000)
    pg.click("#placeList button[data-i='0']")
    pg.wait_for_function("document.getElementById('placeNow').textContent.includes('Istanbul')", timeout=20000)
    pg.wait_for_function("!document.getElementById('placeTimesRow').hidden", timeout=20000)
    assert "Fajr" in pg.inner_text("#placeTimes")
    frame.wait_for_function("document.getElementById('npTime').textContent.length > 0", timeout=20000)
    assert isl.cfg["location"]["label"].startswith("Istanbul")


@pytest.mark.network
@pytest.mark.parametrize("method", ["3", "13"])
def test_change_method(app, method):
    pg, _, isl = app
    isl.set_location(isl.search_city("London")[0])
    pg.locator("#method").scroll_into_view_if_needed()
    pg.select_option("#method", method)
    pg.wait_for_function("document.getElementById('status').textContent.startsWith('Saved')", timeout=20000)
    assert isl.cfg["prayerMethod"] == int(method)


# ================================================================ clipper tab
CLIP_SW = ["watermark", "cursor", "islandInClips", "toastInClips", "sounds"]


def open_clipper_tab(pg):
    pg.evaluate("document.querySelector('#tabs [data-tab=clipper]').hidden = false")
    pg.click("#tabs [data-tab=clipper]")
    pg.wait_for_timeout(300)


@pytest.mark.parametrize("key", CLIP_SW)
def test_clipper_switch(app, key):
    pg, _, _ = app
    open_clipper_tab(pg)
    before = host.clipper_settings()[key]
    pg.click(f"#tab-clipper input[data-ckey={key}]", force=True)
    pg.wait_for_timeout(400)
    assert host.clipper_settings()[key] is (not before)


@pytest.mark.parametrize("key,value", [("fps", "30"), ("fps", "60"), ("fps", "120"), ("quality", "best"),
                                       ("quality", "high"), ("quality", "small"), ("defaultSeconds", "15"),
                                       ("defaultSeconds", "30"), ("defaultSeconds", "60")])
def test_clipper_choice(app, key, value):
    pg, _, _ = app
    open_clipper_tab(pg)
    pg.click(f".seg[data-ckey={key}] button[data-v='{value}']")
    pg.wait_for_timeout(400)
    got = host.clipper_settings()[key]
    assert str(got) == value
    assert pg.locator(f".seg[data-ckey={key}] button.on").get_attribute("data-v") == value


def test_clipper_folder_default(app, sandbox):
    pg, _, isl = app
    isl.set_clipper({"saveDir": os.path.join(sandbox, "elsewhere")})
    open_clipper_tab(pg)
    pg.click("#cDirReset")
    pg.wait_for_timeout(400)
    assert host.clips_dir() == host.DEFAULT_CLIPS
    assert pg.inner_text("#cDir") == host.DEFAULT_CLIPS


def test_brand_follows_tab(app):
    pg, _, _ = app
    open_clipper_tab(pg)
    assert "brand-clipper" in pg.get_attribute("#brandImg", "src")
    pg.click("#tabs [data-tab=island]")
    assert "brand-island" in pg.get_attribute("#brandImg", "src")


# ================================================================ tooltips
@pytest.mark.parametrize("sel,text", [("#undo", "Ctrl+Z")])
def test_settings_tooltip(app, sel, text):
    pg, _, _ = app
    pg.hover(sel)
    pg.wait_for_function("t => document.querySelector('.hop-tip.on')?.textContent === t", arg=text, timeout=5000)
    assert pg.get_attribute(sel, "title") is None               # Windows' own tooltip never shows


@pytest.mark.parametrize("sel,text", [("#volBtn", "Volume"), ("#center", "Snap to top middle")])
def test_island_tooltip(app, sel, text):
    pg, frame, _ = app
    frame.hover(sel)
    frame.wait_for_function("t => document.querySelector('.hop-tip.on')?.textContent === t", arg=text, timeout=5000)


# ================================================================ preview open / closed, chips
@pytest.mark.parametrize("mode", ["closed", "open"])
def test_preview_mode(app, mode):
    pg, frame, _ = app
    pg.click(f"#pvMode button[data-v={mode}]")
    pg.wait_for_timeout(300)
    assert ("open" in classes(frame)) == (mode == "open")


@pytest.mark.parametrize("i", range(4))
def test_chip_shows_page(app, i):
    pg, frame, _ = app
    pg.click(f"#chips .chip[data-i='{i}']")
    pg.wait_for_timeout(300)
    on = frame.evaluate("[...document.querySelectorAll('.full .pg')].findIndex(p => p.classList.contains('on'))")
    ids = frame.evaluate("window.__islandPageIds()")
    assert frame.evaluate(f"document.querySelector('.full .pg.on').dataset.id") == ids[i]


# ================================================================ swipe up to dismiss (left button)
CLIP = {"kind": "clip", "url": "", "seconds": 15, "path": "C:/x.mp4"}


def show_card(pg, frame):
    frame.evaluate("c => window.__islandClip(c)", CLIP)
    frame.wait_for_function("document.getElementById('island').classList.contains('carding')")
    pg.wait_for_timeout(500)


def swipe(pg, frame, dy, steps=8, ms=10):
    box = frame.locator("#island").bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    pg.mouse.move(x, y)
    pg.mouse.down()
    for i in range(1, steps + 1):
        pg.mouse.move(x, y + dy * i / steps)
        pg.wait_for_timeout(ms)
    pg.mouse.up()
    pg.wait_for_timeout(700)


@pytest.mark.parametrize("dy", [-60, -120, -200])
def test_swipe_up_dismisses_card(app, dy):
    pg, frame, _ = app
    show_card(pg, frame)
    swipe(pg, frame, dy)
    assert "carding" not in classes(frame)


@pytest.mark.parametrize("dy", [-8, 20, 60])
def test_short_or_downward_swipe_springs_back(app, dy):
    pg, frame, _ = app
    show_card(pg, frame)
    swipe(pg, frame, dy, steps=10, ms=30)                       # slow: no flick
    assert "carding" in classes(frame)
    assert frame.evaluate("document.getElementById('island').style.transform") == ""


def test_quick_flick_dismisses(app):
    pg, frame, _ = app
    show_card(pg, frame)
    swipe(pg, frame, -18, steps=2, ms=1)                        # short but fast
    assert "carding" not in classes(frame)


def test_right_button_does_not_swipe(app):
    pg, frame, _ = app
    show_card(pg, frame)
    box = frame.locator("#island").bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    pg.mouse.move(x, y); pg.mouse.down(button="right"); pg.mouse.move(x, y - 120, steps=6); pg.mouse.up(button="right")
    pg.wait_for_timeout(500)
    assert "carding" in classes(frame)


def test_buttons_still_click(app):
    """A plain click on the card's buttons still works (the swipe waits for movement)."""
    pg, frame, _ = app
    show_card(pg, frame)
    frame.click("#cCopy")
    frame.wait_for_function("document.getElementById('cCopy').textContent.includes('Copied')")
    assert "carding" in classes(frame)


def test_right_click_has_no_menu(app):
    pg, frame, _ = app
    prevented = frame.evaluate("""() => { const e = new MouseEvent('contextmenu', {bubbles: true, cancelable: true});
        document.getElementById('island').dispatchEvent(e); return e.defaultPrevented; }""")
    assert prevented


def test_swipe_away_prayer_alarm(app):
    """A prayer alarm (the one with Dismiss) goes with a swipe too."""
    pg, frame, _ = app
    frame.evaluate("""() => {
        const now = new Date(), hm = d => String(d.getHours()).padStart(2,'0') + ':' + String(d.getMinutes()).padStart(2,'0');
        const day = {Fajr: '00:01', Sunrise: '00:02', Dhuhr: hm(now), Asr: '23:57', Maghrib: '23:58', Isha: '23:59'};
        const iso = now.getFullYear() + '-' + String(now.getMonth()+1).padStart(2,'0') + '-' + String(now.getDate()).padStart(2,'0');
        window.__islandPrayers({date: iso, today: day, tomorrow: day});
    }""")
    frame.wait_for_function("document.getElementById('island').classList.contains('alerting')", timeout=15000)
    pg.wait_for_timeout(500)
    swipe(pg, frame, -120)
    frame.wait_for_function("!document.getElementById('island').classList.contains('alerting')", timeout=3000)


def test_dismiss_button_still_works_on_alarm(app):
    pg, frame, _ = app
    frame.evaluate("""() => {
        const now = new Date(), hm = d => String(d.getHours()).padStart(2,'0') + ':' + String(d.getMinutes()).padStart(2,'0');
        const day = {Fajr: '00:01', Sunrise: '00:02', Dhuhr: hm(now), Asr: '23:57', Maghrib: '23:58', Isha: '23:59'};
        const iso = now.getFullYear() + '-' + String(now.getMonth()+1).padStart(2,'0') + '-' + String(now.getDate()).padStart(2,'0');
        window.__islandPrayers({date: iso, today: day, tomorrow: day});
    }""")
    frame.wait_for_function("document.getElementById('island').classList.contains('alerting')", timeout=15000)
    pg.wait_for_timeout(500)
    frame.click("#alStop")
    frame.wait_for_function("!document.getElementById('island').classList.contains('alerting')", timeout=3000)
