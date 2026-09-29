"""clipper: a tiny "clip the last few seconds" recorder, lighter than Medal.

    pythonw clipper.py          (start.bat does this, with no window)

  F8                save the last 30 s to SAVE_DIR; a notification slides in
                    ("30s recorded"). Click it to pick 15s / 30s / 1min instead;
                    every length is cut back from the moment F8 was pressed.
  Ctrl+Shift+F8     quit
  Tray bunny        double-click: open the clips folder; right-click: menu

HOW IT WORKS
  * The screen is grabbed with Windows Graphics Capture (ffmpeg's gfxcapture;
    it sees fullscreen games that Desktop Duplication misses), the "recorded
    with <bunny>" watermark is burnt in, and it is encoded on the CPU with
    x264 (1-3 cores with motion), so a game can't starve the recorder of GPU time.
  * The recording is a rolling ring of 2-second MPEG-TS pieces on disk (a bit
    over a minute of them), overwritten in place: no RAM buffer of video.
  * Saving is a stream copy: no re-encode, so it is instant and lossless.
  * Starts with Windows (a Startup-folder shortcut), keeps itself recording
    through sleep/wake and device changes, and only one copy ever runs.

"FROM THE SECOND I PRESSED F8"
  F8 copies the newest minute of pieces, including the one being written at
  that instant, out of the ring into a snapshot. Every length you pick later is
  cut from that snapshot, so it always ends exactly where F8 was pressed, however
  long you take to choose. Keyframes are every second, so the start of a clip
  lands within a second of the length asked for.

AUDIO
  Desktop sound (whatever you hear) through WASAPI loopback, from the
  `soundcard` package, piped into the same ffmpeg so it is muxed in sync with
  the picture. Loopback delivers nothing while the PC is silent, so a silent
  stream is kept playing to hold the device awake. Clock drift is corrected
  inaudibly (see audio_pump); short hold-ups are never padded with silence.
  Set MIC = True to mix your microphone in too.
"""
import ctypes
import ctypes.wintypes as wt
import datetime
import json
import math
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import warnings
import winsound

import numpy as np
import soundcard as sc
from PIL import Image, ImageTk

# ------------------------------------------------------------------ settings
DEFAULT_SECONDS = 30
LENGTHS = [(15, "15s"), (30, "30s"), (60, "1min")]
FPS = 60
QUALITY = 22            # x264 CRF: lower is better/bigger; 18-26 is sensible
MIC = False
# Files that ship with the app: next to this script, or inside the PyInstaller
# bundle when frozen.
HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else HERE
DEFAULT_SAVE_DIR = os.path.join(os.path.expanduser("~"), "Videos", "Hop Clips")


def _read_version():
    for p in (os.path.join(HERE, "VERSION"), os.path.join(HERE, "..", "VERSION")):
        try:
            return open(p, encoding="utf-8").read().strip()
        except OSError:
            pass
    return "0.0.0"


VERSION = _read_version()
RELEASES = "https://github.com/preinfection/hop/releases/latest"


def version_tuple(v):
    """'v0.2.0' -> (0, 2, 0); junk -> (0,)."""
    try:
        return tuple(int(x) for x in str(v).strip().lstrip("vV").split("-")[0].split("."))
    except ValueError:
        return (0,)


def latest_release():
    """(version, page url) of Hop's newest release on GitHub, or None (offline,
    no releases yet). One small public request; no account."""
    import urllib.request
    req = urllib.request.Request("https://api.github.com/repos/preinfection/hop/releases/latest",
                                 headers={"User-Agent": f"hop-clipper/{VERSION}", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read().decode("utf-8"))
        return d.get("tag_name", "").lstrip("vV"), d.get("html_url") or RELEASES
    except Exception:
        return None


def island_installed():
    """Hop Island next to us: it shows update notices when the clipper isn't
    running; when both run, the clipper shows them (one notice, not two)."""
    return os.path.exists(os.path.join(APP_DIR, "..", "Island", "HopIsland.exe"))


def find_tool(name):
    """ffmpeg / ffprobe: the copy the installer put in <install>\ffmpeg, one
    next to the app, $HOP_FFMPEG_DIR, or whatever is on PATH."""
    dirs = [os.environ.get("HOP_FFMPEG_DIR", ""), os.path.join(APP_DIR, "..", "ffmpeg"),
            os.path.join(APP_DIR, "ffmpeg"), APP_DIR]
    for d in dirs:
        p = os.path.join(d, name)
        if d and os.path.exists(p):
            return os.path.abspath(p)
    return shutil.which(name) or name


FFMPEG = find_tool("ffmpeg.exe")
ICON, BUNNY, CLICK = (os.path.join(HERE, n) for n in ("bunny.ico", "bunny.png", "click.wav"))
RING = os.path.join(os.environ["TEMP"], "clipper-ring")
HOLD = os.path.join(os.environ["TEMP"], "clipper-hold")
SEG = 2                                   # seconds per piece
LONGEST = max(s for s, _ in LENGTHS)
PIECES = LONGEST // SEG + 3               # ring: a bit over the longest clip
RATE, CH, BLOCK = 48000, 2, 960           # 20 ms audio blocks
CAPTURE_LAG_S = 0.08                      # picture capture latency; see start_ffmpeg

warnings.filterwarnings("ignore", category=sc.SoundcardRuntimeWarning)
NO_WINDOW = 0x08000000
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)   # crisp toast on scaled displays
except Exception:
    pass


APP_NAME = "Hop Clipper"
# What the user picked in Hop Island's settings app (Clipper tab). Read at every
# recorder start and on WM_CLIP_RELOAD, so changes apply without a restart.
SETTINGS_FILE = os.path.join(os.environ.get("LOCALAPPDATA", HERE), "clipper", "settings.json")
SETTINGS_DEFAULTS = {"watermark": True, "cursor": True, "toastInClips": False, "islandInClips": True,
                     "fps": 60, "quality": "high", "defaultSeconds": 30, "sounds": True, "saveDir": ""}
CRF = {"best": 18, "high": 22, "small": 27}


def weak_pc():
    """4 CPU threads or fewer, or under 8 GB of RAM: default to 30 fps there
    (half the capture and encode work); a picked frame rate always wins."""
    try:
        import psutil
        return (os.cpu_count() or 4) <= 4 or psutil.virtual_memory().total < 8 * 1024 ** 3
    except Exception:
        return (os.cpu_count() or 4) <= 4


WEAK_PC = weak_pc()


def settings():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as fh:
            got = json.load(fh)
    except (OSError, ValueError):
        got = {}
    if not isinstance(got, dict):                   # a damaged file (a list, null...): defaults
        got = {}
    out = dict(SETTINGS_DEFAULTS, fps=30 if WEAK_PC else 60)
    out.update({k: v for k, v in got.items() if k in SETTINGS_DEFAULTS and type(v) is type(SETTINGS_DEFAULTS[k])})
    if out["fps"] not in (30, 60, 120):              # 120: for fast PCs on high-refresh screens
        out["fps"] = 60
    if out["quality"] not in CRF:
        out["quality"] = "high"
    if out["defaultSeconds"] not in [n for n, _ in LENGTHS]:
        out["defaultSeconds"] = 30
    out["saveDir"] = out["saveDir"].strip() or DEFAULT_SAVE_DIR     # "" = the default folder
    return out


SAVE_DIR = settings()["saveDir"]


def click_sound():
    if not settings()["sounds"]:
        return
    try:
        winsound.PlaySound(CLICK, winsound.SND_FILENAME | winsound.SND_ASYNC)
    except RuntimeError:
        winsound.Beep(1200, 80)


# ------------------------------------------------------------------ log
# %LOCALAPPDATA%\clipper\clipper.log: recorder starts/exits, stalls (with the
# window in front at the time), pauses, restarts and saves. ffmpeg's own
# warnings go to ffmpeg.log beside it. Each is capped at ~1 MB (one .old kept).
LOG_DIR = os.path.join(os.environ.get("LOCALAPPDATA", HERE), "clipper")
LOG = os.path.join(LOG_DIR, "clipper.log")
FF_LOG = os.path.join(LOG_DIR, "ffmpeg.log")
_log_lock = threading.Lock()


def _rotate(path, limit=1_000_000):
    try:
        if os.path.getsize(path) > limit:
            os.replace(path, path + ".old")
    except OSError:
        pass


def log(*parts):
    line = f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S.%f}"[:-3] + "  " + " ".join(str(p) for p in parts)
    with _log_lock:
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            _rotate(LOG)
            with open(LOG, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass


def foreground():
    """The window in front: title, process-owned size, and whether it covers its monitor."""
    try:
        h = u32.GetForegroundWindow()
        n = u32.GetWindowTextLengthW(h)
        buf = ctypes.create_unicode_buffer(n + 1)
        u32.GetWindowTextW(h, buf, n + 1)
        r = wt.RECT()
        u32.GetWindowRect(h, ctypes.byref(r))
        full = (r.right - r.left) >= u32.GetSystemMetrics(0) and (r.bottom - r.top) >= u32.GetSystemMetrics(1)
        island = bool(u32.IsWindowVisible(u32.FindWindowW(None, "Lyrics Island")))
        return f"front={buf.value!r} {r.right - r.left}x{r.bottom - r.top} fullscreen={full} island_visible={island}"
    except Exception as e:
        return f"front=? ({e})"


LAST = os.path.join(LOG_DIR, "last.json")


def announce(path, seconds, kind):
    """Tell the Lyrics Island a file was just saved (it watches this file and
    shows the clip-saved card with Open / Copy)."""
    try:
        tmp = LAST + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"path": path, "seconds": seconds, "kind": kind, "at": time.time()}, fh)
        os.replace(tmp, LAST)
    except OSError:
        pass


def run_ff(args):
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args], creationflags=NO_WINDOW)


# ------------------------------------------------------------------ what to capture
# FULLSCREEN GAMES ARE CAPTURED AS A WINDOW. A borderless-fullscreen game that
# covers the screen is shown by "independent flip": its frames go straight to
# the display and DWM does not compose them, so capturing the MONITOR got
# nothing new until something forced a compose (the 1 px heartbeat), and even
# then the game's picture moved ~5 times a second. Measured 2026-09-27: a 15 s
# Roblox clip held 81 distinct frames, frozen for 4.7 s and 5.4 s at a time;
# turning MPO off (OverlayTestMode=5) did not change that. Capturing the game's
# WINDOW takes frames from its own swap chain, whatever the flip mode. So the
# recorder follows the foreground window: a window filling the primary monitor
# is captured on its own, anything else means the whole monitor. Each switch
# starts a fresh recorder in its own ring folder, and clips join pieces across
# folders, so a switch costs about a second of picture, not the buffer.
SILENT_WINDOWS = {}                     # hwnd -> until when: gave no frames, use the monitor instead
SHELL_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Windows.UI.Core.CoreWindow"}


KEEP = "keep"                           # capture_target: carry on with whatever is being captured
# ALWAYS THE WHOLE SCREEN (2026-09-28). Following the fullscreen game meant a
# recorder restart on every alt-tab and back, and each restart cut ~0.1-0.15 s
# of frames out of clips (the "spikes"). Measured in Roblox (cap 60, MPO off):
# monitor capture 59.5 real fps / worst gap 34 ms, window capture 56.7 / 50 ms,
# so the screen is the better source anyway. False = never switch.
FOLLOW_GAMES = False


