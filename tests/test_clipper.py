"""Hop Clipper: its settings, and REAL recordings of this PC's screen with every
combination of frame rate, quality, watermark and cursor, checked with ffprobe.
Then a real snapshot + cut into a clip, for every clip length."""
import itertools
import json
import os
import subprocess
import threading
import time

import pytest

import clipper as C


def write_settings(**kw):
    os.makedirs(os.path.dirname(C.SETTINGS_FILE), exist_ok=True)
    with open(C.SETTINGS_FILE, "w", encoding="utf-8") as fh:
        json.dump(kw, fh)


@pytest.fixture(autouse=True)
def fresh_settings(sandbox, monkeypatch):
    # the ring and snapshots in the sandbox, never the live clipper's
    monkeypatch.setattr(C, "RING", os.path.join(sandbox, "ring"))
    monkeypatch.setattr(C, "HOLD", os.path.join(sandbox, "hold"))
    if os.path.exists(C.SETTINGS_FILE):
        os.remove(C.SETTINGS_FILE)
    yield


def probe(path, *entries):
    r = subprocess.run([C.FFPROBE, "-v", "error", "-show_entries", ":".join(entries), "-of", "json", path],
                       capture_output=True, text=True, creationflags=C.NO_WINDOW)
    return json.loads(r.stdout or "{}")


# ================================================================ settings()
def test_defaults_when_no_file():
    s = C.settings()
    assert s["fps"] == (30 if C.WEAK_PC else 60)
    assert s["quality"] == "high" and s["defaultSeconds"] == 30 and s["watermark"] is True
    assert s["saveDir"] == C.DEFAULT_SAVE_DIR


@pytest.mark.parametrize("fps", [30, 60, 120])
def test_fps_kept(fps):
    write_settings(fps=fps)
    assert C.settings()["fps"] == fps


@pytest.mark.parametrize("fps", [0, 15, 59, 144, 240, -60, "60", None, 60.0])
def test_fps_rejected(fps):
    write_settings(fps=fps)
    assert C.settings()["fps"] in (30, 60)


@pytest.mark.parametrize("q", ["best", "high", "small"])
def test_quality_kept(q):
    write_settings(quality=q)
    assert C.settings()["quality"] == q
    assert C.CRF[q] in (18, 22, 27)


@pytest.mark.parametrize("q", ["ultra", "", "HIGH", 22, None])
def test_quality_rejected(q):
    write_settings(quality=q)
    assert C.settings()["quality"] == "high"


@pytest.mark.parametrize("n", [15, 30, 60])
def test_length_kept(n):
    write_settings(defaultSeconds=n)
    assert C.settings()["defaultSeconds"] == n


@pytest.mark.parametrize("n", [0, 10, 45, 120, "30", None])
def test_length_rejected(n):
    write_settings(defaultSeconds=n)
    assert C.settings()["defaultSeconds"] == 30


@pytest.mark.parametrize("key", ["watermark", "cursor", "toastInClips", "islandInClips", "sounds"])
@pytest.mark.parametrize("value", [True, False])
def test_switches(key, value):
    write_settings(**{key: value})
    assert C.settings()[key] is value


@pytest.mark.parametrize("key", ["watermark", "cursor", "toastInClips", "islandInClips", "sounds"])
@pytest.mark.parametrize("junk", ["yes", 1, 0, None])
def test_switch_junk(key, junk):
    write_settings(**{key: junk})
    assert C.settings()[key] is C.SETTINGS_DEFAULTS[key]


@pytest.mark.parametrize("given", ["", "   "])
def test_empty_folder_is_default(given):
    write_settings(saveDir=given)
    assert C.settings()["saveDir"] == C.DEFAULT_SAVE_DIR


def test_custom_folder(sandbox):
    d = os.path.join(sandbox, "my clips")
    write_settings(saveDir=d)
    assert C.settings()["saveDir"] == d


@pytest.mark.parametrize("raw", ["{", "[]", "null", '"text"', ""])
def test_broken_file(raw):
    os.makedirs(os.path.dirname(C.SETTINGS_FILE), exist_ok=True)
    open(C.SETTINGS_FILE, "w").write(raw)
    assert C.settings()["quality"] == "high"


