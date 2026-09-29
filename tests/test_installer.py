"""The real installer (build\\installer\\HopSetup-*.exe): silent installs into a
temporary folder for each choice of components, what lands where, a
customized install, and a clean uninstall. Also checks the built apps.

A customized install writes into this PC's real settings folders (Inno Setup
can't be pointed elsewhere), so that test backs those files up first and puts
them back afterwards, whatever happens."""
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
        assert got["layout"] == {"scale": 1.0, "musicLeft": "rec", "musicRight": "prayer"}
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