def capture_target():
    """hwnd of a fullscreen window in front (a game), None for the whole
    monitor, or KEEP when clipper's own toast is in front: clicking the toast
    to change a clip's length must not switch the capture away from the game
    (it did, 2026-09-27: 5 s of monitor capture after every toast click)."""
    if not FOLLOW_GAMES:
        return None
    try:
        h = u32.GetForegroundWindow()
        if not h:
            return None
        pid = wt.DWORD()
        u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value == os.getpid():
            return KEEP
        # Clicking the Lyrics Island (its record button) brings it to the
        # front; that is not leaving the game either.
        if _title(h) == "Lyrics Island":
            return KEEP
        cls = ctypes.create_unicode_buffer(128)
        u32.GetClassNameW(h, cls, 128)
        if cls.value in SHELL_CLASSES:
            return None
        r = wt.RECT()
        u32.GetWindowRect(h, ctypes.byref(r))
        sw, sh = u32.GetSystemMetrics(0), u32.GetSystemMetrics(1)       # the primary monitor (monitor_idx=0)
        if r.left <= 0 and r.top <= 0 and r.right >= sw and r.bottom >= sh and not u32.IsIconic(h)                 and SILENT_WINDOWS.get(int(h), 0) < time.time():
            return int(h)
    except Exception:
        pass
    return None


def _still_in_game(game):
    """True when the game window is still up and what took the front is only a
    pop-up over it: a notification, the volume or Start flyout, an overlay, a
    tool or untitled window, or a window of the game itself. Only a real app
    window (Discord, a browser...) means the player left the game. The capture
    kept flipping to the monitor mid-game, and each flip restarted the recorder
    (2026-09-28: two restarts in one 15 s clip, audio dropouts at both)."""
    try:
        if not u32.IsWindow(game) or u32.IsIconic(game) or not u32.IsWindowVisible(game):
            return False
        h = u32.GetForegroundWindow()
        if not h:
            return True
        cls = ctypes.create_unicode_buffer(128)
        u32.GetClassNameW(h, cls, 128)
        if cls.value in ("Progman", "WorkerW"):                   # the desktop: the game really was left
            return False
        if cls.value in SHELL_CLASSES or not _title(h).strip():
            return True
        if u32.GetWindowLongW(h, -20) & 0x80:                      # WS_EX_TOOLWINDOW
            return True
        a, b = wt.DWORD(), wt.DWORD()
        u32.GetWindowThreadProcessId(h, ctypes.byref(a))
        u32.GetWindowThreadProcessId(game, ctypes.byref(b))
        return a.value == b.value
    except Exception:
        return False


def _title(h):
    try:
        n = u32.GetWindowTextLengthW(h)
        buf = ctypes.create_unicode_buffer(n + 1)
        u32.GetWindowTextW(h, buf, n + 1)
        return buf.value
    except Exception:
        return "?"


# ------------------------------------------------------------------ recorder
def _run_dirs():
    try:
        return [os.path.join(RING, d) for d in os.listdir(RING) if os.path.isdir(os.path.join(RING, d))]
    except OSError:
        return []


def _all_pieces():
    """Every non-empty ring piece of every recent run, oldest first."""
    out = []
    for d in _run_dirs():
        try:
            out += [os.path.join(d, f) for f in os.listdir(d) if f.endswith(".ts")]
        except OSError:
            pass
    out = [(os.path.getmtime(p), p) for p in out if os.path.exists(p)]
    return [p for _, p in sorted(out)]


_JOB = None


def _tie_to_us(proc):
    """Put a recorder in a Windows job that closes with this process, so if the
    clipper ever dies (crash, force-close, Task Manager) Windows kills its
    ffmpeg too. An ffmpeg left behind kept capturing with no sound input and
    grew to 6 GB of memory (seen 2026-09-28)."""
    global _JOB
    k = ctypes.windll.kernel32
    try:
        if _JOB is None:
            class LIMITS(ctypes.Structure):
                _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                            ("LimitFlags", wt.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wt.DWORD),
                            ("Affinity", ctypes.c_size_t), ("PriorityClass", wt.DWORD), ("SchedulingClass", wt.DWORD)]

            class IO(ctypes.Structure):
                _fields_ = [(n, ctypes.c_uint64) for n in ("r", "w", "o", "rb", "wb", "ob")]

            class EXT(ctypes.Structure):
                _fields_ = [("Basic", LIMITS), ("Io", IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                            ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                            ("PeakJobMemoryUsed", ctypes.c_size_t)]
            k.CreateJobObjectW.restype = wt.HANDLE
            job = k.CreateJobObjectW(None, None)
            info = EXT()
            info.Basic.LimitFlags = 0x2000                       # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            k.SetInformationJobObject(wt.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info))   # Extended limits
            _JOB = job
        h = k.OpenProcess(0x0100 | 0x0001, False, proc.pid)     # PROCESS_SET_QUOTA | TERMINATE
        if h:
            k.AssignProcessToJobObject(wt.HANDLE(_JOB), wt.HANDLE(h))
            k.CloseHandle(wt.HANDLE(h))
    except Exception as e:
        log("could not tie ffmpeg to the clipper:", repr(e))


def _ffmpeg_mb(ff):
    try:
        import psutil
        return psutil.Process(ff.pid).memory_info().rss / 2 ** 20
    except Exception:
        return 0


def take_over(mutex_name, window_class, quit_msg, quit_wparam=0, wait=8.0):
    """ONE copy at a time, and the NEWEST one wins: if another copy is running
    (an update was just installed, or a copy started some other way), ask it
    to quit, wait for it, and close it by force if it doesn't answer (an older
    version may not know the message). Returns our mutex handle.

    0.1.0 simply exited when a copy was already running, so after an update
    the OLD version kept running until the PC restarted."""
    k32_ = ctypes.windll.kernel32
    u32_ = ctypes.windll.user32
    k32_.CreateMutexW.restype = wt.HANDLE

    def grab():
        h = k32_.CreateMutexW(None, False, mutex_name)
        if k32_.GetLastError() != 183:              # ERROR_ALREADY_EXISTS
            return h
        k32_.CloseHandle(wt.HANDLE(h))
        return None

    h = grab()
    if h:
        return h
    w = u32_.FindWindowW(window_class, None)
    if w:
        u32_.PostMessageW(w, quit_msg, quit_wparam, 0)
    end = time.time() + wait
    while time.time() < end:
        time.sleep(0.1)
        h = grab()
        if h:
            return h
    if w:                                           # it didn't answer: close it
        pid = wt.DWORD()
        u32_.GetWindowThreadProcessId(w, ctypes.byref(pid))
        proc = k32_.OpenProcess(0x0001, False, pid.value)      # PROCESS_TERMINATE
        if proc:
            k32_.TerminateProcess(wt.HANDLE(proc), 0)
            k32_.CloseHandle(wt.HANDLE(proc))
    for _ in range(30):
        time.sleep(0.1)
        h = grab()
        if h:
            return h
    return None


TRAY_CLASS = "clipper-tray" + os.environ.get("HOP_TEST_INSTANCE", "")


def stop_ffmpeg(ff, wait=3.0):
    """Stop a recorder CLEANLY: close its sound input and let it finish the
    current piece. Killing it outright left that piece cut off mid-frame, and
    a clip saved across the restart (screen off/on, a settings change, the
    watchdog) played a few glitched frames (found by tests/test_clipper.py,
    2026-09-28). Killed only if it hasn't finished within `wait` seconds."""
    if ff is None or ff.poll() is not None:
        return
    try:
        ff.stdin.close()
    except Exception:
        pass
    try:
        ff.wait(wait)
    except Exception:
        ff.kill()


def new_ring_dir():
    """A fresh folder for one recorder run; runs whose pieces are all older
    than the longest clip (plus slack) are removed."""
    os.makedirs(RING, exist_ok=True)
    for f in os.listdir(RING):                      # pieces from the old flat layout
        if f.endswith(".ts"):
            try:
                os.remove(os.path.join(RING, f))
            except OSError:
                pass
    for d in _run_dirs():
        try:
            newest = max((os.path.getmtime(os.path.join(d, f)) for f in os.listdir(d)), default=0)
        except OSError:
            continue
        if time.time() - newest > LONGEST + 30:
            shutil.rmtree(d, ignore_errors=True)
    d = os.path.join(RING, f"{time.time():.3f}")
    os.makedirs(d, exist_ok=True)
    return d


def start_ffmpeg(audio_t0, ring_dir, hwnd=None):
    """Starts the recorder. `audio_t0` is the wall-clock time (time.time()) of
    the first audio sample the pump is about to write.

    ONE CLOCK FOR PICTURE AND SOUND. Both sides take an unpredictable while to
    start (opening the loopback device, starting Graphics Capture: ~0.2-2 s
    each), and gfxcapture re-zeroes its timestamps at its first frame, so
    lining them up by "when ffmpeg was launched" put the sound 230 ms, then
    2.1 s, ahead of the picture (flash + beep measurements, 2026-09-27). Now
    both timelines start at the audio's first sample:
      * the audio counts samples from 0 (steady, no jitter);
      * each video frame is stamped, the moment it enters the filter graph,
        with (wall clock now - audio_t0) via setpts and RTCTIME.
    Tried first and rejected: wall-clock input timestamps + -copyts +
    -itsoffset. -copyts stalled the recorder after 4-5 frames whenever the
    audio pipe was attached (bisected), so it is not used.
    """
    sw, sh = u32.GetSystemMetrics(0), u32.GetSystemMetrics(1)
    if hwnd:
        # Always monitor-sized, so pieces from window and monitor runs join cleanly.
        src = f"gfxcapture=hwnd={hwnd}:width={sw}:height={sh}:resize_mode=scale_aspect"
    else:
        src = "gfxcapture=monitor_idx=0"
    # A frame reaches the filter ~80 ms after it was on screen (compose +
    # capture), while loopback hears sound as it is played: measured
    # -82 / -77 ms (sound early) with a flash + beep. Stamping each frame that
    # much earlier puts picture and sound together.
    t0_us = int((audio_t0 + CAPTURE_LAG_S) * 1_000_000)
    cfg = settings()
    fps, crf = cfg["fps"], CRF[cfg["quality"]]
    mark = (f"[v][2:v]overlay=x=(main_w-overlay_w)/2:y=22:format=yuv420,fps={fps},format=yuv420p,"
            if cfg["watermark"] else f"[v]fps={fps},format=yuv420p,")
    args = [
        FFMPEG, "-hide_banner", "-loglevel", "error",
        # WINDOWS GRAPHICS CAPTURE, not Desktop Duplication (ddagrab). Roblox in
        # fullscreen draws through a hardware overlay plane that ddagrab does not
        # see, so its clips came out frozen with the odd jump (2026-09-27). This
        # is the capture OBS uses for such games, and it also costs less (~1% vs
        # ~3%): it only hands over a frame when the screen actually changed.
        "-f", "lavfi", "-i", f"{src}:max_framerate={fps}:capture_cursor={int(cfg['cursor'])}",
        "-f", "f32le", "-ar", str(RATE), "-ac", str(CH), "-i", "pipe:0",
        "-i", WATERMARK,                           # one frame; overlay repeats it forever
        # THE WATERMARK IS BURNT IN WHILE RECORDING, so saving stays a stream
        # copy and is instant. fps=60 turns the capture's changes-only frames
        # into a steady 60.
        # ONE GPU STEP ONLY (2026-09-28). The old chain (vpp_qsv to NV12, a
        # download, then Quick Sync) waited on the GPU three times a frame,
        # each time behind the game's queue: Roblox at ~110 fps left clips at
        # 8-15 real fps. Measured in game, capture + a plain download alone
        # still ran at ~35-43 fps. So the GPU only captures and copies the
        # frame out; watermark, colour conversion and x264 run on the CPU
        # (x264 on 2 threads: benched as good as 4 or 6 under load, ~1.8 cores total).
        # Timestamps: the FIRST frame is placed by the wall clock (for A/V
        # sync), every later one by the capture's own clock. Stamping each
        # frame by RTCTIME when the filter got to it (as before) meant a busy
        # CPU made frames look late, fps=60 filled the "gap" with copies that
        # were then converted and encoded too, and the recorder fell further
        # behind for good (2026-09-28 bug test: 25-37 s behind, clips ending
        # 3-5 s before F8, ffmpeg at 1 GB). fps runs after the conversion, so
        # a copy costs only the encoder's cheap skip.
        "-filter_complex", f"[0:v]setpts='if(eq(N,0),(RTCTIME-{t0_us})/(1000000*TB),PREV_OUTPTS+PTS-PREV_INPTS)',"
                           f"hwdownload,format=bgra,scale=out_color_matrix=bt709:out_range=tv,format=yuv420p[v];"
                           # Converted to YUV straight after the download, before the
                           # watermark and fps: benchmarked under a game-level GPU load,
                           # 17-21 -> ~30 real fps at the same CPU.
                           + mark +
                           f"setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv[out]",
        "-map", "[out]", "-map", "1:a",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", str(crf), "-threads", str(min(2, os.cpu_count() or 2)),
        "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
        # A keyframe every second: a clip's start can only be cut on one, and
        # the ring can only split on one. They must be real IDRs (forced-idr),
        # or the ring is found as ONE long piece and a cut comes out audio-only.
        "-g", str(fps), "-force_key_frames", "expr:gte(t,n_forced*1)", "-forced-idr", "1",
        "-c:a", "aac", "-b:a", "160k",
        # Ends when the sound input ends: stop_ffmpeg() closes it, so the piece
        # being written is finished properly instead of cut off mid-frame.
        "-shortest",
        "-f", "segment", "-segment_time", str(SEG), "-segment_wrap", str(PIECES),
        "-segment_format", "mpegts", "-reset_timestamps", "1",
        os.path.join(ring_dir, "p%03d.ts"),
    ]
    args[args.index("-loglevel") + 1] = "warning"
    os.makedirs(LOG_DIR, exist_ok=True)
    _rotate(FF_LOG)
    ff_log = open(FF_LOG, "ab")
    ff_log.write(f"\n==== {datetime.datetime.now():%Y-%m-%d %H:%M:%S} recorder start ({src})\n".encode())
    ff_log.flush()
    proc = subprocess.Popen(args, stdin=subprocess.PIPE, stderr=ff_log, creationflags=NO_WINDOW)
    _tie_to_us(proc)
    # No _boost(proc) any more: HIGH GPU priority made BOTH the recording and
    # the game slower under a game-level load (2026-09-28 bench: 30 -> 40 real
    # fps and the "game" 50 -> 97 fps without it).
    return proc


def _boost(proc):
    """Keeps a heavy game from starving the recorder (2026-09-28: an uncapped
    Roblox had the Iris Xe at ~80% and a 15 s clip held only 211 distinct
    frames, ~14 fps). HIGH GPU scheduling priority (what OBS does; allowed
    without admin) gets the capture and its copy out in ahead of the game's
    frames.
    The GPU call fails (0xC000000D) until ffmpeg has opened the GPU, so it is
    retried on a thread for a few seconds."""
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x0200 | 0x0400, False, proc.pid)   # SET_ | QUERY_INFORMATION
    if not h:
        return
    # NOT an above-normal CPU class: measured 2026-09-28 it made the x264
    # pipeline burn ~1 extra core (0.9 -> 1.9) without any more frames.

    def gpu():
        try:
            st = 0
            for _ in range(40):
                if proc.poll() is not None:
                    return
                st = ctypes.windll.gdi32.D3DKMTSetProcessSchedulingPriorityClass(h, 4) & 0xFFFFFFFF   # HIGH
                if not st:
                    return
                time.sleep(0.25)
            log(f"GPU priority not raised: {st:#x}")
        finally:
            k.CloseHandle(h)
    threading.Thread(target=gpu, daemon=True).start()


