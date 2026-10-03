"""Widget pages (boards): the settings app's editor and the island page in a
real browser, on the real host API (like test_ui.py), plus the polish the
user asked for: every widget fits its tile at every size it allows, long
commands stay on one line, and the privacy dot gets room of its own."""
import ctypes
import os

import pytest

import host
import options

playwright = pytest.importorskip("playwright.sync_api")
from test_ui import BRIDGE, browser  # noqa: E402,F401  (the module's browser fixture)


@pytest.fixture()
def board_app(browser):
    for f in (host.CONFIG, host.CLIPPER_SETTINGS):
        if os.path.exists(f):
            os.remove(f)
    isl = host.Island()                                  # defaults: widget pages
    u32 = ctypes.windll.user32
    u32.CreateWindowExW.restype = ctypes.c_void_p
    hwnd = u32.CreateWindowExW(0x80, "STATIC", "hop-test-island", 0x80000000, 100, 10, 560, 280, None, None, None, None)
    isl.hwnd = hwnd
    api = host.SettingsApi(isl)
    page = host.build_web()
    pg = browser.new_page(viewport={"width": 1200, "height": 860})
    pg.expose_function("__hopcall", lambda name, args: getattr(api, name)(*args))
    pg.add_init_script(BRIDGE)
    pg.goto("file:///" + os.path.join(os.path.dirname(page), "settings.html").replace("\\", "/"))
    pg.wait_for_function("document.getElementById('status').textContent.includes('saved')", timeout=20000)
    frame = next(f for f in pg.frames if "preview" in f.url)
    frame.wait_for_function("document.querySelectorAll('.pg-board').length > 0", timeout=20000)
    yield pg, frame, isl
    pg.close()
    u32.DestroyWindow(ctypes.c_void_p(hwnd))


def saved():
    return host.clean_layout(host.read_config().get("layout"))


def push_layout(pg, L):
    pg.evaluate("L => document.getElementById('pv').contentWindow.postMessage({t:'cmd', fn:'Layout', args:[L]}, '*')", L)


def test_three_pages_of_widgets(board_app):
    pg, frame, _ = board_app
    assert frame.evaluate("window.__islandPageIds()") == ["board-0", "board-1", "board-2"]
    assert [c.text_content() for c in pg.locator("#chips .chip").all()] == ["Now", "Work", "Stuff"]
    tiles = frame.evaluate("[...document.querySelectorAll('.pg-board')].map(b => [...b.querySelectorAll('.tile')].map(t => t.dataset.w + ':' + [...t.classList].find(c => c.startsWith('sz-'))))")
    assert tiles == [["music:sz-b", "today:sz-w", "timer:sz-w"], ["agents:sz-b", "calendar:sz-b"], ["clips:sz-w", "alerts:sz-b", "pc:sz-w"]]
    # the player's own controls moved with it (island.js still finds them by id)
    assert frame.evaluate("!!document.querySelector('.tile #play') && !!document.querySelector('.tile #title')")


def test_resize_and_add_from_the_editor(board_app):
    pg, frame, _ = board_app
    pg.locator("#boardsEd").scroll_into_view_if_needed()
    pg.click("#boardsEd [data-b='0'][data-j='0'][data-ws='w']")          # Now playing: Big -> Wide
    frame.wait_for_function("document.querySelector('.tile[data-w=music]').classList.contains('sz-w')")
    assert saved()["boards"][0]["widgets"][0] == {"w": "music", "s": "w"}
    pg.select_option("#boardsEd select[data-wadd='0']", "notes")             # 2 cells free now: notes fits
    frame.wait_for_function("!!document.querySelector('.pg-board[data-id=\"board-0\"] .tile[data-w=notes]')")
    assert [w["w"] for w in saved()["boards"][0]["widgets"]] == ["music", "today", "timer", "notes"]


def test_no_room_means_no_change(board_app):
    pg, _, _ = board_app
    pg.locator("#boardsEd").scroll_into_view_if_needed()
    pg.click("#boardsEd [data-b='0'][data-j='1'][data-ws='b']")          # Today -> Big: the page is full
    pg.wait_for_timeout(300)
    assert saved()["boards"][0]["widgets"][1]["s"] == "w"


