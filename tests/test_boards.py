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
    assert frame.evaluate("window.__islandPageIds()") == ["board-0", "board-1", "board-2", "board-3"]
    assert [c.text_content() for c in pg.locator("#chips .chip").all()] == ["Home", "Work", "Day", "Clips"]
    assert frame.evaluate("document.querySelectorAll('#tabs .tab').length") == 4          # a tab per page on top
    tiles = frame.evaluate("[...document.querySelectorAll('.pg-board')].map(b => [...b.querySelectorAll('.tile')].map(t => t.dataset.w + ':' + [...t.classList].find(c => c.startsWith('sz-'))))")
    assert tiles == [["music:sz-b", "weather:sz-t", "timer:sz-t"], ["agents:sz-b", "calendar:sz-b"],
                     ["today:sz-t", "battery:sz-t", "alerts:sz-b"], ["clips:sz-w", "pc:sz-w", "notes:sz-f"]]
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
    assert [w["w"] for w in saved()["boards"][0]["widgets"]] == ["music", "weather", "timer", "notes"]


def test_no_room_means_no_change(board_app):
    pg, _, _ = board_app
    pg.locator("#boardsEd").scroll_into_view_if_needed()
    btn = pg.locator("#boardsEd [data-b='0'][data-j='1'][data-ws='w']")   # Weather -> Wide: the page is full
    assert btn.is_disabled() and btn.get_attribute("title") == "No room on this page"
    assert saved()["boards"][0]["widgets"][1]["s"] == "t"


def test_classic_and_back(board_app):
    pg, frame, _ = board_app
    pg.click(".seg[data-k=pageMode] button[data-v=pages]")
    frame.wait_for_function("!document.querySelector('.pg-board')")
    assert frame.evaluate("document.querySelector('.pg-music > .wg-music') !== null")
    assert "music" in frame.evaluate("window.__islandPageIds()")
    pg.click(".seg[data-k=pageMode] button[data-v=boards]")
    frame.wait_for_function("document.querySelectorAll('.pg-board').length === 4")
    assert frame.evaluate("document.querySelector('.tile .wg-music') !== null")


CASES = [(w, s) for w, sizes in options.WIDGETS.items() for s in sizes]

FILL = r"""(() => {
  const now = Date.now();
  window.__hopEvent('agents', {sessions: [
      {id: 'a', tool: 'claude', name: 'hop', status: 'work', detail: 'Editing island/ui/features.js'},
      {id: 'b', tool: 'codex', name: 'mutate', status: 'ask', detail: 'Wants to run npm test'}],
    usage: {five: 42, week: 18, fiveReset: '2h 14m', weekReset: '3d 4h'}});
  window.__hopEvent('calendar', [
    {uid: '1', title: 'Design review: Hop 0.1.3 with the whole team', start: now + 3.6e6, end: now + 5e6, location: 'Google Meet', link: 'https://meet.google.com/abc-defg-hij'},
    {uid: '2', title: 'Gym', start: now + 9e6, end: now + 1e7, location: ''},
    {uid: '3', title: 'Dinner', start: now + 2e7, end: now + 2.2e7, location: 'Home'}]);
  window.__hopEvent('sports', [{id: 'm1', league: 'EPL', home: 'Arsenal', away: 'Chelsea', hs: '2', as: '1', status: "67'", live: true, state: 'in'},
                               {id: 'm2', league: 'EPL', home: 'Brighton & Hove Albion', away: 'Wolverhampton', hs: '0', as: '0', status: '3:00 PM', live: false, state: 'pre'}]);
  window.__hopEvent('shelf', [{name: 'design-notes-final-v2.pdf', path: 'C:/x/a.pdf', pinned: true}, {name: 'logo.png', path: 'C:/x/b.png'},
                              {name: 'trip.zip', path: 'C:/x/c.zip'}, {name: 'clip.mp4', path: 'C:/x/d.mp4'}]);
  window.__hopEvent('battery', {pct: 64, charging: false, minutes: 192, health: 56, design: 40466, full: 22478, cycles: 312,
                                drainers: [{name: 'RobloxPlayerBeta', cpu: 21.4}, {name: 'Brave', cpu: 6.2}, {name: 'Spotify', cpu: 1.1}]});
  for (const n of [['Discord', 'preinfection', 'yo did you push the notch build? the clip from last night is crazy'],
                   ['Outlook', 'Porkbun', 'gethop.lol renews on 2027-09-30'], ['Teams', 'Standup', 'Starting in 5 minutes']])
    window.__hopPopup('notif', '<div class=ct>x</div>', 200, 60, null, {history: {app: n[0], title: n[1], text: n[2]}});
  document.getElementById('notes') && (document.getElementById('notes').textContent = 'Ideas for 0.1.4:\n- per-game clip folders\n- record mic as its own track\n- a much longer line that has to wrap somewhere in the tile because it is long');
})()"""


@pytest.fixture()
def clips_for(board_app, sandbox):
    """Three real clips in the clips folder, so the Clips widget has pictures."""
    import subprocess
    import extras
    d = os.path.join(sandbox, "board-clips")
    os.makedirs(d, exist_ok=True)
    for i, secs in enumerate((15, 30, 60)):
        out = os.path.join(d, f"clip 2026-01-0{i + 1} 10-00-00 ({secs}s).mp4")
        if not os.path.exists(out):
            subprocess.run([extras.FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=15:d=1",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", out], check=True)
    board_app[2].set_clipper({"saveDir": d})


@pytest.mark.parametrize("widget,size", CASES)
def test_every_widget_fits_its_tile(board_app, clips_for, widget, size):
    """Nothing a widget shows pokes out of its tile, at any size it allows,
    WITH content in it (agents, events, scores, files, notes, clips...)."""
    pg, frame, isl = board_app
    L = isl.set_layout({**isl.layout, "boards": [{"name": "T", "widgets": [{"w": widget, "s": size}]}]})
    push_layout(pg, L)
    frame.evaluate(FILL)
    frame.evaluate("window.__islandHover && document.querySelector('.card') && (document.getElementById('island').classList.remove('carding'))")
    frame.wait_for_function(f"!!document.querySelector('.tile[data-w={widget}].sz-{size}')")
    frame.evaluate("window.__islandSetPage(0)")
    frame.wait_for_timeout(450)
    out = frame.evaluate("""w => {
      const t = document.querySelector('.tile[data-w=' + w + ']'), r = t.getBoundingClientRect(), bad = [];
      for (const el of t.querySelectorAll('.wg *')) {
        const s = getComputedStyle(el);
        if (s.display === 'none' || s.visibility === 'hidden' || el.closest('.vol-row, .pr-view, .mq, svg')) continue;
        const sc = el.parentElement && el.parentElement.closest('.rows, .scrolls');
        if (sc && sc !== el && sc.scrollHeight > sc.clientHeight + 1 && getComputedStyle(sc).overflowY !== 'visible')
          continue;                                       // clipped by a list that scrolls: the list's own box is what's checked
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
