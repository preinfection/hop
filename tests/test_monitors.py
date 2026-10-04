"""Several screens, without plugging any in: the screens are made up (their
work areas, as EnumDisplayMonitors reports them) and the island's window is
a real hidden Windows window that really moves. Covers the labels the snap
chooser shows, moving to a chosen screen, coming back to it after a restart,
a saved screen that's gone, and the fresh start after a screen change."""
import ctypes
import os

import pytest

import features
import host

u32 = ctypes.windll.user32
u32.CreateWindowExW.restype = ctypes.c_void_p


# ================================================================ labels (pure)
LAPTOP, LEFT, RIGHT, ABOVE = (0, 0, 1920, 1040), (-1920, 0, 0, 1040), (1920, 0, 3840, 1040), (0, -1080, 1920, -40)


@pytest.mark.parametrize("rects,current,want", [
    ([LAPTOP], 0, ["This monitor"]),
    ([LAPTOP, RIGHT], 0, ["This monitor", "Right monitor"]),
    ([LAPTOP, RIGHT], 1, ["Left monitor", "This monitor"]),
    ([LAPTOP, LEFT, RIGHT], 0, ["Left monitor", "This monitor", "Right monitor"]),       # the user's example
    ([RIGHT, LEFT, LAPTOP], 2, ["Left monitor", "This monitor", "Right monitor"]),       # any enumeration order
    ([LAPTOP, ABOVE], 0, ["Top monitor", "This monitor"]),
    ([LAPTOP, LEFT, (-3840, 0, -1920, 1040)], 0, ["Left monitor 2", "Left monitor", "This monitor"]),
    ([(0, 0, 2560, 1400), (2560, 300, 4480, 1340)], 0, ["This monitor", "Right monitor"]),   # different sizes, offset
])
def test_labels_follow_where_screens_sit(rects, current, want):
    got = features.label_monitors(rects, current)
    assert [g["label"] for g in got] == want
    assert sorted(g["index"] for g in got) == list(range(len(rects)))


# ================================================================ a real window on made-up screens
@pytest.fixture()
def isl(monkeypatch):
    if os.path.exists(host.CONFIG):
        os.remove(host.CONFIG)
    i = host.Island()
    hwnd = u32.CreateWindowExW(0x80, "STATIC", "hop-test-island", 0x80000000, 200, 0, 640, 282, None, None, None, None)
    i.hwnd = hwnd
    screens = [{"index": 0, "name": "A", "primary": True, "work": LAPTOP, "handle": 11},
               {"index": 1, "name": "B", "primary": False, "work": RIGHT, "handle": 22}]
    monkeypatch.setattr(features, "monitors", lambda: screens)
    monkeypatch.setattr(host, "ui_thread", lambda w, fn: fn())          # no UI thread here: run it now
    monkeypatch.setattr(i, "reflow", lambda: None)
    i._screens = screens
    yield i
    u32.DestroyWindow(ctypes.c_void_p(hwnd))


def test_one_screen_snaps_at_once(isl, monkeypatch):
    isl._screens[:] = isl._screens[:1]
    assert isl.recenter() is True


def test_two_screens_ask_first(isl, monkeypatch):
    monkeypatch.setattr(u32, "MonitorFromWindow", lambda *a: 11)
    r = isl.recenter()
    assert r == {"choose": [{"index": 0, "label": "This monitor"}, {"index": 1, "label": "Right monitor"}]}


def test_moves_to_the_chosen_screen_and_remembers_it(isl, monkeypatch):
    monkeypatch.setattr(isl, "work_area", lambda: RIGHT)                # once there, "its" screen is the right one
    assert isl.snap_to(1)
    x, y, w, h = isl.rect()
    assert RIGHT[0] <= x and x + w <= RIGHT[2]
    assert abs((x + w / 2) - (RIGHT[0] + RIGHT[2]) / 2) <= 1          # top middle of that screen
    pos = host.read_config()["windowPosition"]
    assert RIGHT[0] <= pos["cx"] <= RIGHT[2]                           # a fresh start comes back to it
    # ...and the fresh start does put it there, even if the window opens on the left screen
    monkeypatch.setattr(isl, "work_area", lambda: LAPTOP)
    isl.cfg = host.read_config()
    isl.place_initial()
    x2, _, w2, _ = isl.rect()
    assert RIGHT[0] <= x2 and x2 + w2 <= RIGHT[2]


def test_a_screen_that_is_gone_is_not_used(isl, monkeypatch):
    isl.cfg["windowPosition"] = {"cx": 2880, "y": 0}                   # saved on the right screen...
    isl._screens[:] = isl._screens[:1]                                 # ...which was unplugged
    monkeypatch.setattr(isl, "work_area", lambda: LAPTOP)
    isl.place_initial()
    x, _, w, _ = isl.rect()
    assert LAPTOP[0] <= x and x + w <= LAPTOP[2]                       # pulled onto the screen that's there
    assert isl.snap_to(1) is False                                     # and it can't be picked any more


def test_screen_change_restarts_once_settled(isl, monkeypatch):
    """A new scale (or a screen added / removed) starts the island fresh
    2.5 s later; moving between same-scale screens doesn't."""
    started = []
    monkeypatch.setattr(isl, "restart_app", lambda: started.append(1))
    isl.screen_changed((96, 11, LAPTOP), None, now=0)                 # first look: remembers 2 screens
    assert not isl.screen_changed((96, 22, RIGHT), (96, 11, LAPTOP), now=1)       # same scale, same screens
    assert not isl.restart_if_settled(now=10)
    assert isl.screen_changed((120, 11, LAPTOP), (96, 22, RIGHT), now=20)         # 100 % -> 125 %
    assert not isl.restart_if_settled(now=21.5)                       # still settling
    import time as _t
    assert isl.restart_if_settled(now=23)
    _t.sleep(0.1)
    assert started == [1]
    isl._screens[:] = isl._screens[:1]                                # the HDMI is unplugged (same scale)
    assert isl.screen_changed((120, 11, LAPTOP), (120, 11, LAPTOP + (1,)), now=30)