def test_classic_and_back(board_app):
    pg, frame, _ = board_app
    pg.click(".seg[data-k=pageMode] button[data-v=pages]")
    frame.wait_for_function("!document.querySelector('.pg-board')")
    assert frame.evaluate("document.querySelector('.pg-music > .wg-music') !== null")
    assert "music" in frame.evaluate("window.__islandPageIds()")
    pg.click(".seg[data-k=pageMode] button[data-v=boards]")
    frame.wait_for_function("document.querySelectorAll('.pg-board').length === 3")
    assert frame.evaluate("document.querySelector('.tile .wg-music') !== null")


CASES = [(w, s) for w, sizes in options.WIDGETS.items() for s in sizes]


@pytest.mark.parametrize("widget,size", CASES)
def test_every_widget_fits_its_tile(board_app, widget, size):
    """Nothing a widget shows pokes out of its tile, at any size it allows."""
    pg, frame, isl = board_app
    L = isl.set_layout({**isl.layout, "boards": [{"name": "T", "widgets": [{"w": widget, "s": size}]}]})
    push_layout(pg, L)
    frame.wait_for_function(f"!!document.querySelector('.tile[data-w={widget}].sz-{size}')")
    frame.evaluate("window.__islandSetPage(0)")
    frame.wait_for_timeout(450)
    out = frame.evaluate("""w => {
      const t = document.querySelector('.tile[data-w=' + w + ']'), r = t.getBoundingClientRect(), bad = [];
      for (const el of t.querySelectorAll('.wg *')) {
        const s = getComputedStyle(el);
        if (s.display === 'none' || s.visibility === 'hidden' || el.closest('.vol-row, .scrolls, .rows, .sh-items, .pr-view, .mq, svg')) continue;
        const e = el.getBoundingClientRect();
        if (!e.width || !e.height) continue;
        if (e.left < r.left - 1 || e.right > r.right + 1 || e.top < r.top - 1 || e.bottom > r.bottom + 1)
          bad.push((el.id || el.className || el.tagName) + ' ' + [e.left - r.left, r.right - e.right, e.top - r.top, r.bottom - e.bottom].map(Math.round));
      }
      return bad.slice(0, 5);
    }""", widget)
    assert out == [], f"{widget} at {size} overflows: {out}"


def test_long_command_stays_on_one_line(board_app):
    _, frame, _ = board_app
    frame.evaluate("""window.__hopEvent('agentAsk', {kind: 'permission', id: 'x', tool: 'claude', name: 'hop', verb: 'run',
                      summary: 'python -m pytest tests/test_layout.py -q --maxfail=1'})""")
    frame.wait_for_function("!!document.querySelector('.card .body.one')")
    frame.wait_for_timeout(600)
    b = frame.evaluate("(() => { const e = document.querySelector('.card .body.one'); return [e.scrollWidth, e.clientWidth, e.getClientRects().length]; })()")
    assert b[0] <= b[1] + 1, "the command was cut off"


def test_privacy_dot_has_room(board_app):
    _, frame, _ = board_app
    frame.evaluate("window.__islandHover(false)")
    frame.evaluate("window.__hopEvent('privacy', {mic: ['Discord'], cam: []})")
    frame.wait_for_function("document.getElementById('island').classList.contains('pdot-on')")
    frame.wait_for_timeout(3600)                                      # the 3 s "is using your microphone" pop-up ends
    r = frame.evaluate("""(() => {
      const d = document.querySelector('.pdot').getBoundingClientRect(), s = document.querySelector('.sl-r').getBoundingClientRect(),
            i = document.getElementById('island').getBoundingClientRect();
      return {gap: d.left - s.right, centred: Math.abs((i.left + i.right) / 2 - innerWidth / 2), mic: document.querySelector('.pdot').classList.contains('mic')};
    })()""")
    assert r["mic"] and r["gap"] >= 2 and r["centred"] < 1.5


def test_no_mic_text_on_the_pill(board_app):
    _, frame, _ = board_app
    frame.evaluate("window.__hopEvent('privacy', {mic: ['Discord'], cam: []})")
    frame.wait_for_timeout(1500)
    assert "Mic" not in frame.evaluate("document.querySelector('.live-text').textContent")