def _keep_recording_forever(stop, holder, heartbeat):
    """keep_recording, but an exception can't end recording for good: under
    pythonw a crashed thread leaves no trace, and on 2026-09-28 the recorder
    silently stopped after a pause and never came back. Logs the traceback
    and starts it again."""
    import traceback
    while not stop.is_set():
        try:
            keep_recording(stop, holder, heartbeat)
            return
        except Exception:
            log("RECORDER CRASHED, restarting in 2 s: " + traceback.format_exc().replace("\n", " | "))
            stop_ffmpeg(holder.get("ff"))
            holder.pop("run_id", None)
            time.sleep(2)


def keep_recording(stop, holder, heartbeat=lambda on: None):
    """Runs for the life of the program so clipper can stay up 24/7: starts
    ffmpeg and the audio pump, and if either dies (sleep/wake, a display or
    driver change, the default speaker changing) starts both again two seconds
    later on whatever the current devices are. The ring is restarted empty, so
    a clip right after a restart is shorter than 30 s.

    It also watches for a STILL SCREEN. Graphics Capture only hands over a
    frame when something on screen changes, and ffmpeg's fps filter cannot
    invent the frames in between until the next one arrives, so on a screen
    where nothing moves the whole recording (picture AND sound) stalls: found
    by capturing a still Notepad window, which never even reached its 6 s
    limit. When the ring stops growing for STALL_S, `heartbeat(True)` makes a
    1-pixel, nearly transparent window flicker so the capture keeps ticking;
    after 10 s it is switched off again to see whether real frames are flowing,
    so it is never left sitting over a game (where frames flow anyway)."""
    STALL_S = 1.5
    while not stop.is_set():
        # PAUSED while the PC is locked, asleep or its screen is off (set from
        # the window's session/power messages in main). Recording then is
        # worthless, and a capture left running through a lock came back stuck
        # on the lock screen with a dead sound device (13:09-14:24, 2026-09-27).
        if holder.get("paused"):
            time.sleep(0.5)
            continue
        run = threading.Event()                         # ends THIS run's audio threads
        target = capture_target()
        if target == KEEP:
            target = holder.get("target")
        holder["target"] = target
        ring_dir = new_ring_dir()
        holder["ring"] = ring_dir
        t0 = time.time()                                # time zero for picture AND sound
        ff = start_ffmpeg(t0, ring_dir, target)
        holder["ff"] = ff
        log("recorder started, pid", ff.pid, f"capturing window {_title(target)!r}" if target else "capturing monitor")
        pump = threading.Thread(target=_pump_guarded, args=(ff, stop, run, t0), daemon=True)
        pump.start()
        started, beating, beat_since, other_since = time.time(), False, 0.0, None
        newest, pieces_done, pace_from, pace_base = None, 0, time.time(), 0
        while not stop.is_set() and ff.poll() is None and pump.is_alive() and not holder.get("paused") \
                and holder.get("run_id") != "restart":
            time.sleep(0.5)
            # Follow the foreground: a fullscreen game in front (or leaving one)
            # restarts the recorder on the right source once it has held 1 s.
            now_target = capture_target()
            if now_target == KEEP or (now_target is None and target and _still_in_game(target)):
                now_target = target
            if now_target != target:
                other_since = other_since or time.time()
                # Leaving a game waits 2 s: every switch restarts ffmpeg and the
                # audio, which drops a moment of picture and sound from clips.
                if time.time() - other_since >= (2.0 if target else 1.0):
                    holder["run_id"] = "restart"
                    log("capture switch ->", f"window {_title(now_target)!r}" if now_target else "monitor",
                        ";", foreground())
                    break
            else:
                other_since = None
            # Falling behind: each finished piece is SEG s of picture, so the
            # pieces must keep pace with the clock. A recorder more than 6 s
            # behind never catches up (clips would end seconds before F8);
            # start a fresh one instead.
            n = _newest_in(ring_dir)
            if n and n != newest:
                newest, pieces_done = n, pieces_done + 1
            if beating or time.time() - _ring_touched(ring_dir) > 1.0:
                pace_from, pace_base = time.time(), pieces_done   # a still screen makes no frames: not lag
            behind = (time.time() - pace_from) - (pieces_done - pace_base + 1) * SEG
            mb = _ffmpeg_mb(ff) if int(time.time()) % 5 == 0 else 0
            if mb > 1536:
                # normal is ~100 MB; this much means frames are piling up somewhere
                log(f"recorder using {mb:.0f} MB -> restart")
                holder["run_id"] = "restart"
                break
            if time.time() - started > 12 and behind > 6:
                log(f"recorder {behind:.0f} s behind real time -> restart;", foreground())
                holder["run_id"] = "restart"
                break
            stalled = time.time() - started > 5 and time.time() - _ring_touched(ring_dir) > STALL_S
            if target and time.time() - started > 5 and time.time() - _ring_touched(ring_dir) > 3:
                # A window that draws nothing (paused, loading, hidden): the
                # heartbeat can't help here, so record the monitor for a minute.
                SILENT_WINDOWS[target] = time.time() + 60
                log("window", repr(_title(target)), "gave no frames for 3 s -> monitor")
                holder["run_id"] = "restart"
                break
            if stalled and target:
                continue
            if stalled and not beating:
                beating, beat_since = True, time.time()
                log("STALL: no new frames for", STALL_S, "s -> heartbeat on;", foreground())
                heartbeat(True)
            # While it beats the ring always moves, so "not stalled" says nothing:
            # give it 10 s, then stop and see whether real frames are flowing.
            elif beating and not stalled and time.time() - beat_since > 10:
                beating = False
                log("heartbeat off (10 s check);", foreground())
                heartbeat(False)
        if beating:
            heartbeat(False)
        why = ("stop" if stop.is_set() else "paused" if holder.get("paused") else
               "restart requested" if holder.get("run_id") == "restart" else
               f"ffmpeg exited with {ff.poll()}" if ff.poll() is not None else "audio pump died")
        log("recorder ended:", why)
        run.set()
        stop_ffmpeg(ff)                                 # finishes the last piece, then exits
        restart_now = holder.pop("run_id", None) == "restart"
        if not stop.is_set() and not restart_now:
            time.sleep(2)


def _newest_in(ring_dir):
    try:
        return max((f for f in os.listdir(ring_dir) if f.endswith(".ts")),
                   key=lambda f: os.path.getmtime(os.path.join(ring_dir, f)))
    except (OSError, ValueError):
        return None


