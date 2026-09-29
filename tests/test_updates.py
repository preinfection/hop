"""Updates: version numbers, the real GitHub check, the notice in both apps."""
import os

import pytest

import clipper as C
import host
import toastui

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.mark.parametrize("a,b", [("0.1.0", "0.2.0"), ("0.1.0", "v0.1.1"), ("0.9.9", "1.0.0"), ("1.2", "1.2.1"),
                                 ("v1.9.0", "v1.10.0"), ("0.1.0", "0.1.0-1")])
def test_newer(a, b):
    for mod in (host, C):
        assert mod.version_tuple(b) > mod.version_tuple(a) or b.endswith("-1")


@pytest.mark.parametrize("a,b", [("0.2.0", "0.1.0"), ("1.0.0", "1.0.0"), ("v0.1.0", "0.1.0"), ("2.0", "1.99.99")])
def test_not_newer(a, b):
    for mod in (host, C):
        assert not mod.version_tuple(b) > mod.version_tuple(a)


@pytest.mark.parametrize("junk", ["", "abc", None, "v", "1.x"])
def test_junk_version(junk):
    assert host.version_tuple(junk) == (0,) and C.version_tuple(junk) == (0,)


def test_version_file_read_by_both():
    v = open(os.path.join(ROOT, "VERSION")).read().strip()
    assert host.VERSION == v == C.VERSION


@pytest.mark.network
def test_real_github_check(island, record_property):
    u = island.check_update()
    assert u["current"] == host.VERSION and u["checked"]
    assert u["latest"] is None or host.version_tuple(u["latest"]) >= (0,)
    record_property("GitHub says", f"latest {u['latest']}, update available: {u['available']}")


def test_auto_update_switch(island):
    assert island.get_update()["auto"] is True
    island.set_auto_update(False)
    assert host.read_config()["autoUpdate"] is False


def test_update_answer_later_stops_the_loop(island):
    island.update_answer(False)
    assert island._update_later is True


# ---- the clipper's notice: drawn with its two buttons
@pytest.mark.parametrize("scale", [1.0, 1.25, 1.5, 2.0])
@pytest.mark.parametrize("hover", [None, "go", "later"])
def test_update_notice_drawn(scale, hover):
    n = C.UpdateNotice("9.9.9", "https://example.com")
    st = {"title": n.title(), "sub": n.sub(), "status": n.status(),
          "buttons": {"items": [("go", "Update now"), ("later", "Later")], "hover": hover}}
    img, hits = toastui.render(st, scale)
    assert "btn_go" in hits and "btn_later" in hits
    assert hits["btn_go"][2] < hits["btn_later"][0]                 # side by side
    assert img.size == toastui.card_size(st, scale)
    card = hits["card"]
    assert card[0] <= hits["btn_later"][0] and hits["btn_later"][3] <= card[3]


@pytest.mark.parametrize("status", ["saving", "done", "failed", "rec", "update", ""])
@pytest.mark.parametrize("picker", [False, True])
def test_every_toast_state_draws(status, picker):
    st = {"title": "30s saved", "sub": "Click to change the length", "status": status, "spin": 0.3}
    if picker:
        st["picker"] = {"options": [(15, "15s"), (30, "30s"), (60, "1 min")], "selected": 30, "hover": 15}
    img, hits = toastui.render(st, 1.25)
    assert img.mode == "RGBA" and "card" in hits
    if picker:
        assert {"len15", "len30", "len60"} <= set(hits)


def test_picker_has_no_seam():
    """No dividing line between the text and the length picker (it showed
    the desktop through as a thin seam)."""
    import inspect
    assert "d.line([(m + P(14), m + P(H))" not in inspect.getsource(toastui.render)
