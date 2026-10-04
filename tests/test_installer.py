"""The real installer (build\\installer\\HopSetup-*.exe): silent installs into a
temporary folder for each choice of components, what lands where, a
customized install, and a clean uninstall. Also checks the built apps.

A customized install writes into this PC's real settings folders (Inno Setup
can't be pointed elsewhere), so that test backs those files up first and puts
them back afterwards, whatever happens.

Every test install also shares the real Hop's registration (same AppId), its
Start menu folder and its startup shortcuts, and closes the running Hop apps.
A test uninstall once erased the real install's entry and startup shortcuts,
so the old pre-Hop copies came back at the next restart. `real_hop` saves all
of that first and puts it back (and restarts the apps) afterwards."""
import glob
import json
import os
import shutil
import subprocess
import tempfile
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build")
SETUP = sorted(glob.glob(os.path.join(BUILD, "installer", "HopSetup-*.exe")))
REAL_APPDATA = os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
REAL_LOCAL = os.path.join(os.path.expanduser("~"), "AppData", "Local")
STARTUP = os.path.join(REAL_APPDATA, r"Microsoft\Windows\Start Menu\Programs\Startup")

need_setup = pytest.mark.skipif(not SETUP, reason="build the installer first (installer\\build.ps1)")


def install(target, components, *extra):
    r = subprocess.run([SETUP[-1], "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/NOCANCEL",
                        f"/DIR={target}", f"/COMPONENTS={components}", "/TASKS=", *extra], timeout=600)
    assert r.returncode == 0


def uninstall(target):
    un = os.path.join(target, "unins000.exe")
    subprocess.run([un, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], timeout=300)
    for _ in range(60):                         # the uninstaller finishes in a child process
        if not os.path.exists(un):
            break
        time.sleep(1)


UNINSTALL_KEY = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\{8C1B6A52-4E0D-4F3B-9E62-6F0A2B7D1C11}_is1"
START_MENU = os.path.join(REAL_APPDATA, r"Microsoft\Windows\Start Menu\Programs\Hop")
OLD_STARTUP = ("Lyrics Island.lnk", "clipper.lnk")         # from before Hop
SAVED_STARTUP = ("Hop Island.lnk", "Hop Clipper.lnk") + OLD_STARTUP


def _running_hop():
    import psutil
    out = []
    for p in psutil.process_iter(["name", "exe"]):
        if (p.info["name"] or "").lower() in ("hopisland.exe", "hopclipper.exe") and p.info["exe"]:
            out.append(p.info["exe"])
    return sorted(set(out))


@pytest.fixture(scope="module", autouse=True)
def real_hop():
    """The real install's registration, Start menu folder, startup shortcuts
    and running apps come back exactly as they were after these tests."""
    tmp = tempfile.mkdtemp(prefix="hop-real-")
    reg = os.path.join(tmp, "uninstall.reg")
    had_reg = subprocess.run(["reg", "export", UNINSTALL_KEY, reg, "/y"], capture_output=True).returncode == 0
    menu = os.path.join(tmp, "menu")
    if os.path.isdir(START_MENU):
        shutil.copytree(START_MENU, menu)
    links = {n: open(os.path.join(STARTUP, n), "rb").read()
             for n in SAVED_STARTUP if os.path.exists(os.path.join(STARTUP, n))}
    running = _running_hop()
    try:
        yield
    finally:
        subprocess.run(["reg", "delete", UNINSTALL_KEY, "/f"], capture_output=True)
        if had_reg:
            subprocess.run(["reg", "import", reg], capture_output=True)
        shutil.rmtree(START_MENU, ignore_errors=True)
        if os.path.isdir(menu):
            shutil.copytree(menu, START_MENU)
        for n in SAVED_STARTUP:
            path = os.path.join(STARTUP, n)
            if n in links:
                open(path, "wb").write(links[n])
            elif os.path.exists(path):
                os.remove(path)
        for exe in running:
            if exe not in _running_hop():
                subprocess.Popen([exe], cwd=os.path.dirname(exe), close_fds=True,
                                 creationflags=0x00000008 | 0x00000200)   # detached, new group
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture()
def target():
    d = tempfile.mkdtemp(prefix="hop-install-")
    yield os.path.join(d, "Hop")
    shutil.rmtree(d, ignore_errors=True)