def _ring_touched(ring_dir):
    try:
        return max(os.path.getmtime(os.path.join(ring_dir, f)) for f in os.listdir(ring_dir) if f.endswith(".ts"))
    except (ValueError, OSError):
        return time.time()


def _pump_guarded(ff, stop, run, t0):
    try:
        audio_pump(ff, stop, run, t0)
    except Exception:
        pass                                            # device gone etc.: keep_recording restarts both
    finally:
        run.set()                                       # take the reader and keep-awake threads down too


def audio_pump(ff, stop, run, t0):
    """Loopback (+ optional mic) -> ffmpeg stdin, lined up with the picture.

    CAPTURE NEVER WAITS ON FFMPEG. A reader thread only ever pulls blocks off
    the sound device into a queue; this function writes them to ffmpeg. It used
    to be one loop: while ffmpeg took ~2 s to start reading, the pipe filled,
    the loop blocked, WASAPI's buffer overflowed and ~2 s of sound were thrown
    away, so every clip played its sound ~2.3 s early (flash + beep test,
    2026-09-27; the earlier 230 ms was the same thing, smaller).

    LINED UP WITH THE PICTURE: the picture's time zero is t0 (see start_ffmpeg),
    so the time between t0 and the first captured sample is written as silence
    first, and from then on the sound runs sample for sample.

    NEVER PADDED FOR A SHORT DELAY. It used to insert silence whenever it fell
    100 ms behind the wall clock, which put 70-150 ms dropouts into the middle
    of music (six in one 30 s clip); a hold-up here costs nothing now, the
    queue just holds the sound until it is written. What is still handled, in
    the reader where the timing is clean:
      * sound-card clock drift, which over hours of 24/7 recording would slide
        the sound out of sync: a 960-sample block is stretched or squeezed by
        ONE sample (0.1%, far below hearing) while the smoothed error is over
        30 ms;
      * a real stall, the device delivering nothing for 250 ms or more: that
        time is filled with silence once, so picture and sound stay aligned.
    It ends (so the watchdog restarts everything) if the default speaker
    changes, e.g. headphones plugged in, or it would keep listening to the old
    device."""
    speaker = sc.default_speaker()
    q = queue.Queue(maxsize=RATE // BLOCK * 30)       # up to 30 s of sound waiting on ffmpeg
    reader = threading.Thread(target=_audio_reader, args=(speaker, q, stop, run, t0), daemon=True)
    reader.start()
    threading.Thread(target=_silence, args=(speaker, run), daemon=True).start()
    while not stop.is_set() and not run.is_set():
        try:
            block = q.get(timeout=1.0)
        except queue.Empty:
            if not reader.is_alive():
                return                                  # device gone: let the watchdog restart
            continue
        try:
            ff.stdin.write(block.tobytes())
        except (BrokenPipeError, OSError):
            return


def _audio_reader(speaker, q, stop, run, t0):
    try:
        loop_mic = sc.get_microphone(speaker.name, include_loopback=True)
        mic_rec = sc.default_microphone().recorder(samplerate=RATE, channels=CH, blocksize=BLOCK) if MIC else None
        with loop_mic.recorder(samplerate=RATE, channels=CH, blocksize=BLOCK) as rec:
            if mic_rec:
                mic_rec.__enter__()
            first = True
            sent, err, checked = 0, 0.0, time.time()
            while not stop.is_set() and not run.is_set():
                a = time.perf_counter()
                block = rec.record(numframes=BLOCK)
                waited = time.perf_counter() - a
                if mic_rec:
                    block = np.clip(block + mic_rec.record(numframes=BLOCK), -1, 1)
                block = block.astype(np.float32)
                if first:
                    # This block was heard over the last BLOCK samples; everything
                    # between the picture's time zero and then is silence.
                    lead = int(((time.time() - BLOCK / RATE) - t0) * RATE)
                    if lead > 0:
                        block = np.vstack([np.zeros((lead, CH), np.float32), block])
                    elif lead < 0:
                        block = block[min(-lead, len(block) - 1):]
                    first = False
                elif waited > 5:
                    # Not a stall: the PC slept. Filling that with silence once
                    # pushed 74 MINUTES of zeros into ffmpeg after a standby
                    # (2026-09-27): the timeline raced ahead, the picture froze and
                    # a 30 s clip came out audio-only and 137 s long. Restart.
                    return
                elif waited > 0.25:                           # the device really stopped delivering
                    gap = int((waited - BLOCK / RATE) * RATE)
                    block = np.vstack([np.zeros((gap, CH), np.float32), block])
                due = (time.time() - t0) * RATE
                err = 0.98 * err + 0.02 * (due - (sent + len(block)))
                if err > 0.03 * RATE:                          # sound running slow: one extra sample
                    block = _stretch(block, len(block) + 1)
                elif err < -0.03 * RATE:                       # sound running fast: one fewer
                    block = _stretch(block, len(block) - 1)
                try:
                    q.put(block, timeout=5)
                except queue.Full:
                    return                                     # ffmpeg is not taking anything: restart
                sent += len(block)
                if time.time() - checked > 3:                  # headphones in or out?
                    checked = time.time()
                    if sc.default_speaker().name != speaker.name:
                        return
            if mic_rec:
                mic_rec.__exit__(None, None, None)
    except Exception:
        return


def _stretch(block, n):
    """Linear resample of one block to n samples (only ever +-1 sample)."""
    x_old = np.linspace(0.0, 1.0, len(block))
    x_new = np.linspace(0.0, 1.0, n)
    return np.stack([np.interp(x_new, x_old, block[:, c]) for c in range(block.shape[1])], axis=1).astype(np.float32)


def _silence(speaker, run):
    """Plays silence so loopback never goes quiet. Ends with its run, so a
    watchdog restart does not leave one more of these behind each time."""
    zeros = np.zeros((BLOCK * 5, CH), np.float32)
    try:
        with speaker.player(samplerate=RATE, channels=CH) as p:
            while not run.is_set():
                p.play(zeros)
    except Exception:
        pass


# ------------------------------------------------------------------ clips
def _broken_run_end(piece, later):
    """The last piece of an EARLIER recorder run (a later piece is in another
    run folder) that doesn't decode cleanly: left out of the clip. That only
    happens after a crash now (stop_ffmpeg finishes pieces properly)."""
    if not later or os.path.dirname(later[0]) == os.path.dirname(piece):
        return False
    r = subprocess.run([FFMPEG, "-v", "error", "-i", piece, "-f", "null", "-"],
                       capture_output=True, text=True, creationflags=NO_WINDOW)
    if r.stderr.strip():
        log("left a broken piece out of the clip:", os.path.basename(os.path.dirname(piece)), os.path.basename(piece))
        return True
    return False


def snapshot():
    """Copy the newest minute of the ring (including the piece being written
    right now) aside, so later cuts end exactly at this moment."""
    pieces = [p for p in _all_pieces() if os.path.getsize(p) > 0][-(LONGEST // SEG + 2):]   # across runs
    pieces = [p for i, p in enumerate(pieces) if not _broken_run_end(p, pieces[i + 1:])]
    if not pieces:
        return None
    os.makedirs(HOLD, exist_ok=True)
    old = sorted(os.listdir(HOLD))
    for name in old[:-2]:                                   # keep the last few presses only
        shutil.rmtree(os.path.join(HOLD, name), ignore_errors=True)
    snap = os.path.join(HOLD, datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    os.makedirs(snap)
    for i, p in enumerate(pieces):
        shutil.copyfile(p, os.path.join(snap, f"{i:03d}.ts"))
    with open(os.path.join(snap, "list.txt"), "w", encoding="utf-8") as fh:
        fh.writelines(f"file '{i:03d}.ts'\n" for i in range(len(pieces)))
    run_ff(["-f", "concat", "-safe", "0", "-i", os.path.join(snap, "list.txt"), "-c", "copy", os.path.join(snap, "all.ts")])
    return snap


WATERMARK = os.path.join(HERE, "watermark.png")   # "recorded with" + the bunny, top middle


def cut(snap, seconds, stamp):
    """The last `seconds` of a snapshot, as an mp4 in SAVE_DIR. A stream copy:
    the watermark is already in the pixels (burnt in while recording), so this
    takes a fraction of a second whatever the length.

    Returns the path, or None if nothing usable was written (E: missing, the
    snapshot already cleaned up...), so the caller never reports a clip that
    is not there."""
    source = os.path.join(snap, "all.ts")
    if not os.path.exists(source):
        return None
    try:
        os.makedirs(SAVE_DIR, exist_ok=True)
    except OSError:
        return None
    label = dict(LENGTHS).get(seconds, f"{seconds}s")
    out = os.path.join(SAVE_DIR, f"clip {stamp} ({label}).mp4")
    # The snapshot runs TAIL_S past the F8 press (see Press.take), so the clip
    # ends TAIL_S before the snapshot's end: exactly at F8. It STARTS on the
    # last keyframe at or before (F8 - seconds), with both streams from there:
    # a stream copy can only begin a picture on a keyframe, and letting ffmpeg
    # seek on its own started the video at the NEXT one, so a 1min clip opened
    # on 0.78 s of sound with no picture. A clip may run up to 1 s over its
    # label instead.
    begin, end = _snapshot_span(source)
    if end is None:
        return None
    stop_at = end - TAIL_S
    want = stop_at - seconds
    keys = _keyframes(source)
    start = max([k for k in keys if k <= want + 0.001], default=keys[0] if keys else begin)
    # -ss counts from the START OF THE FILE (the snapshot's timeline begins at
    # ~1.4 s), not in its timestamps: passing the raw keyframe time landed a
    # second late, past the keyframe.
    run_ff(["-ss", f"{start - begin:.3f}", "-i", source, "-t", f"{stop_at - start:.3f}", "-c", "copy",
            "-bsf:a", "aac_adtstoasc", "-movflags", "+faststart", out])
    ok = os.path.exists(out) and os.path.getsize(out) > 1024
    log("saved" if ok else "SAVE FAILED", repr(os.path.basename(out)),
        f"{os.path.getsize(out) // 1024} KB" if ok else "")
    return out if ok else None


FFPROBE = find_tool("ffprobe.exe")


def _probe(args):
    r = subprocess.run([FFPROBE, "-v", "error", *args], capture_output=True, text=True, creationflags=NO_WINDOW)
    return r.stdout


def _snapshot_span(source):
    """(start, end) of a snapshot on its own timeline, in seconds."""
    try:
        start, dur = (float(x) for x in _probe(["-show_entries", "format=start_time,duration",
                                                 "-of", "csv=p=0", source]).strip().split(","))
        return start, start + dur
    except ValueError:
        return None, None


def _keyframes(source):
    """Timestamps of the snapshot's video keyframes (one a second)."""
    out = _probe(["-select_streams", "v", "-show_entries", "packet=pts_time,flags", "-of", "csv=p=0", source])
    keys = []
    for line in out.splitlines():
        parts = line.split(",")
        if len(parts) >= 2 and "K" in parts[1]:
            try:
                keys.append(float(parts[0]))
            except ValueError:
                pass
    return sorted(keys)


def unique_stamp():
    """A file stamp no other press has used: two F8 presses within the same
    second used to get the same name, and the second clip overwrote the first."""
    base = datetime.datetime.now().strftime("%Y-%m-%d %H-%M-%S")
    stamp, n = base, 2
    while stamp in unique_stamp.used or any(f.startswith(f"clip {stamp} (") for f in _save_dir_names()):
        stamp, n = f"{base} #{n}", n + 1
    unique_stamp.used.add(stamp)
    return stamp


unique_stamp.used = set()


def _save_dir_names():
    try:
        return os.listdir(SAVE_DIR)
    except OSError:
        return []


TAIL_S = 1.0   # how long after F8 the snapshot is taken; see Press.take


class Press:
    """One F8 press: its snapshot and the clip currently saved from it.

    The press time is noted the instant F8 lands; the snapshot is taken TAIL_S
    later and every cut ends TAIL_S before the snapshot's end, i.e. exactly at
    the press. Why wait: sound reaches the ring almost at once, but a video
    frame spends ~0.7 s in the encoder, so a snapshot taken AT the press had
    sound up to the press and picture only up to ~0.7 s before it, and every
    clip ended on a frozen frame (a 1min clip: video 59.24 s, audio 59.93 s)."""

    ALL = []                                              # every press this run, for a clean quit

    @classmethod
    def wait_all(cls, limit=120):
        """Quitting mid-save would leave a half-written, unplayable clip."""
        end = time.time() + limit
        while any(p.busy for p in cls.ALL) and time.time() < end:
            time.sleep(0.1)

    def __init__(self, on_change=lambda: None):
        Press.ALL = [p for p in Press.ALL if p.busy][-20:] + [self]   # don't grow forever at 24/7
        self.pressed = time.time()
        self.stamp = unique_stamp()
        self.snap = None
        self.ready = threading.Event()                    # set once the snapshot is taken (or failed)
        self.seconds = settings()["defaultSeconds"]       # the length asked for (may change before the first cut)
        self.saved_seconds = None                         # the length of the file at self.path
        self.path = None
        self.failed = False
        self.busy = True                                  # "saving…" until the snapshot is in and cut
        self.lock = threading.Lock()
        self.on_change = on_change

    def take(self):
        """The snapshot, TAIL_S after the press (see the class note)."""
        time.sleep(max(0.0, self.pressed + TAIL_S - time.time()))
        self.snap = snapshot()
        self.ready.set()
        if not self.snap:
            self.busy = False                             # "nothing recorded yet"
            self.on_change()

    # --- what the toast shows for this press
    def title(self):
        label = SHOW_LEN[self.seconds]
        if self.busy:                                     # includes the TAIL_S before the snapshot
            return f"Saving {label}"
        if not self.snap:
            return "Nothing recorded yet"
        if self.failed:
            return f"Couldn't save {label}"
        return f"{label} saved"

    def sub(self):
        return "" if (self.ready.is_set() and not self.snap) else "Click to change the length"

    def status(self):
        """The mark on the right: spinner while saving, tick when the file is
        written, cross if it failed."""
        if self.failed:
            return "failed"
        if self.busy:
            return "saving"
        return "done" if self.snap else ""

    def save(self, seconds=None):
        if not self.snap:
            return
        with self.lock:                                   # one cut at a time per press
            seconds = seconds or self.seconds
            if seconds == self.saved_seconds and self.path:
                self.busy = False                         # already cut at that length
                self.on_change()
                return
            self.seconds, self.busy, self.failed = seconds, True, False
            self.on_change()
            new = cut(self.snap, seconds, self.stamp)
            if new is None:
                # Nothing written: keep whatever clip this press already had
                # (never delete a good file for a failed one) and say so.
                self.busy, self.failed = False, True
                self.on_change()
                winsound.Beep(300, 150)
                return
            if self.path and self.path != new:
                try:
                    os.remove(self.path)
                except OSError:
                    pass
            self.path, self.saved_seconds, self.busy = new, seconds, False
            self.on_change()
            click_sound()
            announce(new, seconds, "clip")                                 # the moment the file is really there

    def change(self, seconds):
        """A length picked in the toast. Picking works AT ONCE, even before the
        snapshot is in (it used to ignore clicks for the first second or two,
        so it took several clicks): the toast switches to "saving 15s…" right
        away, and the cut happens as soon as the snapshot exists."""
        self.seconds, self.busy = seconds, True
        self.on_change()
        self.ready.wait(30)
        if self.snap:
            self.save(seconds)


# ------------------------------------------------------------------ full recordings
REC_TMP = os.path.join(SAVE_DIR, ".recording")   # pieces kept on the same drive as the result


def apply_save_dir():
    """The save folder changed in settings: clips go to the new one from now on."""
    global SAVE_DIR, REC_TMP
    SAVE_DIR = settings()["saveDir"]
    REC_TMP = os.path.join(SAVE_DIR, ".recording")
ENCODE_LAG_S = 0.7                                  # a frame reaches the ring ~0.7 s after it was on screen


def _newest_piece():
    pieces = _all_pieces()
    return pieces[-1] if pieces else None


def _fmt_len(s):
    s = int(max(0, s))
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


class Recording:
    """A full recording, started and stopped from the island's record button
    (or the tray menu).

    IT COSTS ALMOST NOTHING. The ring recorder is already encoding 1080p60 (x264)
    all the time; a recording only keeps each 2 s piece as it
    completes, before the ring overwrites it, and on stop joins them with a
    stream copy into one mp4. No second capture, no second encode, same HD
    quality and watermark as the clips.

    The piece being written when the button is pressed began up to 2 s
    earlier; that lead-in is cut off (on the keyframe at or before the press),
    and the end is cut TAIL_S after the stop press like a clip."""

    CURRENT = None                                         # the one running now, if any

    def __init__(self, on_change=lambda: None):
        self.started = time.time()
        self.stopped = None
        self.stamp = unique_stamp()
        self.dir = os.path.join(REC_TMP, self.stamp)
        self.busy = False                                  # saving
        self.failed = False
        self.path = None
        self.on_change = on_change
        self.pieces = []
        self.head = 0.0                                    # seconds of the first piece from before the press
        Recording.CURRENT = self
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        log("recording started", self.stamp)

    @property
    def running(self):
        return self.stopped is None

    def stop(self):
        if self.stopped is None:
            self.stopped = time.time()
            self.busy = True
            log("recording stop requested after", _fmt_len(self.stopped - self.started))
            self.on_change()

    # --- collecting the pieces
    def _run(self):
        try:
            os.makedirs(self.dir, exist_ok=True)
        except OSError as e:
            log("RECORDING FAILED: no folder", e)
            self.stopped = self.stopped or time.time()
            return self._done(None)
        cur, first, final, changed = _newest_piece(), True, None, time.time()
        while True:
            time.sleep(0.1)
            n = _newest_piece()
            if final is None and self.stopped and time.time() >= self.stopped + TAIL_S:
                final = cur                                # the piece holding the stop moment
                final_at = time.time()
            if n != cur:                                   # `cur` is complete
                if cur:
                    first = self._keep(cur, first)
                done = final is not None
                cur, changed = n, time.time()
                if done:
                    break
            elif final is not None and time.time() - final_at > SEG + 3:
                if cur:                                    # recorder paused/stalled: take it as it is
                    self._keep(cur, first)
                break
        self._done(self._join())

    def _keep(self, src, first):
        dst = os.path.join(self.dir, f"{len(self.pieces):05d}.ts")
        try:
            shutil.copyfile(src, dst)
        except OSError as e:
            log("recording: lost a piece", os.path.basename(src), e)   # the ring restarted under it
            return first
        if first:
            begin, end = _snapshot_span(dst)
            if end is not None:
                # It ends now (minus the encoder's lag), so it began `dur` before that.
                began = time.time() - ENCODE_LAG_S - (end - begin)
                self.head = min(max(0.0, self.started - began), end - begin)
        self.pieces.append(dst)
        return False

    def _join(self):
        if not self.pieces:
            return None
        listing = os.path.join(self.dir, "list.txt")
        with open(listing, "w", encoding="utf-8") as fh:
            fh.writelines(f"file '{os.path.basename(p)}'\n" for p in self.pieces)
        # Start on the first piece's keyframe at or before the press (a stream
        # copy can only start a picture on one). The concat timeline starts at 0.
        begin, _ = _snapshot_span(self.pieces[0])
        keys = [k - begin for k in _keyframes(self.pieces[0])] if begin is not None else []
        ss = max([k for k in keys if k <= self.head + 0.001], default=0.0)
        length = (self.stopped - self.started) + (self.head - ss)
        out = os.path.join(SAVE_DIR, f"recording {self.stamp}.mp4")
        run_ff(["-f", "concat", "-safe", "0", "-ss", f"{ss:.3f}", "-i", listing, "-t", f"{length:.3f}",
                "-c", "copy", "-bsf:a", "aac_adtstoasc", "-movflags", "+faststart", out])
        ok = os.path.exists(out) and os.path.getsize(out) > 1024
        log("recording saved" if ok else "RECORDING SAVE FAILED", repr(os.path.basename(out)),
            f"{os.path.getsize(out) // 1024} KB" if ok else "", "pieces", len(self.pieces))
        return out if ok else None

    def _done(self, path):
        shutil.rmtree(self.dir, ignore_errors=True)
        self.path, self.failed, self.busy = path, path is None, False
        if Recording.CURRENT is self:
            Recording.CURRENT = None
        self.on_change()
        if path:
            click_sound()
            announce(path, round(self.length()), "recording")
        else:
            winsound.Beep(300, 150)

    # --- what the toast shows
    def length(self):
        return (self.stopped or time.time()) - self.started

    def title(self):
        if self.running:
            return "Recording"
        if self.busy:
            return f"Saving {_fmt_len(self.length())} recording"
        if self.failed:
            return "Couldn't save the recording"
        return f"{_fmt_len(self.length())} recording saved"

    def sub(self):
        if self.running:
            return ""                                      # just "Recording": the red dot says the rest
        return "Click to show it" if self.path else ""

    def status(self):
        return "rec" if self.running else "failed" if self.failed else "saving" if self.busy else "done"

    def click(self):
        if self.path and os.path.exists(self.path):
            subprocess.Popen(["explorer", "/select,", self.path])


# ------------------------------------------------------------------ toast
# A modern card, bottom-right above the taskbar (toastui.py draws it): soft
# shadow, smooth corners, fades and slides in, waits (longer while hovered),
# fades out. Click it for the length picker, which opens INSIDE the card.
#
# It is a LAYERED Win32 window (UpdateLayeredWindow: per-pixel alpha) with its
# OWN thread and message loop. NOT on the Tk thread: a ctypes window procedure
# called from inside Tk's mainloop crashed Python ("PyEval_RestoreThread: the
# function must be called with the GIL held", 2026-09-27). Tk now only runs the
# 1 px heartbeat. It is
# WS_EX_NOACTIVATE: clicking it never takes focus from the game (which also
# kept the recorder from switching away from a fullscreen game's window).
import numpy as _np
import toastui

SHOW_LEN = {15: "15s", 30: "30s", 60: "1 min"}              # how lengths read on screen
PICK = [(secs, SHOW_LEN[secs]) for secs, _ in LENGTHS]


def work_area():
    r = wt.RECT()
    ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0)   # SPI_GETWORKAREA
    return r.left, r.top, r.right, r.bottom


def ease_out(t):
    return 1 - (1 - t) ** 3


def ease_in(t):
    return t ** 3


class _BMIH(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                ("biBitCount", wt.WORD), ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD)]


class _BLEND(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


class _TRACK(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("dwFlags", wt.DWORD), ("hwndTrack", wt.HWND), ("dwHoverTime", wt.DWORD)]


class Layered:
    """One borderless, topmost, never-activated window showing an RGBA image."""

    CLASS = "clipper-toast"
    _proc = None

    def __init__(self, on_mouse):
        self.on_mouse = on_mouse                       # (event, x, y) with event in move / leave / click
        g, U = ctypes.windll.gdi32, ctypes.windll.user32
        self.g, self.U = g, U
        g.CreateCompatibleDC.restype = wt.HDC
        g.CreateCompatibleDC.argtypes = [wt.HDC]
        g.CreateDIBSection.restype = wt.HBITMAP
        g.CreateDIBSection.argtypes = [wt.HDC, ctypes.c_void_p, wt.UINT, ctypes.POINTER(ctypes.c_void_p), wt.HANDLE, wt.DWORD]
        g.SelectObject.restype = wt.HGDIOBJ
        g.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
        g.DeleteObject.argtypes = [wt.HGDIOBJ]
        g.DeleteDC.argtypes = [wt.HDC]
        U.GetDC.restype = wt.HDC
        U.GetDC.argtypes = [wt.HWND]
        U.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
        U.UpdateLayeredWindow.argtypes = [wt.HWND, wt.HDC, ctypes.POINTER(wt.POINT), ctypes.POINTER(wt.SIZE), wt.HDC,
                                          ctypes.POINTER(wt.POINT), wt.COLORREF, ctypes.POINTER(_BLEND), wt.DWORD]
        U.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
        U.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT]
        U.TrackMouseEvent.argtypes = [ctypes.POINTER(_TRACK)]
        U.LoadCursorW.restype = wt.HANDLE
        U.LoadCursorW.argtypes = [wt.HINSTANCE, ctypes.c_void_p]
        U.SetCursor.argtypes = [wt.HANDLE]

        def proc(hwnd, msg, wp, lp):
            x, y = ctypes.c_short(lp & 0xFFFF).value, ctypes.c_short((lp >> 16) & 0xFFFF).value
            if msg == 0x0021:                          # WM_MOUSEACTIVATE: never take focus
                return 3                               # MA_NOACTIVATE
            if msg == 0x0200:                          # WM_MOUSEMOVE
                if not self.tracking:
                    self.tracking = True
                    U.TrackMouseEvent(ctypes.byref(_TRACK(ctypes.sizeof(_TRACK), 0x2, hwnd, 0)))   # TME_LEAVE
                self.on_mouse("move", x, y)
                return 0
            if msg == 0x02A3:                          # WM_MOUSELEAVE
                self.tracking = False
                self.on_mouse("leave", 0, 0)
                return 0
            if msg == 0x0202:                          # WM_LBUTTONUP
                self.on_mouse("click", x, y)
                return 0
            if msg == 0x0020:                          # WM_SETCURSOR: a hand, it is clickable
                U.SetCursor(U.LoadCursorW(None, ctypes.c_void_p(32649)))
                return 1
            return U.DefWindowProcW(hwnd, msg, wp, lp)

        if Layered._proc is None:
            Layered._proc = WNDPROC(proc)
            wc = WNDCLASSW(lpfnWndProc=Layered._proc, hInstance=k32.GetModuleHandleW(None), lpszClassName=self.CLASS)
            U.RegisterClassW(ctypes.byref(wc))
        else:
            raise RuntimeError("one toast window only")
        # WS_EX_LAYERED | TOOLWINDOW | TOPMOST | NOACTIVATE, WS_POPUP
        self.hwnd = U.CreateWindowExW(0x00080000 | 0x80 | 0x8 | 0x08000000, self.CLASS, "clipper toast",
                                      0x80000000, 0, 0, 1, 1, None, None, k32.GetModuleHandleW(None), None)
        # Kept out of screen capture (WDA_EXCLUDEFROMCAPTURE) unless the user
        # wants it in clips: the recorder films the whole screen, and the
        # toast pops up right at F8.
        self.apply_affinity()
        self.tracking = False
        self.visible = False
        self.bmp = self.mdc = None
        self.size = (1, 1)

    def apply_affinity(self):
        if self.hwnd:
            ctypes.windll.user32.SetWindowDisplayAffinity(self.hwnd, 0 if settings()["toastInClips"] else 0x11)

    def set_image(self, img):
        """Replace the picture (PIL RGBA). Premultiplied BGRA, as layered windows want."""
        a = _np.asarray(img, dtype=_np.uint16)
        rgb = (a[..., :3] * a[..., 3:4] + 127) // 255
        bgra = _np.dstack([rgb[..., 2], rgb[..., 1], rgb[..., 0], a[..., 3]]).astype(_np.uint8)
        w, h = img.size
        g, U = self.g, self.U
        screen = U.GetDC(None)
        mdc = g.CreateCompatibleDC(screen)
        bmi = _BMIH(ctypes.sizeof(_BMIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        bits = ctypes.c_void_p()
        bmp = g.CreateDIBSection(mdc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        ctypes.memmove(bits, bgra.tobytes(), w * h * 4)
        g.SelectObject(mdc, bmp)
        U.ReleaseDC(None, screen)
        old = (self.mdc, self.bmp)
        self.mdc, self.bmp, self.size = mdc, bmp, (w, h)
        if old[0]:
            g.DeleteDC(old[0])
            g.DeleteObject(old[1])

    def present(self, x, y, alpha):
        if not self.mdc:
            return
        screen = self.U.GetDC(None)
        self.U.UpdateLayeredWindow(self.hwnd, screen, ctypes.byref(wt.POINT(int(x), int(y))),
                                   ctypes.byref(wt.SIZE(*self.size)), self.mdc, ctypes.byref(wt.POINT(0, 0)), 0,
                                   ctypes.byref(_BLEND(0, 0, max(0, min(255, int(alpha))), 1)), 0x2)   # ULW_ALPHA
        self.U.ReleaseDC(None, screen)
        if not self.visible:
            self.visible = True
            self.U.ShowWindow(self.hwnd, 4)                               # SW_SHOWNOACTIVATE
        self.U.SetWindowPos(self.hwnd, wt.HWND(-1), 0, 0, 0, 0, 0x1 | 0x2 | 0x10)   # stay topmost, no activate

    def hide(self):
        if self.visible:
            self.visible = False
            self.U.ShowWindow(self.hwnd, 0)


class Note:
    """A plain little message ("Hop is up to date")."""
    busy = False

    def __init__(self, title, sub=""):
        self._t, self._s = title, sub

    def title(self):
        return self._t

    def sub(self):
        return self._s

    def status(self):
        return "done"


class UpdateNotice:
    """The "Update available" card: stays up until Update now (opens the
    release page) or Later (quiet until the next start of the PC)."""
    busy = False

    def __init__(self, version, url):
        self.version, self.url = version, url

    def title(self):
        return "Update available"

    def sub(self):
        return f"Hop v{self.version} is ready"

    def status(self):
        return "update"


class Toast:
    DONE_MS = 2500      # after "saved", then it fades away
    PICK_MS = 6000      # after opening the length picker
    IN_MS, OUT_MS = 300, 220

    def __init__(self):
        self.q = queue.Queue()                          # for the card's thread: show / retitle
        self.bq = queue.Queue()                         # for the Tk thread: heartbeat on / off
        self.ready = threading.Event()
        self.tk_ready = threading.Event()
        threading.Thread(target=self._run_tk, daemon=True).start()
        threading.Thread(target=self._run, daemon=True).start()
        self.ready.wait(5)
        self.tk_ready.wait(5)

    def show(self, press):
        self.q.put(("show", press))

    def heartbeat(self, on):
        """Called by the recorder's watchdog when the screen has gone still."""
        self.bq.put(on)

    # --- a tiny timer queue for the card's thread (instead of Tk's after)
    def _after(self, ms, fn):
        self._timer_n += 1
        self._timers[self._timer_n] = (time.perf_counter() + ms / 1000, fn)
        return self._timer_n

    def _cancel(self, tid):
        self._timers.pop(tid, None)

    def _run_tk(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.beat_win = None

        def poll():
            try:
                while True:
                    self._beat(self.bq.get_nowait())
            except queue.Empty:
                pass
            self.root.after(100, poll)
        self.root.after(100, poll)
        self.tk_ready.set()
        self.root.mainloop()

    # --- the heartbeat: a 1 px, almost invisible window in the top-left corner
    # that changes 60 times a second while on, so Graphics Capture keeps
    # delivering frames on a still screen (see keep_recording).
    def _beat(self, on):
        if on and not self.beat_win:
            w = self.beat_win = tk.Toplevel(self.root)
            w.overrideredirect(True)
            w.attributes("-topmost", True)
            w.geometry("1x1+0+0")
            w.configure(bg="#000000")
            self.beat_n = 0
            self._beat_step()
        elif not on and self.beat_win:
            try:
                self.beat_win.destroy()
            except tk.TclError:
                pass
            self.beat_win = None

    def _beat_step(self):
        if not self.beat_win:
            return
        self.beat_n ^= 1
        try:
            self.beat_win.attributes("-alpha", 0.02 if self.beat_n else 0.03)
            self.root.after(16, self._beat_step)
        except tk.TclError:
            self.beat_win = None

    def _run(self):
        self._timers, self._timer_n = {}, 0
        self.s = u32.GetDpiForSystem() / 96.0                    # display scale
        self.win = Layered(self._mouse)
        self.press = None
        self.picker = False
        self.hover = False
        self.hover_len = None
        self.hits = {}
        self.hide_id = None
        self.anim = None                                         # (kind "in"/"out", started)
        self.shown = False
        self.spin = 0.0
        self.frame_id = None
        self.ready.set()
        msg = wt.MSG()
        u32.PeekMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT, wt.UINT]
        u32.MsgWaitForMultipleObjects.argtypes = [wt.DWORD, ctypes.c_void_p, wt.BOOL, wt.DWORD, wt.DWORD]
        while True:
            try:
                while True:
                    what, arg = self.q.get_nowait()
                    if what == "show":
                        self._show(arg)
                    elif what == "retitle":
                        self._retitle()
            except queue.Empty:
                pass
            except Exception as e:
                log("toast error", repr(e))
            now = time.perf_counter()
            for tid, (when, fn) in sorted(self._timers.items(), key=lambda kv: kv[1][0]):
                if when <= now and self._timers.pop(tid, None):
                    try:
                        fn()
                    except Exception as e:
                        log("toast error", repr(e))
            while u32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):          # PM_REMOVE
                u32.TranslateMessage(ctypes.byref(msg))
                u32.DispatchMessageW(ctypes.byref(msg))
            nxt = min((w for w, _ in self._timers.values()), default=now + 0.04)
            wait = max(0, min(40, int((nxt - time.perf_counter()) * 1000)))
            u32.MsgWaitForMultipleObjects(0, None, False, wait, 0x04FF)         # QS_ALLINPUT

    # --- drawing
    def _state(self):
        p = self.press
        status = p.status() if p else ""
        if status != getattr(self, "_mark", None):                  # a new mark: its animation starts now
            self._mark, self._mark_t0 = status, time.perf_counter()
        st = {"title": p.title() if p else "Nothing recorded yet", "sub": p.sub() if p else "",
              "status": status, "spin": self.spin, "hover": self.hover,
              "t": time.perf_counter() - self._mark_t0}
        if self.picker and isinstance(p, Press):
            st["sub"] = "Pick a length"
            st["picker"] = {"options": PICK, "selected": p.seconds, "hover": self.hover_len}
        if isinstance(p, UpdateNotice):
            st["buttons"] = {"items": [("go", "Update now"), ("later", "Later")], "hover": getattr(self, "hover_btn", None)}
        return st

    def _redraw(self):
        img, self.hits = toastui.render(self._state(), self.s)
        self.win.set_image(img)
        self._place()

    def _spot(self):
        """Top-left of the window with the card's bottom-right 16 px inside the work area."""
        l, t, r, b = work_area()
        w, h = self.win.size
        m = round(toastui.MARGIN * self.s)
        gap = round(16 * self.s)
        return r - gap - (w - m), b - gap - (h - m)

    def _place(self):
        """Put the window where the animation says, with its fade."""
        x, y = self._spot()
        alpha, dx = 255, 0
        if self.anim:
            kind, t0, ms = self.anim
            p = min(1.0, (time.perf_counter() - t0) * 1000 / ms)
            if kind == "in":
                e = ease_out(p)
                alpha, dx = 255 * e, round(36 * self.s) * (1 - e)
            else:
                e = ease_in(p)
                alpha, dx = 255 * (1 - e), round(24 * self.s) * e
        if self.press and self.press.status() == "failed":
            k = time.perf_counter() - getattr(self, "_mark_t0", 0) - 0.6        # a short shake after the cross
            if 0 < k < 0.42:
                dx += round(5 * self.s * math.sin(k * 45) * (1 - k / 0.42))
        self.win.present(x + dx, y, alpha)

    def _tick(self):
        """One animation frame: slide/fade, and the spinner or recording dot."""
        self.frame_id = None
        kind = self.press.status() if self.press else ""
        animating = kind in ("done", "failed") and time.perf_counter() - getattr(self, "_mark_t0", 0) < toastui.DONE_LEN
        busy_mark = self.shown and self.press and (kind in ("saving", "rec", "update") or animating)
        if busy_mark:
            self.spin = (self.spin + 0.033 / {"saving": 0.8, "rec": 1.4, "update": 1.3}.get(kind, 1.0)) % 1.0
            img, self.hits = toastui.render(self._state(), self.s)
            self.win.set_image(img)
        if self.anim:
            kind, t0, ms = self.anim
            if (time.perf_counter() - t0) * 1000 >= ms:
                self.anim = None
                if kind == "out":
                    self.win.hide()
                    self.shown = False
                    self.picker = False
                    return
        self._place()
        if self.anim or busy_mark:
            self.frame_id = self._after(16 if self.anim else 33, self._tick)

    def _kick(self):
        if not self.frame_id:
            self.frame_id = self._after(0, self._tick)

    # --- showing / hiding
    def _show(self, press):
        self.press = press
        self.picker = False
        self.hover_len = None
        self._redraw_image_only()
        if not self.shown or (self.anim and self.anim[0] == "out"):
            self.shown = True
            self.anim = ("in", time.perf_counter(), self.IN_MS)
        self._kick()
        self._arm_hide(self.DONE_MS)                    # held while "saving", re-armed when saved

    def _redraw_image_only(self):
        img, self.hits = toastui.render(self._state(), self.s)
        self.win.set_image(img)

    def _arm_hide(self, ms):
        if self.hide_id:
            self._cancel(self.hide_id)
        self.hide_id = self._after(ms, self._hide)

    def _pointer_over(self):
        pt = wt.POINT()
        u32.GetCursorPos(ctypes.byref(pt))
        if not self.shown or "card" not in self.hits:
            return False
        x, y = self._spot()
        l, t, r, b = self.hits["card"]
        return x + l <= pt.x < x + r and y + t <= pt.y < y + b

    def _hide(self):
        self.hide_id = None
        if not self.shown:
            return
        if isinstance(self.press, UpdateNotice) and not getattr(self.press, "answered", False):
            return                                       # stays until Update now / Later
        if self._pointer_over() or (self.press and self.press.busy and self.press.status() != "rec"):
            return self._arm_hide(800)                   # never leave while it still says "Saving"
        self.anim = ("out", time.perf_counter(), self.OUT_MS)
        self._kick()

    def _retitle(self):
        if not self.shown:
            return
        self._redraw()
        self._kick()
        if self.press and not self.press.busy and not self.picker:
            self._arm_hide(self.DONE_MS)                # "saved" -> gone ~2.5 s later, like Medal

    # --- the mouse (window coordinates)
    def _mouse(self, ev, x, y):
        if ev == "leave":
            if self.hover or self.hover_len:
                self.hover, self.hover_len = False, None
                self._redraw()
            return
        inside = lambda box: box[0] <= x < box[2] and box[1] <= y < box[3]
        on_card = inside(self.hits.get("card", (0, 0, 0, 0)))
        over = next((secs for secs, _ in PICK if f"len{secs}" in self.hits and inside(self.hits[f"len{secs}"])), None)
        btn = next((k[4:] for k in self.hits if k.startswith("btn_") and inside(self.hits[k])), None)
        if ev == "move":
            if on_card != self.hover or over != self.hover_len or btn != getattr(self, "hover_btn", None):
                self.hover, self.hover_len, self.hover_btn = on_card, over, btn
                self._redraw()
            return
        if ev == "click" and btn and isinstance(self.press, UpdateNotice):
            return self._answer(btn)
        if ev == "click" and on_card:
            self._click(over)

    def _answer(self, btn):
        """Update now: the latest release's page in the browser. Later: quiet
        until the next start of the PC (the notice comes back then)."""
        notice = self.press
        notice.answered = True
        if btn == "go":
            try:
                os.startfile(notice.url)
            except OSError:
                pass
        self.anim = ("out", time.perf_counter(), self.OUT_MS)
        self._kick()

    def _click(self, over):
        p = self.press
        if isinstance(p, Recording):
            p.click()                                   # show the saved file
            return
        if not isinstance(p, Press):
            return
        if self.picker and over is not None:
            return self._pick(over)
        # Opens AT ONCE, even while the snapshot is still being taken; a pick
        # made then is cut as soon as it exists (see Press.change).
        if not self.picker and p.ready.is_set() and not p.snap:
            return
        self.picker = not self.picker
        self._redraw()
        self._arm_hide(self.PICK_MS if self.picker else self.DONE_MS)

    def _pick(self, seconds):
        press = self.press                            # (the click plays when the re-cut is saved)
        self.picker = False
        press.seconds, press.busy = seconds, True     # "Saving 15s" on screen right now
        self._redraw()
        self._kick()

        def work():                                   # re-cut off the UI thread,
            press.change(seconds)                     # then retitle through the queue
            self.q.put(("retitle", None))             # (Tk may only be touched from its own thread)
        threading.Thread(target=work, daemon=True).start()
        self._arm_hide(self.DONE_MS)


# ---------------------------------------------------------------- tray icon
# The bunny in the notification area, drawn with Shell_NotifyIcon through
# ctypes (no extra packages). A hidden window receives both the tray clicks and
# the hotkeys, so the whole program is one message loop.
u32, sh32, k32 = ctypes.windll.user32, ctypes.windll.shell32, ctypes.windll.kernel32
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
u32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
u32.DefWindowProcW.restype = LRESULT
# 64-bit handles: without these, ctypes passes and returns them as 32-bit ints
# and CreateWindowExW overflows on the module handle.
k32.GetModuleHandleW.restype = wt.HMODULE
u32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, ctypes.c_void_p]
u32.CreateWindowExW.restype = wt.HWND
u32.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT]
u32.DestroyWindow.argtypes = [wt.HWND]
u32.SetForegroundWindow.argtypes = [wt.HWND]
u32.AppendMenuW.argtypes = [wt.HMENU, wt.UINT, ctypes.c_size_t, wt.LPCWSTR]
u32.DestroyMenu.argtypes = [wt.HMENU]
u32.LoadImageW.argtypes = [wt.HINSTANCE, wt.LPCWSTR, wt.UINT, ctypes.c_int, ctypes.c_int, wt.UINT]
u32.LoadImageW.restype = wt.HANDLE
u32.CreatePopupMenu.restype = wt.HMENU
u32.TrackPopupMenu.argtypes = [wt.HMENU, wt.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND, ctypes.c_void_p]
sh32.Shell_NotifyIconW.argtypes = [wt.DWORD, ctypes.c_void_p]

WM_DESTROY, WM_HOTKEY, WM_TRAY = 0x0002, 0x0312, 0x8001
# Sent by the Lyrics Island (or anything) to the "clipper-tray" window:
#   WM_REC_START / WM_REC_STOP / WM_REC_TOGGLE   start / stop a full recording
#   WM_REC_QUERY  returns when the running recording started (ms since 1970), or 0
WM_REC_START, WM_REC_STOP, WM_REC_TOGGLE, WM_REC_QUERY = 0x8000 + 10, 0x8000 + 11, 0x8000 + 12, 0x8000 + 13
WM_CLIP_RELOAD = 0x8000 + 14             # settings.json changed (Hop Island's settings app)


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD), ("Data4", ctypes.c_ubyte * 8)]