@pytest.mark.slow
def test_clean_stop_finishes_the_last_piece():
    """Stopping the recorder (screen off, settings change, restart) must leave
    every piece whole: the last one used to be cut off mid-frame."""
    write_settings(fps=30, quality="small")
    ring = record(5.0)
    for f in sorted(os.listdir(ring)):
        r = subprocess.run([C.FFMPEG, "-v", "error", "-i", os.path.join(ring, f), "-f", "null", "-"],
                           capture_output=True, text=True)
        assert r.stderr.strip() == "", f


@pytest.mark.slow
def test_clip_across_two_recorder_runs(sandbox, monkeypatch):
    """A clip saved right after a restart joins two runs, and plays clean."""
    write_settings(fps=30, quality="small")
    monkeypatch.setattr(C, "SAVE_DIR", os.path.join(sandbox, "clips2"))
    record(4.5)
    record(4.5)
    out = C.cut(C.snapshot(), 15, "two-runs")
    r = subprocess.run([C.FFMPEG, "-v", "error", "-i", out, "-f", "null", "-"], capture_output=True, text=True)
    assert r.stderr.strip() == ""


def test_save_dir_follows_settings(sandbox):
    d = os.path.join(sandbox, "moved")
    write_settings(saveDir=d)
    C.apply_save_dir()
    assert C.SAVE_DIR == d and C.REC_TMP == os.path.join(d, ".recording")


# ================================================================ tools
def test_ffmpeg_found():
    assert os.path.exists(C.FFMPEG) and os.path.exists(C.FFPROBE)


