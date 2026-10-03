"""The island host's own API (what the settings app and the installer use),
run for real: config files in the sandbox, real city search, real uploads."""
import json
import os
import subprocess
import time

import pytest

import extras
import host


# ================================================================ config files
def test_config_round_trip(island):
    island.cfg["startAtLogin"] = False
    host.write_config(island.cfg)
    assert host.read_config()["startAtLogin"] is False


@pytest.mark.parametrize("raw", ["", "{", "[1,2]", "null"])
def test_broken_config_gives_defaults(raw):
    os.makedirs(os.path.dirname(host.CONFIG), exist_ok=True)
    open(host.CONFIG, "w").write(raw)
    cfg = host.read_config()
    assert cfg["lyricOffsetMs"] == host.DEFAULTS["lyricOffsetMs"]


def test_layout_saved_and_read(island):
    L = island.set_layout({"musicLeft": "art", "hidden": ["pc"], "scale": 1.2})
    assert L["musicLeft"] == "art" and L["hidden"] == ["pc"] and L["scale"] == 1.2
    assert host.read_config()["layout"]["musicLeft"] == "art"
    assert host.Island().layout["musicLeft"] == "art"          # a restart keeps it


def test_reset_layout_keeps_size(island):
    island.set_layout({"musicLeft": "none", "scale": 1.3})
    L = island.reset_layout()
    assert L["musicLeft"] == "rec" and L["scale"] == 1.3