# {6FE69556-704A-47A0-8F24-C28D936FDA47}: the console display turning off / on / dim.
GUID_CONSOLE_DISPLAY_STATE = GUID(0x6FE69556, 0x704A, 0x47A0, (ctypes.c_ubyte * 8)(0x8F, 0x24, 0xC2, 0x8D, 0x93, 0x6F, 0xDA, 0x47))


class POWERBROADCAST_SETTING(ctypes.Structure):
    _fields_ = [("PowerSetting", GUID), ("DataLength", wt.DWORD), ("Data", ctypes.c_ubyte * 4)]
WM_LBUTTONDBLCLK, WM_RBUTTONUP = 0x0203, 0x0205
NIM_ADD, NIM_DELETE = 0, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 1, 2, 4
CMD_SAVE, CMD_OPEN, CMD_QUIT, CMD_REC, CMD_UPDATE = 1, 2, 3, 4, 5


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON), ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH),
                ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("hWnd", wt.HWND), ("uID", wt.UINT), ("uFlags", wt.UINT),
                ("uCallbackMessage", wt.UINT), ("hIcon", wt.HICON), ("szTip", wt.WCHAR * 128),
                ("dwState", wt.DWORD), ("dwStateMask", wt.DWORD), ("szInfo", wt.WCHAR * 256),
                ("uVersion", wt.UINT), ("szInfoTitle", wt.WCHAR * 64), ("dwInfoFlags", wt.DWORD),
                ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", wt.HICON)]