@pytest.mark.parametrize("what", ["gfxcapture", "hwdownload", "overlay", "setparams", "scale", "fps"])
def test_ffmpeg_has_filter(what):
    out = subprocess.run([C.FFMPEG, "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    assert f" {what} " in out


@pytest.mark.parametrize("what", ["libx264", "aac"])
def test_ffmpeg_has_encoder(what):
    out = subprocess.run([C.FFMPEG, "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    assert f" {what} " in out


@pytest.mark.parametrize("name", ["watermark.png", "click.wav", "bunny.png", "bunny.ico"])
def test_assets_present(name):
    assert os.path.exists(os.path.join(C.HERE, name))


# ================================================================ REAL recordings
HEARTBEAT = r"""
import ctypes, time, ctypes.wintypes as wt
u = ctypes.windll.user32
u.CreateWindowExW.restype = wt.HWND
# NEVER takes focus: no-activate, click-through, tool window (not in the taskbar)
EX = 0x08000000 | 0x00000020 | 0x00000080 | 0x00080000 | 0x00000008   # NOACTIVATE|TRANSPARENT|TOOLWINDOW|LAYERED|TOPMOST
h = u.CreateWindowExW(EX, "STATIC", "hop-test-heartbeat", 0x80000000, 0, 0, 4, 4, None, None, None, None)
u.ShowWindow(h, 4)                                     # SW_SHOWNOACTIVATE
end = time.time() + %f
a = 1
while time.time() < end:
    a = 3 - a                                          # alpha 1 <-> 2: invisible, but the screen recomposes
    u.SetLayeredWindowAttributes(h, 0, a, 2)
    msg = wt.MSG()
    while u.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
        u.DispatchMessageW(ctypes.byref(msg))
    time.sleep(0.016)
u.DestroyWindow(h)
"""


def record(seconds=5.0):
    """Run the real recorder on this PC's screen for a few seconds, feeding it
    real silence as the audio stream, and return the ring folder. Windows
    only hands over frames when something on screen changes, so (like the
    clipper's own heartbeat) a 4-pixel window in the corner flickers meanwhile."""
    import sys
    beat = subprocess.Popen([sys.executable, "-c", HEARTBEAT % (seconds + 2)])
    ring = C.new_ring_dir()
    t0 = time.time()
    ff = C.start_ffmpeg(t0, ring, None)
    stop = threading.Event()

    def feed():
        block = b"\0" * (C.BLOCK * C.CH * 4)
        n = 0
        while not stop.is_set():
            try:
                ff.stdin.write(block)
            except OSError:
                return
            n += 1
            time.sleep(max(0, t0 + n * C.BLOCK / C.RATE - time.time()))
    th = threading.Thread(target=feed, daemon=True)
    th.start()
    time.sleep(seconds)
    stop.set()
    C.stop_ffmpeg(ff)                                # the app's own clean stop
    beat.kill()
    return ring


COMBOS = list(itertools.product([30, 60, 120], ["best", "high", "small"], [True, False], [True, False]))


@pytest.mark.slow
@pytest.mark.parametrize("fps,quality,watermark,cursor", COMBOS)
def test_real_recording(fps, quality, watermark, cursor, record_property):
    write_settings(fps=fps, quality=quality, watermark=watermark, cursor=cursor)
    ring = record(5.0)
    pieces = sorted(f for f in os.listdir(ring) if f.endswith(".ts"))
    assert pieces, "the recorder wrote nothing"
    first = os.path.join(ring, pieces[0])
    info = probe(first, "stream=codec_type,codec_name,avg_frame_rate,width,height,color_transfer", "format=duration")
    kinds = {s["codec_type"]: s for s in info["streams"]}
    assert kinds["video"]["codec_name"] == "h264" and kinds["audio"]["codec_name"] == "aac"
    num, den = map(int, kinds["video"]["avg_frame_rate"].split("/"))
    assert abs(num / den - fps) < 1
    assert kinds["video"]["color_transfer"] == "bt709"
    assert 1.5 <= float(info["format"]["duration"]) <= 2.6          # 2 s pieces
    record_property("piece", f"{kinds['video']['width']}x{kinds['video']['height']} @ {num / den:.0f} fps, "
                             f"{os.path.getsize(first) // 1024} KB for {float(info['format']['duration']):.2f} s")


@pytest.mark.slow
@pytest.mark.parametrize("seconds", [15, 30, 60])
def test_real_snapshot_and_cut(seconds, sandbox, monkeypatch):
    """A real clip: record, snapshot the ring, cut the last N seconds to mp4.
    (The ring holds only what was recorded, so the clip is as long as that.)"""
    write_settings(fps=30, quality="small")
    monkeypatch.setattr(C, "SAVE_DIR", os.path.join(sandbox, "clips"))
    record(7.0)
    snap = C.snapshot()
    assert snap and os.path.exists(os.path.join(snap, "all.ts"))
    out = C.cut(snap, seconds, f"test-{seconds}")
    assert out and os.path.exists(out)
    info = probe(out, "stream=codec_type", "format=duration")
    assert {s["codec_type"] for s in info["streams"]} == {"video", "audio"}
    assert float(info["format"]["duration"]) > 1.0
    # it decodes cleanly from start to end
    r = subprocess.run([C.FFMPEG, "-v", "error", "-i", out, "-f", "null", "-"], capture_output=True, text=True)
    assert r.stderr.strip() == ""


@pytest.mark.slow
def test_ffmpeg_dies_with_the_clipper(sandbox):
    """If the clipper process dies, Windows kills its ffmpeg too (a leftover
    one kept capturing and grew to 6 GB)."""
    import sys
    code = ("import sys, time; sys.path.insert(0, r'%s'); import clipper as C; "
            "C.RING = r'%s'; ff = C.start_ffmpeg(time.time(), C.new_ring_dir(), None); "
            "print(ff.pid, flush=True); time.sleep(60)") % (os.path.join(os.path.dirname(C.__file__)),
                                                           os.path.join(sandbox, "orphan-ring"))
    p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True, env=os.environ)
    ff_pid = int(p.stdout.readline())
    import psutil
    assert psutil.pid_exists(ff_pid)
    p.kill()                                       # the clipper dies without cleaning up
    p.wait(10)
    for _ in range(20):
        if not psutil.pid_exists(ff_pid):
            break
        time.sleep(0.25)
    assert not psutil.pid_exists(ff_pid), "ffmpeg outlived the clipper"