# ================================================================ installer handoff
def write_installer(d):
    path = os.path.join(os.path.dirname(host.CONFIG), "installer-settings.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(d, open(path, "w"))
    return path


@pytest.mark.parametrize("scale", [0.85, 1.0, 1.2])
@pytest.mark.parametrize("left", ["rec", "art", "none"])
@pytest.mark.parametrize("right", ["prayer", "bars", "clock", "none"])
def test_installer_layout(scale, left, right, host=host):
    if os.path.exists(host.CONFIG):
        os.remove(host.CONFIG)
    path = write_installer({"layout": {"scale": scale, "musicLeft": left, "musicRight": right}})
    isl = host.Island()
    assert (isl.layout["scale"], isl.layout["musicLeft"], isl.layout["musicRight"]) == (scale, left, right)
    assert not os.path.exists(path)                             # taken once, then gone


@pytest.mark.parametrize("method", [1, 2, 3, 4, 5, 13, 15, 16])
@pytest.mark.parametrize("school", [0, 1])
def test_installer_prayer_method(method, school):
    if os.path.exists(host.CONFIG):
        os.remove(host.CONFIG)
    write_installer({"prayerMethod": method, "asrSchool": school, "city": "Istanbul"})
    isl = host.Island()
    assert isl.cfg["prayerMethod"] == method and isl.cfg["asrSchool"] == school
    assert isl.cfg["pendingCity"] == "Istanbul"


def test_installer_empty_city_not_pending():
    if os.path.exists(host.CONFIG):
        os.remove(host.CONFIG)
    write_installer({"city": "   "})
    assert "pendingCity" not in host.Island().cfg


def test_installer_file_broken_is_ignored():
    path = os.path.join(os.path.dirname(host.CONFIG), "installer-settings.json")
    open(path, "w").write("{nope")
    host.Island()


# ================================================================ city + prayer times
@pytest.mark.network
@pytest.mark.parametrize("q,country", [("London", "United Kingdom"), ("Makkah", "Saudi Arabia"), ("Istanbul", "Türkiye"),
                                       ("Cairo", "Egypt"), ("Toronto", "Canada"), ("Jakarta", "Indonesia"),
                                       ("Karachi", "Pakistan"), ("Paris", "France")])
def test_real_city_search(island, q, country, record_property):
    got = island.search_city(q)
    assert got, "no result"
    assert any(country in r["label"] for r in got)
    assert all(-90 <= r["lat"] <= 90 and -180 <= r["lon"] <= 180 for r in got)
    record_property("first match", got[0]["label"])


@pytest.mark.parametrize("q", ["", " ", "a"])
def test_city_search_too_short(island, q):
    assert island.search_city(q) == []


@pytest.mark.network
def test_city_search_nonsense(island):
    assert island.search_city("zzqqxxwwvv") == []


@pytest.mark.network
def test_set_location_gives_times_at_once(island, record_property):
    got = island.search_city("Istanbul")[0]
    loc = island.set_location(got, 13, 0)
    assert loc["location"]["label"] == got["label"] and loc["method"] == 13
    t = island.get_prayers()["today"]
    assert t and len(t) == 6
    record_property("Istanbul today", " ".join(f"{k} {v}" for k, v in t.items()))


@pytest.mark.network
def test_first_city_from_installer(island):
    island.cfg["pendingCity"] = "Cairo"
    island.cfg.pop("location", None)
    island.first_city()
    assert "Cairo" in island.cfg["location"]["label"] and "pendingCity" not in island.cfg


def test_clear_location(island):
    island.set_location({}, None, None)
    assert island.get_location()["location"] is None
    assert island.get_prayers()["today"] is None


# ================================================================ Hop Clipper settings, from the island
@pytest.mark.parametrize("patch", [{"fps": 120}, {"fps": 30}, {"quality": "best"}, {"quality": "small"},
                                   {"watermark": False}, {"cursor": False}, {"islandInClips": False},
                                   {"toastInClips": True}, {"defaultSeconds": 15}, {"defaultSeconds": 60},
                                   {"sounds": False}])
def test_clipper_settings_saved(island, patch):
    st = island.set_clipper(patch)
    for k, v in patch.items():
        assert st["settings"][k] == v
        assert host.clipper_settings()[k] == v


@pytest.mark.parametrize("patch", [{"fps": "60"}, {"watermark": "no"}, {"hacker": 1}, {"quality": 5}])
def test_clipper_settings_bad_types_ignored(island, patch):
    before = host.clipper_settings()
    island.set_clipper(patch)
    assert host.clipper_settings() == before


def test_clips_folder(island, sandbox):
    assert host.clips_dir() == host.DEFAULT_CLIPS
    d = os.path.join(sandbox, "Clips here")
    island.set_clipper({"saveDir": d})
    assert host.clips_dir() == d and island.get_clipper()["folder"] == d and extras.CLIPS == d


def test_island_in_screenshots_by_default():
    assert host.CLIPPER_DEFAULTS["islandInClips"] is True


def test_clipper_found_from_source():
    cmd = host.clipper_command()
    assert cmd and cmd[-1].endswith("clipper.py") and os.path.exists(cmd[-1])


# ================================================================ clips page, with real clips
@pytest.mark.slow
def test_recent_clips_and_thumbnails(island, sandbox):
    d = os.path.join(sandbox, "clips-page")
    os.makedirs(d, exist_ok=True)
    for i, secs in enumerate((15, 30)):
        out = os.path.join(d, f"clip 2026-01-0{i + 1} 10-00-00 ({secs}s).mp4")
        subprocess.run([extras.FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=2",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", out], check=True)
        time.sleep(0.05)
    island.set_clipper({"saveDir": d})
    clips = island.get_clips()
    assert [c["seconds"] for c in clips] == [30, 15]               # newest first, length from the name
    for c in clips:
        # the picture travels as data: it shows even if thumbs.island was never mapped (a cold boot)
        assert c["url"].startswith("https://clips.island/") and c["thumb"].startswith("data:image/jpeg;base64,")
        assert len(c["thumb"]) > 1300
    assert len(os.listdir(extras.THUMBS)) >= 2                    # still cached on disk, made once


# ================================================================ drop to upload: the real anonymous host
@pytest.mark.network
def test_real_anonymous_upload(sandbox, record_property):
    from PIL import Image
    p = os.path.join(sandbox, "upload.png")
    Image.new("RGB", (12, 12), (10, 132, 255)).save(p)
    if os.path.exists(extras.KEY_FILE):
        os.remove(extras.KEY_FILE)
    try:
        link = extras.upload(p)
    except RuntimeError as e:
        if "Too many" in str(e) or "429" in str(e):
            pytest.skip("the anonymous host's hourly limit was reached by earlier runs")
        raise
    assert link.startswith("https://mutate.lol/i/")
    import urllib.request
    req = urllib.request.Request(link, headers=extras.UA)
    page = urllib.request.urlopen(req, timeout=20).read().decode()
    assert "by Anonymous" in page
    record_property("link", link)


@pytest.mark.parametrize("raw", ["[]", "null", "5", '"text"'])
def test_installer_file_not_an_object(raw):
    path = os.path.join(os.path.dirname(host.CONFIG), "installer-settings.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").write(raw)
    host.Island()                                   # no exception, file consumed
    assert not os.path.exists(path)


@pytest.mark.parametrize("raw", ["[]", "null", "{", ""])
def test_clipper_settings_damaged(raw):
    os.makedirs(os.path.dirname(host.CLIPPER_SETTINGS), exist_ok=True)
    open(host.CLIPPER_SETTINGS, "w").write(raw)
    assert host.clipper_settings() == host.CLIPPER_DEFAULTS


# ================================================================ style: pill / notch
def _hidden_window(isl):
    """A real (hidden) popup window for the island, like the UI tests use."""
    import ctypes
    u32 = ctypes.windll.user32
    u32.CreateWindowExW.restype = ctypes.c_void_p
    isl.hwnd = u32.CreateWindowExW(0x80, "STATIC", "hop-test-style", 0x80000000, 300, 300, 360, 196,
                                   None, None, None, None)
    return lambda: u32.DestroyWindow(ctypes.c_void_p(isl.hwnd))


@pytest.mark.parametrize("style,size,gap", [("pill", host.COMPACT, 10), ("notch", host.NOTCH, 0)])
def test_style_size_and_gap(island, style, size, gap):
    island.set_layout({"style": style})
    assert island.compact() == size and island.top_gap() == gap


@pytest.mark.parametrize("style,gap", [("pill", 10), ("notch", 0)])
def test_recenter_uses_the_style_gap(island, style, gap):
    """Snap to top middle: the notch lands ON the top edge, the pill 10px below."""
    island.set_layout({"style": style})
    close = _hidden_window(island)
    try:
        island.recenter()
        l, t, r, _ = island.work_area()
        x, y, w, _ = island.rect()
        assert abs(y - (t + gap * island.scale())) <= 1
        assert abs((x + w / 2) - (l + r) / 2) <= 1
    finally:
        close()


def test_switching_to_notch_moves_it_to_the_edge_and_resizes_the_pill(island):
    close = _hidden_window(island)
    try:
        island.recenter()                                   # a pill, 10px down
        island.set_layout({"style": "notch"})
        island._apply_style()
        _, t, _, _ = island.work_area()
        _, y, _, _ = island.rect()
        assert abs(y - t) <= 1
        assert island.pill_w == host.NOTCH[0]
        assert host.read_config()["windowPosition"]["y"] == y
        island.set_layout({"style": "pill"})
        island._apply_style()
        _, y, _, _ = island.rect()
        assert abs(y - (t + 10 * island.scale())) <= 1 and island.pill_w == host.COMPACT[0]
    finally:
        close()


@pytest.mark.parametrize("style,minimum", [("pill", host.COMPACT[0]), ("notch", host.NOTCH[0])])
def test_pill_width_never_below_the_style(island, style, minimum):
    island.set_layout({"style": style})
    island.set_pill_width(50)
    assert island.pill_w == minimum