class Tray:
    nid = None
    added = False

    @classmethod
    def add(cls, hwnd):
        icon = u32.LoadImageW(None, ICON, 1, 0, 0, 0x10 | 0x40)       # IMAGE_ICON, LR_LOADFROMFILE | LR_DEFAULTSIZE
        nid = NOTIFYICONDATAW(cbSize=ctypes.sizeof(NOTIFYICONDATAW), hWnd=hwnd, uID=1,
                              uFlags=NIF_MESSAGE | NIF_ICON | NIF_TIP, uCallbackMessage=WM_TRAY, hIcon=icon)
        nid.szTip = f"{APP_NAME} - F8 saves the last {settings()['defaultSeconds']} s"
        cls.added = bool(sh32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)))
        cls.nid = nid

    @classmethod
    def remove(cls):
        if cls.nid:
            sh32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(cls.nid))


def menu(hwnd):
    m = u32.CreatePopupMenu()
    u32.AppendMenuW(m, 0, CMD_SAVE, f"Save last {settings()['defaultSeconds']} s\tF8")
    u32.AppendMenuW(m, 0, CMD_REC, "Stop recording" if Recording.CURRENT and Recording.CURRENT.running
                    else "Start recording")
    u32.AppendMenuW(m, 0, CMD_OPEN, "Open clips folder")
    u32.AppendMenuW(m, 0, CMD_UPDATE, "Check for updates")
    u32.AppendMenuW(m, 0x800, 0, None)                                   # separator
    u32.AppendMenuW(m, 0, CMD_QUIT, "Quit\tCtrl+Shift+F8")
    pt = wt.POINT(); u32.GetCursorPos(ctypes.byref(pt))
    u32.SetForegroundWindow(hwnd)                                        # so the menu closes on an outside click
    cmd = u32.TrackPopupMenu(m, 0x100 | 0x20, pt.x, pt.y, 0, hwnd, None)  # TPM_RETURNCMD | TPM_RIGHTBUTTON
    u32.DestroyMenu(m)
    return cmd