CASES = {
    "island,clipper": {"Island\\HopIsland.exe": True, "Clipper\\HopClipper.exe": True, "ffmpeg\\ffmpeg.exe": True},
    "island": {"Island\\HopIsland.exe": True, "Clipper\\HopClipper.exe": False, "ffmpeg\\ffmpeg.exe": False},
    "clipper": {"Island\\HopIsland.exe": False, "Clipper\\HopClipper.exe": True, "ffmpeg\\ffmpeg.exe": True},
}


@need_setup
@pytest.mark.slow
@pytest.mark.parametrize("components", list(CASES))
def test_install_components(target, components, record_property):
    install(target, components)
    try:
        for rel, expected in CASES[components].items():
            assert os.path.exists(os.path.join(target, rel)) is expected, rel
        for rel in ("LICENSE", "THIRD-PARTY-NOTICES.md", "unins000.exe"):
            assert os.path.exists(os.path.join(target, rel))
        if "clipper" in components:
            assert os.path.exists(os.path.join(target, "ffmpeg", "ffprobe.exe"))
            assert os.path.exists(os.path.join(target, "ffmpeg", "LICENSE-ffmpeg.txt"))
        # no startup entries unless asked for
        assert not os.path.exists(os.path.join(STARTUP, "Hop Island.lnk")) or components == "clipper"
        size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(target) for f in fs)
        record_property("installed size", f"{size / 2**20:.0f} MB")
    finally:
        uninstall(target)
    assert not os.path.exists(os.path.join(target, "Island", "HopIsland.exe"))
    assert not os.path.exists(os.path.join(target, "Clipper", "HopClipper.exe"))


@need_setup
@pytest.mark.slow
def test_install_with_startup(target):
    install(target, "island,clipper", "/MERGETASKS=startisland,startclipper")
    try:
        assert os.path.exists(os.path.join(STARTUP, "Hop Island.lnk"))
        assert os.path.exists(os.path.join(STARTUP, "Hop Clipper.lnk"))
    finally:
        uninstall(target)
    assert not os.path.exists(os.path.join(STARTUP, "Hop Island.lnk"))
    assert not os.path.exists(os.path.join(STARTUP, "Hop Clipper.lnk"))


@need_setup
@pytest.mark.slow
def test_customized_install_writes_settings(target):
    island_file = os.path.join(REAL_APPDATA, "LyricsIslandLite", "installer-settings.json")
    clip_file = os.path.join(REAL_LOCAL, "clipper", "settings.json")
    backup = {p: open(p, "rb").read() if os.path.exists(p) else None for p in (island_file, clip_file)}
    try:
        install(target, "island,clipper", "/CUSTOMIZE=1")
        got = json.load(open(island_file, encoding="utf-8"))
        assert got["prayerMethod"] == 2 and got["asrSchool"] == 0 and got["city"] == ""
        assert got["layout"] == {"scale": 1.0, "musicLeft": "rec", "musicRight": "clock"}    # prayer times are opt-in (off)
        clip = json.load(open(clip_file, encoding="utf-8"))
        assert clip["fps"] == 60 and clip["quality"] == "high" and clip["defaultSeconds"] == 30
        assert clip["watermark"] is True and clip["islandInClips"] is True
        assert clip["saveDir"].endswith("Videos\\Hop Clips")
    finally:
        for p, data in backup.items():               # this PC's own settings come back exactly
            if data is None:
                if os.path.exists(p):
                    os.remove(p)
            else:
                open(p, "wb").write(data)
        uninstall(target)


# ---- the built apps carry what they need
DIST = os.path.join(BUILD, "dist")
need_dist = pytest.mark.skipif(not os.path.exists(os.path.join(DIST, "HopIsland")), reason="build first")


@need_dist
@pytest.mark.parametrize("rel", ["HopIsland\\HopIsland.exe", "HopIsland\\_internal\\ui\\settings.html",
                                 "HopIsland\\_internal\\ui\\index.html", "HopIsland\\_internal\\ui\\island.js",
                                 "HopIsland\\_internal\\ui\\tip.js", "HopIsland\\_internal\\ui\\fonts\\Syne.ttf",
                                 "HopIsland\\_internal\\ui\\brand-island.png", "HopIsland\\_internal\\bridge.js",
                                 "HopIsland\\_internal\\assets\\hop.ico", "HopClipper\\HopClipper.exe",
                                 "HopClipper\\_internal\\watermark.png", "HopClipper\\_internal\\click.wav",
                                 "HopClipper\\_internal\\bunny.png", "ffmpeg\\ffmpeg.exe", "ffmpeg\\ffprobe.exe"])
def test_built_files(rel):
    assert os.path.exists(os.path.join(DIST, rel)), rel


@need_dist
@pytest.mark.parametrize("exe", ["HopIsland\\HopIsland.exe", "HopClipper\\HopClipper.exe"])
def test_exe_has_bunny_icon(exe):
    """The .exe's own icon is the Hop bunny (not Python's)."""
    import ctypes
    shell32 = ctypes.windll.shell32
    n = shell32.ExtractIconExW(os.path.join(DIST, exe), -1, None, None, 0)
    assert n >= 1


@need_setup
@pytest.mark.slow
def test_update_replaces_old_files_keeps_settings(target):
    """Installing over an existing Hop (an update): the old app files are
    removed completely, the user's settings are untouched."""
    island_cfg = os.path.join(REAL_APPDATA, "LyricsIslandLite", "config.json")
    before = open(island_cfg, "rb").read() if os.path.exists(island_cfg) else None
    install(target, "island,clipper")
    try:
        stale = [os.path.join(target, "Island", "old-version-leftover.dll"),
                 os.path.join(target, "Clipper", "_internal", "stale.pyd"),
                 os.path.join(target, "ffmpeg", "avcodec-61.dll")]
        for p in stale:
            open(p, "w").write("from the previous version")
        install(target, "island,clipper")                 # the "update"
        for p in stale:
            assert not os.path.exists(p), f"left behind: {p}"
        assert os.path.exists(os.path.join(target, "Island", "HopIsland.exe"))
        after = open(island_cfg, "rb").read() if os.path.exists(island_cfg) else None
        assert after == before                            # preferences exactly as they were
    finally:
        uninstall(target)


@need_setup
@pytest.mark.slow
def test_update_removes_pre_hop_startup_shortcuts(target):
    """The startup shortcuts from before Hop (pythonw on the old scripts)
    are removed, or the old island and clipper come back at the next sign-in."""
    for n in OLD_STARTUP:
        open(os.path.join(STARTUP, n), "wb").write(b"old")
    install(target, "island,clipper")
    try:
        for n in OLD_STARTUP:
            assert not os.path.exists(os.path.join(STARTUP, n)), n
    finally:
        uninstall(target)


OLD_COPY = r"""
import ctypes, ctypes.wintypes as wt, sys
u32 = ctypes.windll.user32
u32.DefWindowProcW.restype = ctypes.c_ssize_t
u32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
PROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
def wndproc(h, m, w, l):
    if m in (0x8004, 0x0312, 0x0010):     # the quit messages: an old copy ignores them
        return 0
    return u32.DefWindowProcW(h, m, w, l)
proc = PROC(wndproc)
class WNDCLASS(ctypes.Structure):
    _fields_ = [("style", wt.UINT), ("lpfnWndProc", PROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
                ("lpszClassName", wt.LPCWSTR)]
wc = WNDCLASS(lpfnWndProc=proc, lpszClassName=sys.argv[1])
u32.RegisterClassW(ctypes.byref(wc))
u32.CreateWindowExW(0, sys.argv[1], "old copy", 0, 0, 0, 0, 0, None, None, None, None)
msg = wt.MSG()
while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
    u32.TranslateMessage(ctypes.byref(msg)); u32.DispatchMessageW(ctypes.byref(msg))
"""


@need_setup
@pytest.mark.slow
@pytest.mark.parametrize("window_class", ["lyrics-island-lite", "clipper-tray"])
def test_update_closes_an_old_copy_that_ignores_quit(target, window_class, tmp_path):
    """A pre-Hop copy (pythonw, not HopIsland.exe) owns the same window class
    but doesn't know the quit message: the installer closes it anyway."""
    import sys
    script = tmp_path / "old_copy.py"
    script.write_text(OLD_COPY)
    old = subprocess.Popen([sys.executable, str(script), window_class])
    try:
        for _ in range(50):
            import ctypes
            if ctypes.windll.user32.FindWindowW(window_class, "old copy"):
                break
            time.sleep(0.1)
        install(target, "island,clipper")
        try:
            old.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pytest.fail("the old copy is still running after the update")
    finally:
        if old.poll() is None:
            old.kill()
        uninstall(target)