def open_folder():
    os.makedirs(SAVE_DIR, exist_ok=True)
    os.startfile(SAVE_DIR)


def main():
    MOD_CONTROL, MOD_SHIFT, VK_F8 = 0x2, 0x4, 0x77
    # ONE clipper at a time. It starts with Windows now, so running start.bat
    # as well used to throw an "F8 is already used" error box; a second copy
    # now just leaves quietly (the first one is already recording).
    # ...and the NEWEST copy wins: an older one is asked to quit the way
    # Ctrl+Shift+F8 does (every version knows it, and a full recording in
    # progress is still saved), then closed by force if it doesn't answer.
    mutex = take_over("Local\\clipper-bunny" + os.environ.get("HOP_TEST_INSTANCE", ""), TRAY_CLASS, WM_HOTKEY, 2, wait=12.0)
    if not mutex:
        sys.exit(0)
    # The startup shortcut from before Hop (pythonw on the old clipper.py)
    # brought the old clipper back at every sign-in.
    try:
        os.remove(os.path.join(os.environ["APPDATA"], r"Microsoft\Windows\Start Menu\Programs\Startup", "clipper.lnk"))
    except OSError:
        pass
    toast = Toast()
    later_this_session = []                          # "Later" pressed: quiet until the PC restarts

    def check_updates(by_hand=False):
        """Newer Hop on GitHub? Show the notice (with the island installed and
        the clipper running, the clipper is the one that shows it)."""
        got = latest_release()
        if got and version_tuple(got[0]) > version_tuple(VERSION):
            n = UpdateNotice(*got)
            later_this_session.append(n)
            toast.show(n)
            log("update available:", got[0])
        elif by_hand:
            toast.show(Note("Hop is up to date", f"You have v{VERSION}"))

    def update_loop():
        time.sleep(20)                                 # the PC has just started: let the network come up
        while True:
            if not any(getattr(n, "answered", False) for n in later_this_session):
                check_updates()
            time.sleep(24 * 3600)
    threading.Thread(target=update_loop, daemon=True).start()

    def save():
        log("F8 pressed;", foreground())
        press = Press(on_change=lambda: toast.q.put(("retitle", None)))
        toast.show(press)                               # at once, reading "saving 30s…"
        press.take()                                    # the snapshot, TAIL_S after the press
        press.save()                                    # a stream copy; then "✓ 30s saved" + click

    def rec_start():
        if Recording.CURRENT and Recording.CURRENT.running:
            return
        r = Recording(on_change=lambda: toast.q.put(("retitle", None)))
        toast.show(r)                                   # "● recording"

    def rec_stop():
        r = Recording.CURRENT
        if r and r.running:
            r.stop()
            toast.show(r)                               # "saving 2:14 recording…" -> "✓ saved"

    def act(cmd, hwnd):
        if cmd == CMD_REC:
            rec_stop() if Recording.CURRENT and Recording.CURRENT.running else rec_start()
        elif cmd == CMD_SAVE:
            threading.Thread(target=save, daemon=True).start()
        elif cmd == CMD_OPEN:
            open_folder()
        elif cmd == CMD_UPDATE:
            threading.Thread(target=check_updates, args=(True,), daemon=True).start()
        elif cmd == CMD_QUIT:
            u32.DestroyWindow(hwnd)

    rec = {}                                     # the current ffmpeg + pause/restart flags, for the watchdog

    # LOCK / SLEEP / SCREEN OFF pause the recorder; unlock / wake / screen on
    # restart it fresh. A capture left running through a lock came back stuck
    # on the lock screen with a dead sound device, and every clip after that
    # was frozen or audio-only (13:09-14:24, 2026-09-27). Windows sends:
    #   WM_WTSSESSION_CHANGE   lock (7) / unlock (8)       via WTSRegisterSessionNotification
    #   WM_POWERBROADCAST      suspend (4) / resume (0x12) / power-setting change
    #                          (console display off 0 / on 1 / dimmed 2)
    #   WM_DISPLAYCHANGE       resolution or monitor change: restart
    def pause(on):
        log("pause" if on else "unpause")
        rec["paused"] = on
        if on and rec.get("ff") is not None:
            # off the window's thread: a clean stop can take a moment
            threading.Thread(target=stop_ffmpeg, args=(rec["ff"],), daemon=True).start()

    def restart():
        log("restart (unlock / wake / screen on / display change)")
        was_paused, rec["paused"] = rec.get("paused"), False
        if not was_paused:                   # a paused loop starts a fresh recorder by itself;
            rec["run_id"] = "restart"        # flagging it too made that one restart at once

    def wndproc(hwnd, msg, wparam, lparam):
        if msg == WM_HOTKEY:
            if wparam in (1, 2):                 # 1 = F8, 2 = Ctrl+Shift+F8; nothing else quits
                act(CMD_SAVE if wparam == 1 else CMD_QUIT, hwnd)
            return 0
        if msg == WM_CLIP_RELOAD:
            log("settings changed:", settings())
            apply_save_dir()
            try:
                toast.apply_affinity()
            except Exception:
                pass
            if not (Recording.CURRENT and Recording.CURRENT.running):   # never cut a recording short
                rec["run_id"] = "restart"
            return 0
        if msg == WM_REC_QUERY:
            r = Recording.CURRENT
            return int(r.started * 1000) if r and r.running else 0
        if msg in (WM_REC_START, WM_REC_STOP, WM_REC_TOGGLE):
            running = bool(Recording.CURRENT and Recording.CURRENT.running)
            if msg == WM_REC_START or (msg == WM_REC_TOGGLE and not running):
                rec_start()
            else:
                rec_stop()
            r = Recording.CURRENT
            return int(r.started * 1000) if r and r.running else 0
        if msg == 0x02B1:                                        # WM_WTSSESSION_CHANGE
            if wparam == 7:                                      # WTS_SESSION_LOCK
                pause(True)
            elif wparam == 8:                                    # WTS_SESSION_UNLOCK
                restart()
            return 0
        if msg == 0x0218:                                        # WM_POWERBROADCAST
            if wparam == 0x4:                                    # PBT_APMSUSPEND
                pause(True)
            elif wparam in (0x7, 0x12):                          # PBT_APMRESUMESUSPEND / RESUMEAUTOMATIC
                restart()
            elif wparam == 0x8013 and lparam:                    # PBT_POWERSETTINGCHANGE
                ps = ctypes.cast(lparam, ctypes.POINTER(POWERBROADCAST_SETTING)).contents
                if bytes(ps.PowerSetting) == bytes(GUID_CONSOLE_DISPLAY_STATE) and ps.DataLength >= 4:
                    state = ps.Data[0]
                    if state == 0:
                        pause(True)                              # screen off
                    elif state == 1 and rec.get("paused"):
                        restart()                                # screen back on
            return 1
        if msg == 0x007E:                                        # WM_DISPLAYCHANGE
            restart()
            return 0
        if msg == WM_TRAY:
            if lparam & 0xFFFF == WM_LBUTTONDBLCLK:
                open_folder()
            elif lparam & 0xFFFF == WM_RBUTTONUP:
                act(menu(hwnd), hwnd)
            return 0
        if msg == WM_DESTROY:
            u32.PostQuitMessage(0)
            return 0
        return u32.DefWindowProcW(hwnd, msg, wparam, lparam)

    proc = WNDPROC(wndproc)                       # kept referenced for the program's life
    wc = WNDCLASSW(lpfnWndProc=proc, hInstance=k32.GetModuleHandleW(None), lpszClassName=TRAY_CLASS)
    u32.RegisterClassW(ctypes.byref(wc))
    hwnd = u32.CreateWindowExW(0, TRAY_CLASS, "clipper", 0, 0, 0, 0, 0, None, None, wc.hInstance, None)

    if not u32.RegisterHotKey(hwnd, 1, 0, VK_F8) or not u32.RegisterHotKey(hwnd, 2, MOD_CONTROL | MOD_SHIFT, VK_F8):
        winsound.Beep(300, 400)
        u32.MessageBoxW(None, "F8 is already used by another program (Medal?). Close it and start Hop Clipper again.", APP_NAME, 0x30)
        sys.exit(1)
    # Ask Windows for the lock/unlock and screen on/off messages handled above.
    ctypes.windll.wtsapi32.WTSRegisterSessionNotification(wt.HWND(hwnd), 0)   # NOTIFY_FOR_THIS_SESSION
    u32.RegisterPowerSettingNotification.restype = wt.HANDLE
    u32.RegisterPowerSettingNotification.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD]
    u32.RegisterPowerSettingNotification(hwnd, ctypes.byref(GUID_CONSOLE_DISPLAY_STATE), 0)
    stop = threading.Event()
    threading.Thread(target=_keep_recording_forever, args=(stop, rec, toast.heartbeat), daemon=True).start()
    Tray.add(hwnd)
    click_sound()

    msg = wt.MSG()
    while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        u32.TranslateMessage(ctypes.byref(msg))
        u32.DispatchMessageW(ctypes.byref(msg))

    # Closing the audio pipe does not end the screen grab, so ffmpeg is
    # stopped outright; every piece is already on disk and nothing is lost.
    Tray.remove()
    r = Recording.CURRENT
    if r:                                         # a recording running at quit is saved, not lost
        r.stop()
        r.thread.join(60)
    stop.set()
    stop_ffmpeg(rec.get("ff"))
    Press.wait_all()                              # let any save in progress finish
    winsound.Beep(600, 80); winsound.Beep(400, 80)


if __name__ == "__main__":
    main()
