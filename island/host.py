"""Island (lite): an iPhone-size Dynamic Island for Windows media.

The page is lite/island (index.html, island.css, island.js), copied into
lite/web/ at start-up together with bridge.js, which provides
window.lyricsIsland (the same calls the original DynamicIslandWindows
renderer used). Compact it is the iPhone island's 126 x 37; it opens on hover
with play / pause / skip and a seekable progress bar. There are no lyrics.

Underneath: pywebview on WebView2 (the Edge engine Windows already has)
instead of Electron, and Windows' own media controls (SMTC) instead of the
Spotify Web API, so changes arrive as events and controls need no sign-in.

Run:  pythonw host.py      (start.bat)
"""
import asyncio
import hashlib
import ctypes
import ctypes.wintypes as wt
import datetime
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request

import webview

import extras
import prayer
from winrt.windows.media.control import (
    GlobalSystemMediaTransportControlsSessionManager as SessionManager,
    GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
)
from winrt.windows.storage.streams import Buffer, InputStreamOptions

FROZEN = getattr(sys, "frozen", False)
HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))   # the app's own files
APP_DIR = os.path.dirname(sys.executable) if FROZEN else HERE                 # where the .exe / script is
ASSETS = os.path.join(HERE, "assets") if FROZEN else os.path.join(os.path.dirname(HERE), "assets")
# The page is built into a writable folder (Program Files is not), with the
# album art beside it.
WEB = os.path.join(os.environ.get("LOCALAPPDATA", HERE), "Hop Island", "web")
ART = os.path.join(WEB, "art")
ICON = os.path.join(ASSETS, "hop.ico")          # the Hop bunny, same as Hop Clipper
APP_NAME = "Hop Island"


def _read_version():
    for p in (os.path.join(HERE, "VERSION"), os.path.join(os.path.dirname(HERE), "VERSION")):
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
    """{"version", "url", "notes"} of Hop's newest GitHub release, or None."""
    req = urllib.request.Request("https://api.github.com/repos/preinfection/hop/releases/latest",
                                 headers={"User-Agent": f"hop-island/{VERSION}", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read().decode("utf-8"))
        return {"version": d.get("tag_name", "").lstrip("vV"), "url": d.get("html_url") or RELEASES,
                "notes": (d.get("body") or "")[:2000]}
    except Exception:
        return None
CONFIG = os.path.join(os.environ["APPDATA"], "LyricsIslandLite", "config.json")

COMPACT = (126, 37)                       # CSS px: the iPhone Dynamic Island
COMPACT_WIDE = 176                        # while it flashes a prayer countdown (island.css --w-wide)
EXPANDED = (360, 150)                     # open on hover (island/island.css)
VOL_EXTRA = 42                            # the volume row the island grows by (island.css --vol-h)
WINDOW = (EXPANDED[0], EXPANDED[1] + VOL_EXTRA + 4)   # fixed; the island animates inside it
EXPANDED_MIN = EXPANDED
PAGE = os.path.join(HERE, "ui")
DEFAULT_CLIPS = os.path.join(os.path.expanduser("~"), "Videos", "Hop Clips")
LEAD_GUARD_MS = 250

u32 = ctypes.windll.user32
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass


# ------------------------------------------------------------------ config
DEFAULTS = {"lyricOffsetMs": 0, "startAtLogin": False, "opacity": 100, "demoMode": False, "autoUpdate": True,
            "windowPosition": None, "expandedSize": {"width": 604, "height": 282}}


# The island's LAYOUT, edited in the settings window (settings.html) and
# applied live. Page order is `pages`; `hidden` pages are left out.
PAGE_IDS = ["music", "today", "clips", "pc"]
LAYOUT_DEFAULTS = {
    "pages": list(PAGE_IDS), "hidden": [],
    "musicLeft": "rec",        # rec | art | none
    "musicRight": "prayer",    # prayer | bars | clock | none
    "lyricLine": True, "progress": True, "controls": True, "volume": True, "snap": True,
    "pillArt": True, "pillClock": True, "pillBars": True,
    # Today page
    "todayHijri": True, "todayEvents": True, "todayWeather": True, "todayPrayers": True,
    # PC page gauges
    "gCpu": True, "gGpu": True, "gRam": True, "gDiskC": True, "gDiskE": True, "gPing": True,
    # pop-ups on the closed pill, and cards
    "actCharge": True, "actLow": True, "actBt": True, "prayCountdown": True, "clipCard": True,
    # prayer alarm
    "prayerAlarm": True, "prayerChime": True,
    # look
    "marquee": True, "artColor": True,
    "appTheme": "system",      # the settings app: system | light | dark
    "scale": 1.0,              # size of the whole island, 0.7 - 1.5
}
BOOL_KEYS = [k for k, v in LAYOUT_DEFAULTS.items() if isinstance(v, bool)]
SCALE_RANGE = (0.7, 1.5)


def clean_layout(raw, legacy_pages34=True):
    """A complete, valid layout from whatever was stored or sent."""
    L = dict(LAYOUT_DEFAULTS)
    if not isinstance(raw, dict):
        raw = {} if legacy_pages34 else {"hidden": ["clips", "pc"]}
    pages = [p for p in raw.get("pages", []) if p in PAGE_IDS]
    L["pages"] = list(dict.fromkeys(pages + [p for p in PAGE_IDS if p not in pages]))
    L["hidden"] = [p for p in dict.fromkeys(raw.get("hidden", [])) if p in PAGE_IDS]
    if len(L["hidden"]) >= len(PAGE_IDS):                  # at least one page stays
        L["hidden"] = [p for p in L["hidden"] if p != "music"]
    for k, allowed in (("musicLeft", ("rec", "art", "none")), ("musicRight", ("prayer", "bars", "clock", "none")),
                       ("appTheme", ("system", "light", "dark"))):
        if raw.get(k) in allowed:
            L[k] = raw[k]
    for k in BOOL_KEYS:
        if isinstance(raw.get(k), bool):
            L[k] = raw[k]
    try:
        L["scale"] = round(min(SCALE_RANGE[1], max(SCALE_RANGE[0], float(raw.get("scale", 1.0)))), 2)
    except (TypeError, ValueError):
        pass
    return L


# ---- Hop Clipper: found by its tray window (running) or its script (installed).
# Its settings live in its own folder; after writing them the island tells it
# to reload (WM_CLIP_RELOAD), which restarts its recorder with them.
CLIPPER_DIR = os.path.join(os.environ.get("LOCALAPPDATA", ""), "clipper")
CLIPPER_SETTINGS = os.path.join(CLIPPER_DIR, "settings.json")
def clipper_command():
    """How to start Hop Clipper, or None if it isn't installed: the installer
    puts HopClipper.exe in <install>\\Clipper next to <install>\\Island; a
    source checkout has clipper/clipper.py beside island/."""
    exe = os.path.join(APP_DIR, "..", "Clipper", "HopClipper.exe")
    if os.path.exists(exe):
        return [os.path.abspath(exe)]
    script = os.path.join(os.path.dirname(APP_DIR), "clipper", "clipper.py")
    if os.path.exists(script):
        pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        return [pyw if os.path.exists(pyw) else sys.executable, os.path.abspath(script)]
    return None
CLIPPER_DEFAULTS = {"watermark": True, "cursor": True, "toastInClips": False, "islandInClips": True,
                    "fps": 60, "quality": "high", "defaultSeconds": 30, "sounds": True, "saveDir": ""}
WM_CLIP_RELOAD = 0x8000 + 14


def clipper_settings():
    try:
        with open(CLIPPER_SETTINGS, encoding="utf-8") as fh:
            got = json.load(fh)
    except (OSError, ValueError):
        got = {}
    if not isinstance(got, dict):
        got = {}
    return {**CLIPPER_DEFAULTS, **{k: v for k, v in got.items() if k in CLIPPER_DEFAULTS}}


def clips_dir():
    """Where Hop Clipper saves (its settings; "" = Videos\\Hop Clips)."""
    return (clipper_settings().get("saveDir") or "").strip() or DEFAULT_CLIPS


def clipper_state():
    running = bool(u32.FindWindowW("clipper-tray", None))
    return {"running": running, "installed": running or clipper_command() is not None,
            "settings": clipper_settings(), "folder": clips_dir()}


def read_config():
    try:
        with open(CONFIG, encoding="utf-8") as fh:
            got = json.load(fh)
        return {**DEFAULTS, **(got if isinstance(got, dict) else {})}   # a damaged file: defaults
    except (OSError, ValueError):
        return dict(DEFAULTS)


def write_config(cfg):
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    with open(CONFIG, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)


# ------------------------------------------------------------------ the island
class Island:
    def __init__(self):
        self.cfg = read_config()
        self._take_installer_settings()
        extras.CLIPS = clips_dir()
        loc = self.cfg.get("location") or {}
        prayer.configure(loc.get("lat"), loc.get("lon"), self.cfg.get("prayerMethod", 2), self.cfg.get("asrSchool", 0))
        self.layout = clean_layout(self.cfg.get("layout"), self.cfg.get("pages34", True))
        self.settings_win = None
        self.window = None
        self.hwnd = None
        self.expanded = False
        self.lock = threading.Lock()
        self.playback = None                  # dict as in main.js
        self.lyrics = {"synced": [], "plain": "", "source": "none"}
        self.status = "Starting"
        self.track_key = ""
        self.session = None
        self.loop = None
        self._last_push = None
        self._art_until = 0.0
        self._online_tried = set()
        self.extra = 0                        # CSS px the island has grown by (volume row)
        self._session_id = None
        self._tokens = None
        self._refresh_pending = False

    # ---- state, same shape as Electron's
    def public_config(self):
        c = self.cfg
        return {"spotifyClientId": "", "lyricOffsetMs": c["lyricOffsetMs"], "pollIntervalMs": 0,
                "startAtLogin": c["startAtLogin"], "position": "top-center", "demoMode": c["demoMode"],
                "opacity": c["opacity"]}

    def active_index(self):
        pb = self.playback
        lines = self.lyrics.get("synced") or []
        if not pb or not lines:
            return -1
        progress = self.progress_now() + (self.cfg["lyricOffsetMs"] or 0) - LEAD_GUARD_MS
        idx = -1
        for i, line in enumerate(lines):
            if line["timeMs"] <= progress:
                idx = i
            else:
                break
        return idx

    def progress_now(self):
        pb = self.playback or {}
        p = pb.get("progressMs", 0)
        if pb.get("isPlaying") and pb.get("_sampled"):
            p += (time.time() - pb["_sampled"]) * 1000
        return min(p, pb.get("durationMs") or p)

    def state(self):
        pb = None
        if self.playback:
            pb = {k: v for k, v in self.playback.items() if not k.startswith("_")}
            pb["progressMs"] = int(self.progress_now())
        return {"status": self.status, "connected": True, "demoMode": self.cfg["demoMode"],
                "playback": pb, "lyrics": self.lyrics, "activeLyricIndex": self.active_index(),
                "config": self.public_config()}

    def push(self):
        """Send state to the page, but only when it says something new.

        Spotify fires timeline events about once a second; the renderer runs
        the progress bar itself, so those are skipped unless the position jumped
        (a seek) or anything else changed. run_js does not wait for a reply."""
        if not self.window:
            return
        st = self.state()
        pb = st["playback"] or {}
        now = time.time()
        same = dict(st, playback=dict(pb, progressMs=0)) if pb else st
        sig = json.dumps(same, sort_keys=True)
        last = self._last_push
        if last and last[0] == sig:
            expected = last[1] + ((now - last[2]) * 1000 if pb.get("isPlaying") else 0)
            if abs(pb.get("progressMs", 0) - expected) < 1500:
                return
        self._last_push = (sig, pb.get("progressMs", 0), now)
        dbg("push", len(sig))
        try:
            self.window.run_js(f"window.__islandPush && window.__islandPush({json.dumps(st)})")
        except Exception:
            pass

    # ---- window geometry (physical pixels via Win32, CSS px x DPI scale)
    def scale(self):
        """Physical px per CSS px: the display's DPI times the user's island size
        (the page zooms by the same factor, so every size in here still holds)."""
        k = self.layout.get("scale", 1.0)
        try:
            return (u32.GetDpiForWindow(wt.HWND(self.hwnd)) / 96.0 if self.hwnd else u32.GetDpiForSystem() / 96.0) * k
        except Exception:
            return k

    def work_area(self):
        """The work area (screen minus taskbar) of the monitor the island is on,
        or the nearest one if that monitor is gone."""
        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]
        try:
            if self.hwnd:
                u32.MonitorFromWindow.restype = wt.HANDLE
                mon = u32.MonitorFromWindow(wt.HWND(self.hwnd), 2)          # MONITOR_DEFAULTTONEAREST
                mi = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
                if mon and u32.GetMonitorInfoW(wt.HANDLE(mon), ctypes.byref(mi)):
                    r = mi.rcWork
                    return r.left, r.top, r.right, r.bottom
        except Exception:
            pass
        r = wt.RECT()
        u32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0)
        return r.left, r.top, r.right, r.bottom

    def display_signature(self):
        """What a display change changes: the island's DPI, its monitor and
        that monitor's work area."""
        try:
            u32.MonitorFromWindow.restype = wt.HANDLE
            return (u32.GetDpiForWindow(wt.HWND(self.hwnd)), u32.MonitorFromWindow(wt.HWND(self.hwnd), 2),
                    self.work_area())
        except Exception:
            return None

    def reflow(self):
        """After a display change: the right size for the (new) DPI, back on
        screen, the click region re-cut, and the glass put back. Seen
        2026-09-28: opening the laptop lid on an external monitor left the
        island a clipped black box (old size, new scale, glass lost)."""
        self.place_initial()                      # the right size, back where it was put (or top middle)
        self.set_region(self.expanded)
        g = getattr(self, "_glass", None)
        if g:
            try:
                g()
            except Exception as e:
                dbg("glass", repr(e))
        dbg("reflow", "dpi", u32.GetDpiForWindow(wt.HWND(self.hwnd)), "rect", self.rect())

    def rect(self):
        r = wt.RECT()
        u32.GetWindowRect(wt.HWND(self.hwnd), ctypes.byref(r))
        return r.left, r.top, r.right - r.left, r.bottom - r.top

    def set_bounds(self, x, y, w, h):
        l, t, r, b = self.work_area()
        w, h = min(w, r - l), min(h, b - t)
        x = max(l, min(x, r - w))
        y = max(t, min(y, b - h))
        u32.SetWindowPos(wt.HWND(self.hwnd), wt.HWND(-1), int(x), int(y), int(w), int(h), 0x0010)   # TOPMOST, NOACTIVATE

    def place_initial(self):
        # The window is ALWAYS the open size and never resizes (resizing made
        # WebView2 flash for half a second on every hover). Only its clickable
        # region changes; see set_region.
        s = self.scale()
        w, h = WINDOW[0] * s, WINDOW[1] * s
        l, t, r, b = self.work_area()
        pos = self.cfg.get("windowPosition")
        if pos and isinstance(pos, dict) and "cx" in pos:
            self.set_bounds(pos["cx"] - w / 2, pos["y"], w, h)
        else:
            self.set_bounds(l + (r - l - w) / 2, t + 10 * s, w, h)

    # ---- the API the bridge calls (window.pywebview.api.*)
    def get_state(self):
        return self.state()

    def save_config(self, update):
        for k in ("demoMode", "startAtLogin", "lyricOffsetMs", "opacity"):
            if k in update:
                self.cfg[k] = update[k]
        write_config(self.cfg)
        set_startup(self.cfg["startAtLogin"])
        self.status = "Settings saved"
        self.refresh_soon()
        return self.state()

    def connect_spotify(self):
        self.status = "No sign-in needed: uses Windows media controls"
        self.push()
        return self.state()

    def open_dashboard(self):
        return True

    def playback_action(self, action):
        if self.cfg["demoMode"] or not self.session or not self.loop:
            return self.state()
        fut = asyncio.run_coroutine_threadsafe(self._control(action), self.loop)
        threading.Thread(target=self._watch_control, args=(fut, action), daemon=True).start()
        return self.state()

    def _watch_control(self, fut, action):
        """SELF-HEALING. Seen 2026-09-28: the media connection hung, so the
        island sat on one song and play/pause did nothing. A control that
        hasn't finished in 3 s means it is stuck: start the island afresh."""
        try:
            fut.result(timeout=3)
        except Exception as e:
            dbg("control stuck:", action, repr(e), "-> restarting the island")
            self.restart_app()

    def restart_app(self):
        """The refresh button (and the stuck-controls fix): start a new copy
        of the island, which waits for this one to exit, then quit."""
        if FROZEN:
            cmd = [sys.executable]
        else:
            pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
            cmd = [pyw if os.path.exists(pyw) else sys.executable, os.path.abspath(__file__)]
        subprocess.Popen(cmd + ["--after", str(os.getpid())], cwd=APP_DIR,
                         creationflags=0x00000008 | 0x00000200)            # DETACHED | NEW_PROCESS_GROUP
        try:
            nid = getattr(self, "_tray_nid", None)
            if nid is not None:
                ctypes.windll.shell32.Shell_NotifyIconW(2, ctypes.byref(nid))   # no ghost tray icon
        except Exception:
            pass
        os._exit(0)

    def seek(self, position_ms):
        if self.session and self.loop:
            asyncio.run_coroutine_threadsafe(self._seek(position_ms), self.loop)
        return self.state()

    def set_expanded(self, expanded):
        self.set_region(bool(expanded))
        return True

    # ---- Spotify's own volume (its Windows audio session), not the PC's
    def _media_sessions(self):
        import comtypes
        from pycaw.pycaw import AudioUtilities
        try:
            comtypes.CoInitialize()
        except OSError:
            pass
        app = (self._session_id or "spotify").lower()
        out = []
        for sess in AudioUtilities.GetAllSessions():
            name = (sess.Process.name() if sess.Process else "").lower()
            if name and (name in app or name.replace(".exe", "") in app):
                out.append(sess.SimpleAudioVolume)
        return out

    def get_volume(self):
        try:
            vols = self._media_sessions()
            if not vols:
                return None
            return {"level": round(vols[0].GetMasterVolume(), 3), "muted": bool(vols[0].GetMute())}
        except Exception as e:
            dbg("volume read failed", repr(e))
            return None

    def set_volume(self, level=None, muted=None):
        try:
            for v in self._media_sessions():
                if level is not None:
                    v.SetMasterVolume(max(0.0, min(1.0, float(level))), None)
                if muted is not None:
                    v.SetMute(1 if muted else 0, None)
        except Exception as e:
            dbg("volume write failed", repr(e))
        return self.get_volume()

    # ---- the clipper (~/projects/clipper): the record button. It is a
    # separate program; its hidden "clipper-tray" window takes these messages
    # (clipper.py WM_REC_*), and answers with the running recording's start
    # time in ms since 1970, or 0.
    WM_REC_START, WM_REC_STOP, WM_REC_TOGGLE, WM_REC_QUERY = 0x8000 + 10, 0x8000 + 11, 0x8000 + 12, 0x8000 + 13

    def _clipper(self, msg):
        """(available, started_ms) after sending msg; never blocks for long."""
        u32.FindWindowW.restype = wt.HWND
        h = u32.FindWindowW("clipper-tray", None)
        if not h:
            return False, 0
        res = ctypes.c_size_t(0)
        u32.SendMessageTimeoutW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM, wt.UINT, wt.UINT,
                                            ctypes.POINTER(ctypes.c_size_t)]
        ok = u32.SendMessageTimeoutW(h, msg, 0, 0, 0x2, 500, ctypes.byref(res))   # SMTO_ABORTIFHUNG
        return bool(ok), int(res.value) if ok else 0

    def record(self, on):
        self._rec_cmd_at = time.time()
        avail, started = self._clipper(self.WM_REC_START if on else self.WM_REC_STOP)
        self._rec_cmd_at = time.time()
        self.rec = (avail, started)
        self.push_rec(force=True)
        return {"available": avail, "started": started}

    def push_rec(self, force=False):
        rec = getattr(self, "rec", (False, 0))
        if not force and rec == getattr(self, "_rec_sent", None):
            return
        self._rec_sent = rec
        try:
            self.window.run_js(f"window.__islandRec && window.__islandRec({json.dumps(rec[0])}, {rec[1]})")
        except Exception:
            pass

    def rec_loop(self):
        """Keep the page's record button in step with the clipper (also when
        a recording is started or stopped from the clipper's tray menu)."""
        while True:
            try:
                asked = time.time()
                rec = self._clipper(self.WM_REC_QUERY)
                # A start/stop sent while this query was out makes its answer
                # stale: it flipped the button back for half a second, and a
                # second click then stopped a recording that had just begun.
                if asked > getattr(self, "_rec_cmd_at", 0) + 0.2:
                    self.rec = rec
                    self.push_rec()
            except Exception as e:
                dbg("rec poll", repr(e))
            time.sleep(0.5)

    # ---- prayer times (prayer.py: fetched daily, saved on disk)
    def get_prayers(self):
        return prayer.today_and_tomorrow()

    def prayer_loop(self):
        """Fetch once a day (prayer.refresh skips a month already fetched
        today), and hand the page a new day at midnight."""
        sent = None
        while True:
            try:
                prayer.refresh()
                data = prayer.today_and_tomorrow()
                if data != sent and self.window:
                    sent = data
                    self.window.run_js(f"window.__islandPrayers && window.__islandPrayers({json.dumps(data)})")
            except Exception as e:
                dbg("prayer", repr(e))
            time.sleep(600)

    def set_pill_width(self, px):
        """The closed pill grows for a live activity (prayer countdown,
        charging, Bluetooth): widen its region first (the page narrows it again
        only after the shrink animation)."""
        self.pill_w = max(COMPACT[0], min(EXPANDED[0], int(px or COMPACT[0])))
        if not self.expanded:
            ui_thread(self.window, lambda: self.set_region(False))
        return True

    def set_big(self, on):
        """An expanded card (clip saved, drop zone) is showing: the whole
        window takes clicks and hover does not open the player over it."""
        self.big = bool(on)
        ui_thread(self.window, lambda: self.set_region(self.big))
        return True

    def open_file(self, path):
        if path and os.path.exists(path):
            os.startfile(path)
        return True

    def copy_file(self, path):
        if path and os.path.exists(path):
            threading.Thread(target=extras.copy_file, args=(path,), daemon=True).start()
        return True

    def get_today(self):
        return extras.today()

    # ---- page 3 / page 4
    def get_clips(self):
        clips = extras.recent_clips(3)
        for c in clips:
            c["url"] = "https://clips.island/" + urllib.parse.quote(c["name"])
            t = extras.thumb(c["path"])
            c["thumb"] = "https://thumbs.island/" + t if t else ""
        return clips

    def open_clips_folder(self):
        os.makedirs(clips_dir(), exist_ok=True)
        os.startfile(clips_dir())
        return True

    def clipboard_loop(self):
        """Text you copy, kept in MEMORY only for the clipboard-history button
        (password managers' private copies are skipped, see extras.Clipboard)."""
        self.clipboard = extras.Clipboard()
        while True:
            try:
                self.clipboard.poll()
            except Exception as e:
                dbg("clipboard", repr(e))
            time.sleep(1)

    def _js(self, code):
        try:
            self.window.run_js(code)
        except Exception:
            pass

    def extras_loop(self):
        """Today page every 10 min; charging / low battery every 3 s; the
        Bluetooth sound output every 2 s (one PowerShell look-up only when the
        output changes)."""
        last_today, ac, low_warned, out_name = 0, None, set(), None
        while True:
            try:
                if time.time() - last_today > 600:
                    last_today = time.time()
                    self._js(f"window.__islandToday && window.__islandToday({json.dumps(extras.today())})")
                on_ac, pct = extras.power()
                if ac is not None and on_ac and not ac:
                    self._js(f"window.__islandActivity && window.__islandActivity({json.dumps({'kind': 'charge', 'pct': pct})})")
                if on_ac:
                    low_warned.clear()
                elif pct is not None:
                    for level in (15, 5):
                        if pct <= level and level not in low_warned:
                            low_warned.update(l for l in (15, 5) if l >= level)
                            self._js(f"window.__islandActivity && window.__islandActivity({json.dumps({'kind': 'low', 'pct': pct})})")
                            break
                ac = on_ac
                name = extras.default_output()
                if out_name is not None and name != out_name:
                    threading.Thread(target=self._bt_check, args=(name,), daemon=True).start()
                out_name = name
            except Exception as e:
                dbg("extras", repr(e))
            time.sleep(2 if ac is not None else 1)

    def _bt_check(self, name):
        found = extras.bt_output(name)
        if found:
            device, battery = found
            self._js(f"window.__islandActivity && window.__islandActivity({json.dumps({'kind': 'bt', 'name': device, 'pct': battery})})")

    def _lyrics_for(self, key, title, artist, album, duration):
        lines = extras.lyrics(title, artist, album, duration)
        if key == self.track_key:
            self._js(f"window.__islandLyrics && window.__islandLyrics({json.dumps({'key': key, 'lines': lines})})")

    def clip_watch(self):
        """The clipper writes %LOCALAPPDATA%\\clipper\\last.json on every save."""
        last = os.path.join(os.environ.get("LOCALAPPDATA", ""), "clipper", "last.json")
        seen = os.path.getmtime(last) if os.path.exists(last) else 0
        while True:
            time.sleep(0.5)
            try:
                m = os.path.getmtime(last)
                if m != seen:
                    seen = m
                    with open(last, encoding="utf-8") as fh:
                        clip = json.load(fh)
                    if time.time() - clip.get("at", 0) < 30 and os.path.exists(clip["path"]):
                        clip["url"] = "https://clips.island/" + urllib.parse.quote(os.path.basename(clip["path"]))
                        self._js(f"window.__islandClip && window.__islandClip({json.dumps(clip)})")
            except (OSError, ValueError):
                pass

    def on_drop(self, event):
        """A file dropped on the island: upload it to mutate.lol and put
        the link on the clipboard. pywebview hands the real path."""
        files = (event.get("dataTransfer") or {}).get("files") or []
        path = next((f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")), None)
        if not path or not os.path.isfile(path):
            self._js("window.__islandUpload && window.__islandUpload({state: 'error', message: 'Drop a file'})")
            return
        name, size = os.path.basename(path), os.path.getsize(path)
        say = lambda d: self._js(f"window.__islandUpload && window.__islandUpload({json.dumps(d)})")
        say({"state": "uploading", "name": name, "size": size, "progress": 0})
        try:
            link = extras.upload(path, lambda f: say({"state": "uploading", "name": name, "size": size, "progress": f}))
            extras.copy_text(link)
            say({"state": "done", "link": link})
        except Exception as e:
            say({"state": "error", "message": str(e)[:80]})

    def set_pill_wide(self, on):
        """The closed pill grows for the prayer countdown: widen its region
        (the page narrows it again only after the shrink animation)."""
        return self.set_pill_width(COMPACT_WIDE if on else COMPACT[0])

    def hold_open(self, on):
        """The prayer alarm: open the island now and keep it open until released."""
        self.hold = bool(on)
        return True

    def chime(self):
        import winsound
        try:
            winsound.PlaySound(os.path.join(PAGE, "chime.wav"), winsound.SND_FILENAME | winsound.SND_ASYNC)
        except RuntimeError:
            pass
        return True

    def _take_installer_settings(self):
        """What was picked in the installer's "Customize now" pages: merged in
        once on the first start after installing, then the file is deleted."""
        path = os.path.join(os.path.dirname(CONFIG), "installer-settings.json")
        try:
            with open(path, encoding="utf-8") as fh:
                got = json.load(fh)
        except (OSError, ValueError):
            return
        if not isinstance(got, dict):
            got = {}
        if isinstance(got.get("layout"), dict):
            self.cfg["layout"] = clean_layout({**(self.cfg.get("layout") or {}), **got["layout"]})
        for k in ("prayerMethod", "asrSchool"):
            if isinstance(got.get(k), int):
                self.cfg[k] = got[k]
        if str(got.get("city", "")).strip():
            self.cfg["pendingCity"] = str(got["city"]).strip()[:80]    # looked up once online (first_city)
        if isinstance(got.get("startAtLogin"), bool):
            self.cfg["startAtLogin"] = got["startAtLogin"]
        write_config(self.cfg)
        try:
            os.remove(path)
        except OSError:
            pass

    # ---- updates (GitHub releases)
    def get_update(self):
        u = getattr(self, "_update", None) or {}
        return {"current": VERSION, "latest": u.get("version"), "url": u.get("url", RELEASES),
                "notes": u.get("notes", ""), "available": bool(u) and version_tuple(u.get("version")) > version_tuple(VERSION),
                "checked": getattr(self, "_update_checked", None), "auto": bool(self.cfg.get("autoUpdate", True))}

    def check_update(self):
        got = latest_release()
        self._update_checked = time.time()
        if got:
            self._update = got
        return self.get_update()

    def set_auto_update(self, on):
        self.cfg["autoUpdate"] = bool(on)
        write_config(self.cfg)
        return self.get_update()

    def open_release(self):
        try:
            os.startfile(self.get_update()["url"] or RELEASES)
        except OSError:
            pass
        return True

    def update_loop(self):
        """On start (the PC has just started, apps start with it) and once a
        day: a newer release -> the notice. Hop Clipper shows it when it is
        running (one notice, not two); otherwise the island does."""
        time.sleep(25)
        last = self.cfg.get("lastVersion")
        if last and version_tuple(VERSION) > version_tuple(last):
            self._js(f"window.__islandUpdated && window.__islandUpdated({json.dumps(VERSION)})")
        if last != VERSION:
            self.cfg["lastVersion"] = VERSION
            write_config(self.cfg)
        while True:
            if self.cfg.get("autoUpdate", True) and not getattr(self, "_update_later", False):
                u = self.check_update()
                if u["available"] and not u32.FindWindowW("clipper-tray", None):
                    self._js(f"window.__islandUpdate && window.__islandUpdate({json.dumps(u)})")
            time.sleep(24 * 3600)

    def update_answer(self, go):
        """The notice's buttons: Update now opens the release; Later = quiet
        until the next start."""
        self._update_later = True
        if go:
            self.open_release()
        return True

    def first_city(self):
        """The installer can't search, so it passes the typed name; the best
        match is taken on the first start that has internet."""
        name = self.cfg.get("pendingCity")
        if not name or self.cfg.get("location"):
            return
        for _ in range(20):
            got = self.search_city(name)
            if got:
                self.cfg.pop("pendingCity", None)
                self.set_location(got[0])
                return
            if got == []:                                   # searched fine, no such city
                self.cfg.pop("pendingCity", None)
                write_config(self.cfg)
                return
            time.sleep(30)                                  # offline: try again in a bit

    # ---- layout, size and position (the settings window)
    def get_layout(self):
        return dict(self.layout)

    def set_layout(self, raw):
        new = clean_layout(raw)
        old_scale = self.layout.get("scale", 1.0)
        self.layout = new
        self.cfg["layout"] = new
        write_config(self.cfg)
        if self.settings_win is not None:
            self._title_bar()
        if self.window:
            if new["scale"] != old_scale:
                ui_thread(self.window, self._apply_scale)
            self.window.run_js(f"window.__islandLayout && window.__islandLayout({json.dumps(new)})")
        return dict(new)

    def reset_layout(self):
        return self.set_layout(dict(LAYOUT_DEFAULTS, scale=self.layout.get("scale", 1.0)))

    def _apply_scale(self):
        """New island size: the window grows or shrinks around its top middle."""
        x, y, w, _ = self.rect()
        s = self.scale()
        nw, nh = WINDOW[0] * s, WINDOW[1] * s
        self.set_bounds(x + w / 2 - nw / 2, y, nw, nh)
        self.set_region(self.expanded)

    def _dpi(self):
        return self.scale() / self.layout.get("scale", 1.0)

    def get_position(self):
        l, t, r, b = self.work_area()
        x, y, w, _ = self.rect()
        return {"x": round(((x + w / 2) - l) / max(1, r - l) * 100, 1), "top": round((y - t) / self._dpi())}

    def set_position(self, x_pct=None, top=None):
        """x_pct: where the island's middle sits across the screen (0-100);
        top: screen px (at 100% scaling) from the top of the work area."""
        l, t, r, b = self.work_area()
        x, y, w, h = self.rect()
        cx = l + (r - l) * min(100.0, max(0.0, float(x_pct))) / 100 if x_pct is not None else x + w / 2
        ny = t + max(0.0, float(top)) * self._dpi() if top is not None else y

        def go():
            self.set_bounds(cx - w / 2, ny, w, h)
            nx, nyy, nw, _ = self.rect()
            self.cfg["windowPosition"] = {"cx": nx + nw / 2, "y": nyy}
            write_config(self.cfg)
        ui_thread(self.window, go)
        return self.get_position()

    def reset_position(self):
        self.set_layout(dict(self.layout, scale=1.0))
        ui_thread(self.window, self.recenter)
        return {"layout": self.get_layout(), "position": self.get_position()}

    # ---- Hop Clipper settings
    def get_clipper(self):
        return clipper_state()

    def set_clipper(self, raw):
        cur = clipper_settings()
        for k, v in (raw or {}).items():
            if k in CLIPPER_DEFAULTS and type(v) is type(CLIPPER_DEFAULTS[k]):
                cur[k] = v
        os.makedirs(CLIPPER_DIR, exist_ok=True)
        with open(CLIPPER_SETTINGS, "w", encoding="utf-8") as fh:
            json.dump(cur, fh, indent=2)
        self.apply_capture_affinity()
        extras.CLIPS = clips_dir()
        h = u32.FindWindowW("clipper-tray", None)
        if h:
            u32.PostMessageW(h, WM_CLIP_RELOAD, 0, 0)
        return clipper_state()

    def apply_capture_affinity(self):
        """In or out of Hop Clipper's recordings, as picked in its settings."""
        if self.hwnd:
            u32.SetWindowDisplayAffinity(wt.HWND(self.hwnd), 0 if clipper_settings()["islandInClips"] else 0x11)

    def start_clipper(self):
        cmd = clipper_command()
        if cmd and not u32.FindWindowW("clipper-tray", None):
            subprocess.Popen(cmd, cwd=os.path.dirname(cmd[-1]), creationflags=0x08000000)
        return True

    def pick_folder(self):
        """A folder picker for the clips folder (the settings app)."""
        w = self.settings_win or self.window
        try:
            got = w.create_file_dialog(webview.FOLDER_DIALOG, directory=clips_dir())
        except Exception as e:
            dbg("pick_folder", repr(e))
            return None
        return got[0] if got else None

    # ---- city for prayer times and weather
    def get_location(self):
        return {"location": self.cfg.get("location"), "method": self.cfg.get("prayerMethod", 2),
                "school": self.cfg.get("asrSchool", 0)}

    def search_city(self, q):
        """Open-Meteo's free geocoder (no key): up to 6 matches."""
        q = str(q or "").strip()
        if len(q) < 2:
            return []
        try:
            d = extras._get("https://geocoding-api.open-meteo.com/v1/search?count=6&language=en&format=json&name="
                            + urllib.parse.quote(q))
        except Exception as e:
            dbg("search_city", repr(e))
            return None
        out = []
        for r in d.get("results") or []:
            label = ", ".join(x for x in (r.get("name"), r.get("admin1"), r.get("country")) if x)
            out.append({"name": r.get("name"), "label": label, "lat": r.get("latitude"), "lon": r.get("longitude")})
        return out

    def set_location(self, loc=None, method=None, school=None):
        if loc is not None:
            self.cfg["location"] = ({"name": str(loc.get("name", ""))[:80], "label": str(loc.get("label", ""))[:160],
                                     "lat": float(loc["lat"]), "lon": float(loc["lon"])} if loc else None)
        if method is not None:
            self.cfg["prayerMethod"] = int(method)
        if school is not None:
            self.cfg["asrSchool"] = int(school)
        write_config(self.cfg)
        self.apply_location()
        # Waits for the new times (about a second), so the settings app can show
        # them, in its own card and in the preview, the moment this returns.
        self._reload_place()
        return self.get_location()

    def apply_location(self):
        loc = self.cfg.get("location") or {}
        prayer.configure(loc.get("lat"), loc.get("lon"), self.cfg.get("prayerMethod", 2), self.cfg.get("asrSchool", 0))

    def _reload_place(self):
        """New city or method: fresh prayer times and weather on the island now."""
        try:
            prayer.refresh(force=True)
            self._js(f"window.__islandPrayerReset && window.__islandPrayerReset()")
            self._js(f"window.__islandPrayers && window.__islandPrayers({json.dumps(prayer.today_and_tomorrow())})")
            extras.forget_weather()
            self._js(f"window.__islandToday && window.__islandToday({json.dumps(extras.today())})")
        except Exception as e:
            dbg("reload place", repr(e))

    def _dress_settings(self):
        """Look like a Windows 11 app: the bunny icon (not Python's), a dark
        title bar the colour of the page, rounded corners. Only posted
        messages and DWM calls: nothing here waits on the UI thread."""
        time.sleep(0.3)
        h = u32.FindWindowW(None, APP_NAME)
        if not h:
            return
        u32.LoadImageW.restype = wt.HANDLE
        u32.SetClassLongPtrW.restype = ctypes.c_void_p
        u32.SetClassLongPtrW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_void_p]
        big_px = max(32, u32.GetSystemMetrics(11))                                   # SM_CXICON (DPI aware)
        small_px = max(16, u32.GetSystemMetrics(49))                                 # SM_CXSMICON
        big = u32.LoadImageW(None, ICON, 1, big_px, big_px, 0x10)                    # IMAGE_ICON, LR_LOADFROMFILE
        small = u32.LoadImageW(None, ICON, 1, small_px, small_px, 0x10)
        # The TASKBAR takes its icon from the window class as well as the window,
        # and run from source that is python's: set both, a few times, because
        # the window library sets its own icon again once it has opened.
        for delay in (0, 1.0, 3.0):
            time.sleep(delay)
            if not u32.IsWindow(h):
                return
            if big:
                u32.SetClassLongPtrW(wt.HWND(h), -14, big)                           # GCLP_HICON
                u32.PostMessageW(wt.HWND(h), 0x0080, 1, big)                         # WM_SETICON, ICON_BIG
            if small:
                u32.SetClassLongPtrW(wt.HWND(h), -34, small)                         # GCLP_HICONSM
                u32.PostMessageW(wt.HWND(h), 0x0080, 0, small)
        self._title_bar(h)

    def _light(self):
        """The settings app's theme: picked, or Windows' own app mode."""
        pick = self.layout.get("appTheme", "system")
        if pick != "system":
            return pick == "light"
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
                return bool(winreg.QueryValueEx(k, "AppsUseLightTheme")[0])
        except OSError:
            return False

    def _title_bar(self, h=None):
        """Title bar in the page's colours (dark or light), rounded corners."""
        h = h or u32.FindWindowW(None, APP_NAME)
        if not h:
            return
        light = self._light()
        dwm = ctypes.windll.dwmapi
        for attr, val in ((20, 0 if light else 1),                                   # immersive dark mode
                          (35, 0x00F7F5F5 if light else 0x000D0B0B),                 # caption = page bg (BGR)
                          (36, 0x001F1D1D if light else 0x00F5F2F2),                 # caption text
                          (33, 2)):                                                  # round corners
            dwm.DwmSetWindowAttribute(wt.HWND(h), attr, ctypes.byref(ctypes.c_int(val)), 4)

    def open_settings(self):
        """The settings window: a normal app window with a live preview."""
        w = self.settings_win
        if w is not None:
            try:
                w.show()
                w.restore()
                return True
            except Exception:
                self.settings_win = None
        # Big enough to show everything at once (the preview was cut off at
        # 760 px high), but never bigger than the screen it opens on.
        l, t, r, b = self.work_area()
        dpi = self._dpi()
        w = int(min(1100, (r - l) / dpi - 40))
        h = int(min(820, (b - t) / dpi - 40))
        win = webview.create_window(APP_NAME, os.path.join(WEB, "settings.html"),
                                    js_api=SettingsApi(self), width=w, height=h,
                                    min_size=(min(860, w), min(560, h)), background_color="#0b0b0d")

        def gone():
            self.settings_win = None

        def dress():
            # NEVER blocks: pywebview waits for 'shown' handlers on the UI
            # thread that runs every window, so touching the form from here
            # (setting .Icon sends a message to that thread) deadlocked the
            # settings window AND the island (2026-09-28: both went white,
            # "not responding"). The work is done later, with posted messages.
            threading.Thread(target=self._dress_settings, daemon=True).start()
        win.events.closed += gone
        win.events.shown += dress
        self.settings_win = win
        return True

    def swiped(self):
        """A card / alarm was swiped away: stay a pill until the pointer leaves."""
        self._quiet_until_leave = True
        return True

    def set_extra(self, px):
        self.extra = max(0, int(px or 0))
        return True

    def recenter(self):
        """Snap back to the exact top middle of the screen and forget the drag."""
        s = self.scale()
        l, t, r, b = self.work_area()
        _, _, w, h = self.rect()
        self.set_bounds(l + (r - l - w) / 2, t + 10 * s, w, h)
        self.cfg["windowPosition"] = None
        write_config(self.cfg)
        return True

    def set_region(self, is_open):
        """Clip the window's clickable (and visible) area: the whole window
        while open, just the pill's box while closed, so the transparent rest
        lets clicks through to whatever is underneath."""
        self.expanded = is_open
        _, _, w, h = self.rect()
        if is_open:
            l, t, r, b = 0, 0, w, h
        else:
            s = self.scale()
            cw, ch = round(getattr(self, "pill_w", COMPACT[0]) * s), round(COMPACT[1] * s)
            l, t, r, b = (w - cw) // 2, 0, (w - cw) // 2 + cw, ch
        gdi = ctypes.windll.gdi32
        gdi.CreateRectRgn.restype = wt.HANDLE
        rgn = gdi.CreateRectRgn(l, t, r, b)
        u32.SetWindowRgn(wt.HWND(self.hwnd), wt.HANDLE(rgn), True)   # Windows owns rgn now

    def resize_expanded(self, size):
        if not self.expanded:
            return None
        s = self.scale()
        x, y, _, _ = self.rect()
        w = max(EXPANDED_MIN[0], float(size["width"]))
        h = max(EXPANDED_MIN[1], float(size["height"]))
        self.cfg["expandedSize"] = {"width": round(w), "height": round(h)}
        self.set_bounds(x, y, w * s, h * s)
        return {"width": round(w), "height": round(h)}

    def start_drag(self):
        """Hand the window to Windows' own move loop: smooth, native dragging."""
        def go():
            u32.ReleaseCapture()
            u32.SendMessageW(wt.HWND(self.hwnd), 0x00A1, 2, 0)   # WM_NCLBUTTONDOWN, HTCAPTION
            x, y, w, _ = self.rect()
            self.cfg["windowPosition"] = {"cx": x + w / 2, "y": y}
            write_config(self.cfg)
        ui_thread(self.window, go)
        return True

    # ---- hover (decided here, from the real cursor, not by the page)
    def hover_loop(self):
        """Open while the cursor is over the pill, close shortly after it leaves.

        The page can't do this itself: growing the window makes Chromium fire a
        false mouseleave for one frame, which closed and re-opened the island
        in a loop. Here it is plain geometry on screen coordinates, ~30x a second."""
        pt = wt.POINT()
        is_open, left_at, closed_at, entered_at = False, None, None, None
        while True:
            time.sleep(0.033)
            if not self.hwnd:
                continue
            # STAY ON TOP. Something can take the window's topmost flag away
            # (seen 2026-09-27: the island fell behind a fullscreen terminal
            # and a browser and looked closed). Once a second: put it back.
            self._top_tick = getattr(self, "_top_tick", 0) + 1
            if self._top_tick % 60 == 7:
                # THE GREY BOX: pywebview switches Windows' Mica backdrop back
                # on whenever Windows sends a theme change, and then the whole
                # window shows grey behind the open island (seen 2026-09-28).
                # Every 2 s: if it's back, switch it off again.
                try:
                    kind = ctypes.c_int(0)
                    ctypes.windll.dwmapi.DwmGetWindowAttribute(wt.HWND(self.hwnd), 38, ctypes.byref(kind), 4)
                    if kind.value not in (0, 1) and getattr(self, "_glass", None):
                        dbg("backdrop came back:", kind.value, "-> off")
                        ui_thread(self.window, self._glass)
                except Exception as e:
                    dbg("backdrop check", repr(e))
            if self._top_tick % 30 == 15:
                sig = self.display_signature()
                last = getattr(self, "_display_sig", None)
                _, _, cw, ch = self.rect()
                s_ = self.scale()
                wrong_size = abs(cw - WINDOW[0] * s_) > 2 or abs(ch - WINDOW[1] * s_) > 2
                if (sig and last and sig != last) or wrong_size:
                    dbg("display changed", last, "->", sig)
                    # twice: now, and once Windows has finished moving things
                    ui_thread(self.window, self.reflow)
                    threading.Timer(1.5, lambda: ui_thread(self.window, self.reflow)).start()
                if sig:
                    self._display_sig = sig
            if self._top_tick % 30 == 0:
                try:
                    if not (u32.GetWindowLongW(wt.HWND(self.hwnd), -20) & 0x8):          # WS_EX_TOPMOST
                        dbg("lost topmost -> restoring")
                        u32.SetWindowPos(wt.HWND(self.hwnd), wt.HWND(-1), 0, 0, 0, 0,
                                         0x0001 | 0x0002 | 0x0010)                           # NOSIZE|NOMOVE|NOACTIVATE
                except Exception as e:
                    dbg("topmost", repr(e))
            if getattr(self, "big", False):
                is_open, left_at, closed_at, entered_at = False, None, None, None
                continue
            try:
                u32.GetCursorPos(ctypes.byref(pt))
                x, y, w, _ = self.rect()
                s = self.scale()
                pw, ph = (EXPANDED if is_open else (getattr(self, "pill_w", COMPACT[0]), COMPACT[1]))
                if is_open:
                    ph += self.extra
                pw, ph = pw * s, ph * s
                cx = x + w / 2
                pad = 6 * s if is_open else 0          # a little slack once open
                inside = (cx - pw / 2 - pad <= pt.x <= cx + pw / 2 + pad) and (y <= pt.y <= y + ph + pad)
                held = getattr(self, "hold", False)            # a prayer alarm holds it open
                if held:
                    inside, entered_at = True, entered_at or 0.0
                dragging = u32.GetAsyncKeyState(0x01) & 0x8000
                # MOVING IT never opens it: not while the button is held (a
                # drag), nor for a moment after; and after a swipe-away it
                # stays a pill until the pointer has left it once.
                if dragging:
                    self._drag_at = time.time()
                    entered_at = None if not is_open else entered_at
                if getattr(self, "_quiet_until_leave", False) and not inside:
                    self._quiet_until_leave = False
                quiet = dragging or time.time() - getattr(self, "_drag_at", 0) < 0.6 or getattr(self, "_quiet_until_leave", False)
                # Opens with music playing, or whenever the clipper is there (record button).
                playing = bool(self.playback and not self.playback.get("empty")) or getattr(self, "rec", (False, 0))[0]
                now = time.time()
                if inside != getattr(self, "_dbg_in", None) or is_open != getattr(self, "_dbg_open", None):
                    self._dbg_in, self._dbg_open = inside, is_open
                    dbg("hover", "inside", inside, "open", is_open, "pt", pt.x, pt.y, "rect", x, y, w, "scale", s)
                if not inside:
                    entered_at = None
                elif entered_at is None:
                    entered_at = now
                # Open only after the cursor RESTS on the pill for a moment, so
                # sweeping past it (e.g. while gaming) doesn't pop it open.
                if inside and not is_open and (playing or held) and not (quiet and not held) and now - entered_at >= 0.25:
                    left_at, closed_at = None, None
                    if not self.expanded:
                        ui_thread(self.window, lambda: self.set_region(True))
                    is_open = True
                    self.window.run_js("window.__islandHover && window.__islandHover(true)")
                elif is_open and (inside or dragging):
                    left_at = None
                elif is_open:
                    left_at = left_at or now
                    if now - left_at > 0.3:
                        is_open, closed_at = False, now
                        self.extra = 0                  # the volume row closes with the island
                        self.window.run_js("window.__islandHover && window.__islandHover(false)")
                elif self.expanded and closed_at and now - closed_at > 0.45:
                    ui_thread(self.window, lambda: self.set_region(False))   # the pill has finished shrinking
                    closed_at = None
            except Exception as e:
                dbg("hover error", repr(e))

    # ---- Windows media controls (SMTC)
    def refresh_soon(self):
        # Events arrive in bursts (Spotify sends three for one track change);
        # they all fold into one refresh 50 ms later.
        if self.loop and not self._refresh_pending:
            self._refresh_pending = True
            self.loop.call_soon_threadsafe(lambda: self.loop.call_later(0.05, self._run_refresh))

    def _run_refresh(self):
        self._refresh_pending = False
        asyncio.ensure_future(self._refresh())

    async def _control(self, action):
        s = self.session
        try:
            if action == "play":
                await s.try_play_async()
            elif action == "pause":
                await s.try_pause_async()
            elif action == "next":
                await s.try_skip_next_async()
            elif action == "previous":
                await s.try_skip_previous_async()
        except Exception:
            pass
        await self._refresh()

    async def _seek(self, position_ms):
        try:
            await self.session.try_change_playback_position_async(int(max(0, position_ms) * 10000))
        except Exception:
            pass
        await self._refresh()

    def _pick_session(self):
        sessions = list(self.manager.get_sessions())
        for s in sessions:
            if "spotify" in (s.source_app_user_model_id or "").lower():
                return s
        return self.manager.get_current_session() or (sessions[0] if sessions else None)

    def _watch(self, session):
        # get_sessions() hands back a NEW wrapper object every call, so compare
        # by app id. (Comparing objects re-subscribed on every refresh: the
        # handlers multiplied into thousands of refreshes a minute.)
        sid = session.source_app_user_model_id if session is not None else None
        if sid == self._session_id and session is not None and self.session is not None:
            return
        old, tokens = self.session, self._tokens
        if old is not None and tokens:
            try:
                old.remove_media_properties_changed(tokens[0])
                old.remove_playback_info_changed(tokens[1])
                old.remove_timeline_properties_changed(tokens[2])
            except Exception:
                pass
        self.session, self._session_id, self._tokens = session, sid, None
        if session is not None:
            kick = lambda *_: self.refresh_soon()
            self._tokens = (session.add_media_properties_changed(kick),
                            session.add_playback_info_changed(kick),
                            session.add_timeline_properties_changed(kick))

    async def _artwork(self, props, current=""):
        try:
            if not props.thumbnail:
                dbg("artwork: Windows has no cover for", repr(props.title))
                return ""
            stream = await props.thumbnail.open_read_async()
            size = int(stream.size)
            if not size or size > 5_000_000:
                dbg("artwork: cover size", size, "for", repr(props.title))
                return ""
            buf = Buffer(size)
            await stream.read_async(buf, size, InputStreamOptions.READ_AHEAD)
            data = bytes(memoryview(buf))[:buf.length]
            if not data:
                return ""
            dbg("artwork", size)
            ext = ".png" if "png" in (stream.content_type or "") else ".jpg"
            return self._store_art(data, ext, current)
        except Exception as e:
            dbg("artwork failed", repr(e))
            return ""

    def _store_art(self, data, ext, current=""):
        """A small file the page loads once, instead of a base64 string riding
        along with every state update. Named by its CONTENT, so an unchanged
        cover is not rewritten and a cached old file can never stand in for a
        new one."""
        name = hashlib.sha1(data).hexdigest()[:16] + ext
        if name == os.path.basename(current or ""):
            return current
        os.makedirs(ART, exist_ok=True)
        for old in os.listdir(ART):
            try:
                os.remove(os.path.join(ART, old))
            except OSError:
                pass
        with open(os.path.join(ART, name), "wb") as fh:
            fh.write(data)
        return f"./art/{name}"

    def _online_cover(self, key, title, artist):
        """For songs Spotify sends to Windows WITHOUT a cover: look it up on
        Apple's free iTunes search (no account) and use it if the song is still
        playing. Runs on a worker thread; tried once per song."""
        data = online_cover(title, artist)
        dbg("artwork online", repr(title), "found" if data else "not found")
        if not data or key != self.track_key or not self.playback:
            return
        url = self._store_art(data, ".jpg", self.playback.get("artworkUrl", ""))
        if key == self.track_key and self.playback:
            self.playback["artworkUrl"] = url
            self.push()

    async def _refresh(self):
        dbg("refresh")
        if self.cfg["demoMode"]:
            self.status = "Demo mode"
            self.playback = {"empty": False, "isPlaying": True, "progressMs": 0, "durationMs": 214000,
                             "track": "Midnight City", "artist": "M83", "album": "", "artworkUrl": "",
                             "uri": "demo:midnight-city", "_sampled": time.time()}
            self.push()
            return
        self._watch(self._pick_session())
        s = self.session
        if s is None:
            self.status, self.playback = "Nothing playing", None
            self.lyrics, self.track_key = {"synced": [], "plain": "", "source": "none"}, ""
            self.push()
            return
        try:
            props = await s.try_get_media_properties_async()
            info = s.get_playback_info()
            tl = s.get_timeline_properties()
        except Exception:
            self._session_id = None     # the app went away; pick afresh next time
            return
        position = tl.position.total_seconds() * 1000
        duration = (tl.end_time - tl.start_time).total_seconds() * 1000
        playing = info.playback_status == PlaybackStatus.PLAYING
        if playing and tl.last_updated_time:
            # SMTC stamps the position when it was last reported; bring it up to now.
            age = (datetime.datetime.now(datetime.timezone.utc) - tl.last_updated_time).total_seconds()
            if 0 < age < 3600:
                position += age * 1000
        key = f"{props.title}|{props.artist}|{props.album_title}"
        new_track = key != self.track_key
        # Spotify often sends the new title BEFORE the new cover (sometimes the
        # previous song's cover first). So the cover is read again on every
        # update for the first 6 s of a song, and whenever it is still missing.
        current = "" if new_track else (self.playback or {}).get("artworkUrl", "")
        if new_track:
            self._art_until = time.time() + 6
        if new_track or not current or time.time() < self._art_until:
            art = await self._artwork(props, current) or current
            if time.time() < self._art_until:
                self.loop.call_later(1.0, self.refresh_soon)   # keep looking while events are quiet
        else:
            art = current
        # Still no cover 2 s into the song: Windows was given none, ask online.
        if not art and props.title and key not in self._online_tried and time.time() > self._art_until - 4:
            self._online_tried.add(key)
            threading.Thread(target=self._online_cover, args=(key, props.title, props.artist),
                             daemon=True).start()
        self.playback = {"empty": not props.title, "isPlaying": playing, "progressMs": int(position),
                         "durationMs": int(duration), "track": props.title or "", "artist": props.artist or "",
                         "album": props.album_title or "", "artworkUrl": art, "uri": key,
                         "_sampled": time.time()}
        self.status = "Windows media" if props.title else "Nothing playing"
        if new_track:
            self.track_key = key
            # One synced line in the open view: fetched once per song (LRCLIB).
            if props.title:
                threading.Thread(target=self._lyrics_for, daemon=True,
                                 args=(key, props.title, props.artist or "", props.album_title or "", int(duration))).start()
        self.push()

    def media_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        async def main():
            self.manager = await SessionManager.request_async()
            self.manager.add_current_session_changed(lambda *_: self.refresh_soon())
            self.manager.add_sessions_changed(lambda *_: self.refresh_soon())
            while True:
                await self._refresh()
                # Events carry every change; this is only a cheap local resync
                # (no network) so the progress bar never drifts.
                await asyncio.sleep(2)

        self.loop.run_until_complete(main())


# ------------------------------------------------------------------ helpers
def online_cover(title, artist):
    """Cover art bytes from the iTunes Search API (600 px), or None."""
    import urllib.parse
    import urllib.request
    try:
        q = urllib.parse.urlencode({"term": f"{artist} {title}", "entity": "song", "limit": 5})
        req = urllib.request.Request("https://itunes.apple.com/search?" + q, headers={"User-Agent": "island-lite"})
        with urllib.request.urlopen(req, timeout=6) as r:
            results = json.loads(r.read().decode("utf-8")).get("results", [])
        want = (title or "").lower()
        pick = next((x for x in results if want and want in x.get("trackName", "").lower()), None) or (results[0] if results else None)
        if not pick or not pick.get("artworkUrl100"):
            return None
        art = pick["artworkUrl100"].replace("100x100bb", "600x600bb")
        with urllib.request.urlopen(urllib.request.Request(art, headers={"User-Agent": "island-lite"}), timeout=6) as r:
            data = r.read()
        return data if len(data) > 1000 else None
    except Exception:
        return None


def dbg(*a):
    if os.environ.get("ISLAND_DEBUG"):
        with open(os.path.join(os.environ["TEMP"], "island-debug.txt"), "a") as f:
            f.write(f"{time.time():.2f} " + " ".join(map(str, a)) + chr(10))


def ui_thread(window, fn):
    """Run fn on the window's UI thread (Win32 dragging must happen there)."""
    try:
        from System import Action
        window.native.Invoke(Action(fn))
    except Exception:
        fn()


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


TRAY_CLASS = "lyrics-island-lite" + os.environ.get("HOP_TEST_INSTANCE", "")
WM_ISLAND_QUIT = 0x8004                              # sent by the installer and by a newer copy


def set_startup(on):
    folder = os.path.join(os.environ["APPDATA"], r"Microsoft\Windows\Start Menu\Programs\Startup")
    lnk = os.path.join(folder, "Hop Island.lnk")
    old = os.path.join(folder, "Lyrics Island.lnk")          # the name before Hop
    if os.path.exists(old):
        os.remove(old)
    if not on:
        if os.path.exists(lnk):
            os.remove(lnk)
        return
    if FROZEN:
        target, args = sys.executable, ""
    else:
        target, args = os.path.join(os.path.dirname(sys.executable), "pythonw.exe"), f'\"{os.path.join(HERE, "host.py")}\"'
    ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');"
          f"$s.TargetPath='{target}';$s.Arguments='{args}';$s.WorkingDirectory='{APP_DIR}';"
          f"$s.IconLocation='{ICON}';$s.Save()")
    import subprocess
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], creationflags=0x08000000)


def build_web():
    """The island page (lite/island) plus the bridge script, into lite/web."""
    os.makedirs(WEB, exist_ok=True)
    for name in os.listdir(WEB):
        path = os.path.join(WEB, name)
        if os.path.isfile(path):
            os.remove(path)
    for name in os.listdir(PAGE):                      # files, and folders such as fonts/
        src, dst = os.path.join(PAGE, name), os.path.join(WEB, name)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copyfile(src, dst)
    shutil.copyfile(os.path.join(HERE, "bridge.js"), os.path.join(WEB, "bridge.js"))
    with open(os.path.join(WEB, "config.js"), "w", encoding="utf-8") as fh:
        cfg = read_config()
        fh.write("window.__layout = " + json.dumps(clean_layout(cfg.get("layout"), cfg.get("pages34", True))) + ";" + chr(10))
    return os.path.join(WEB, "index.html")


def tray(island):
    """A tray icon with Show / Hide / Quit, like the Electron version's."""
    import ctypes.wintypes as w
    k32, sh32 = ctypes.windll.kernel32, ctypes.windll.shell32
    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
    u32.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
    u32.DefWindowProcW.restype = LRESULT
    k32.GetModuleHandleW.restype = w.HMODULE
    u32.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, w.HWND, w.HMENU, w.HINSTANCE, ctypes.c_void_p]
    u32.CreateWindowExW.restype = w.HWND
    u32.LoadImageW.argtypes = [w.HINSTANCE, w.LPCWSTR, w.UINT, ctypes.c_int, ctypes.c_int, w.UINT]
    u32.LoadImageW.restype = w.HANDLE
    u32.CreatePopupMenu.restype = w.HMENU
    u32.AppendMenuW.argtypes = [w.HMENU, w.UINT, ctypes.c_size_t, w.LPCWSTR]
    u32.TrackPopupMenu.argtypes = [w.HMENU, w.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.HWND, ctypes.c_void_p]
    sh32.Shell_NotifyIconW.argtypes = [w.DWORD, ctypes.c_void_p]

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [("style", w.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                    ("cbWndExtra", ctypes.c_int), ("hInstance", w.HINSTANCE), ("hIcon", w.HICON),
                    ("hCursor", w.HANDLE), ("hbrBackground", w.HBRUSH), ("lpszMenuName", w.LPCWSTR),
                    ("lpszClassName", w.LPCWSTR)]

    class NID(ctypes.Structure):
        _fields_ = [("cbSize", w.DWORD), ("hWnd", w.HWND), ("uID", w.UINT), ("uFlags", w.UINT),
                    ("uCallbackMessage", w.UINT), ("hIcon", w.HICON), ("szTip", w.WCHAR * 128),
                    ("dwState", w.DWORD), ("dwStateMask", w.DWORD), ("szInfo", w.WCHAR * 256),
                    ("uVersion", w.UINT), ("szInfoTitle", w.WCHAR * 64), ("dwInfoFlags", w.DWORD),
                    ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", w.HICON)]

    def proc(hwnd, msg, wparam, lparam):
        if msg == 0x8002:                                         # "open settings" (tests, other tools)
            threading.Thread(target=island.open_settings, daemon=True).start()
            return 0
        if msg == WM_ISLAND_QUIT:                                  # the installer / a newer copy: quit
            sh32.Shell_NotifyIconW(2, ctypes.byref(nid))
            island.quitting = True
            try:
                island.window.destroy()
            except Exception:
                pass
            u32.PostQuitMessage(0)
            os._exit(0)
        if msg == 0x8003:                                         # "restart" (the refresh button, for tests)
            threading.Thread(target=island.restart_app, daemon=True).start()
            return 0
        if msg == 0x8001 and (lparam & 0xFFFF) == 0x0205:        # right click
            m = u32.CreatePopupMenu()
            u32.AppendMenuW(m, 0, 1, "Show island")
            u32.AppendMenuW(m, 0, 2, "Hide island")
            u32.AppendMenuW(m, 0, 5, "Settings…")
            u32.AppendMenuW(m, 0x800, 0, None)
            u32.AppendMenuW(m, 0x8 if island.cfg["startAtLogin"] else 0, 4, "Start with Windows")   # MF_CHECKED
            u32.AppendMenuW(m, 0x800, 0, None)
            u32.AppendMenuW(m, 0, 3, "Quit")
            pt = w.POINT(); u32.GetCursorPos(ctypes.byref(pt))
            u32.SetForegroundWindow(hwnd)
            cmd = u32.TrackPopupMenu(m, 0x100, pt.x, pt.y, 0, hwnd, None)
            u32.DestroyMenu(m)
            if cmd == 1:
                island.window.show()
            elif cmd == 2:
                island.window.hide()
            elif cmd == 4:
                island.save_config({"startAtLogin": not island.cfg["startAtLogin"]})
            elif cmd == 5:
                threading.Thread(target=island.open_settings, daemon=True).start()
            elif cmd == 3:
                sh32.Shell_NotifyIconW(2, ctypes.byref(nid))
                island.quitting = True
                island.window.destroy()
                u32.PostQuitMessage(0)
            return 0
        return u32.DefWindowProcW(hwnd, msg, wparam, lparam)

    wndproc = WNDPROC(proc)
    wc = WNDCLASSW(lpfnWndProc=wndproc, hInstance=k32.GetModuleHandleW(None), lpszClassName=TRAY_CLASS)
    u32.RegisterClassW(ctypes.byref(wc))
    hwnd = u32.CreateWindowExW(0, TRAY_CLASS, "Lyrics Island", 0, 0, 0, 0, 0, None, None, wc.hInstance, None)
    nid = NID(cbSize=ctypes.sizeof(NID), hWnd=hwnd, uID=1, uFlags=1 | 2 | 4, uCallbackMessage=0x8001,
              hIcon=u32.LoadImageW(None, ICON, 1, 0, 0, 0x10 | 0x40))
    nid.szTip = APP_NAME
    sh32.Shell_NotifyIconW(0, ctypes.byref(nid))
    island._tray_nid = nid
    msg = w.MSG()
    while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        u32.TranslateMessage(ctypes.byref(msg))
        u32.DispatchMessageW(ctypes.byref(msg))


def main():
    # A restart (refresh button): wait for the old island to be gone first.
    if "--after" in sys.argv:
        try:
            import psutil
            old = psutil.Process(int(sys.argv[sys.argv.index("--after") + 1]))
            old.wait(timeout=10)
        except Exception:
            pass
    # One island at a time.
    # (HOP_TEST_INSTANCE: tests/test_startup.py runs a second island beside yours)
    # One island at a time, and the newest wins (see take_over).
    # (HOP_TEST_INSTANCE: the tests run their own islands beside yours)
    global _MUTEX
    _MUTEX = take_over("Local\\lyrics-island-lite" + os.environ.get("HOP_TEST_INSTANCE", ""), TRAY_CLASS, WM_ISLAND_QUIT, wait=3.0)
    if not _MUTEX:
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Hop.Island")
    except Exception:
        pass
    island = Island()
    page = build_web()
    # Chromium clears to fully transparent from the first frame (see key()).
    os.environ["WEBVIEW2_DEFAULT_BACKGROUND_COLOR"] = "00000000"
    # Lighter on slow PCs: no background network chatter, and the island and
    # the settings window share one render process instead of one each.
    os.environ.setdefault("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
                          "--disable-background-networking --renderer-process-limit=1")
    s = u32.GetDpiForSystem() / 96.0
    island.window = webview.create_window(
        "Lyrics Island", page, js_api=IslandApi(island), width=WINDOW[0], height=WINDOW[1],
        frameless=True, transparent=True, on_top=True, resizable=False, easy_drag=False,
        focus=False, background_color="#000000")

    def started():
        # Wait for the native window, then: hide from taskbar/Alt+Tab, place top-centre.
        for _ in range(100):
            try:
                island.hwnd = int(island.window.native.Handle.ToInt64())
                break
            except Exception:
                time.sleep(0.05)
        # WS_EX_NOACTIVATE: clicking the island never makes it the active
        # window. It used to become active after a click, so when a game
        # was closed with Alt+F4 focus fell to the island and the NEXT Alt+F4
        # closed the island (2026-09-27).
        GWL_EXSTYLE, WS_EX_TOOLWINDOW, WS_EX_APPWINDOW, WS_EX_NOACTIVATE = -20, 0x80, 0x40000, 0x08000000
        ex = u32.GetWindowLongW(wt.HWND(island.hwnd), GWL_EXSTYLE)
        u32.SetWindowLongW(wt.HWND(island.hwnd), GWL_EXSTYLE, (ex | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE) & ~WS_EX_APPWINDOW)
        # Kept out of screen capture (WDA_EXCLUDEFROMCAPTURE): the clipper
        # films the whole screen, and game clips shouldn't carry the island.
        island.apply_capture_affinity()

        # TRANSPARENCY. WebView2 draws on its own GPU layer, so a WinForms
        # colour key cannot reach its see-through pixels (they came out #202020).
        # Instead, like Tauri: keep the window unlayered, have Chromium clear to
        # transparent, and switch on DWM blur-behind with an empty region, which
        # makes DWM honour the per-pixel alpha. Soft anti-aliased corners and the
        # pill's 92 % black then look exactly as they did in Electron.
        def glass():
            """The see-through window: Windows can drop it on a display change."""
            from System.Drawing import Color
            form = island.window.native
            form.BackColor = Color.Black
            wv = form.browser.webview
            wv.DefaultBackgroundColor = Color.Transparent
            form.MinimumSize = type(form.MinimumSize)(1, 1)

            class BLURBEHIND(ctypes.Structure):
                _fields_ = [("dwFlags", wt.DWORD), ("fEnable", wt.BOOL),
                            ("hRgnBlur", wt.HANDLE), ("fTransitionOnMaximized", wt.BOOL)]
            gdi = ctypes.windll.gdi32
            gdi.CreateRectRgn.restype = wt.HANDLE
            rgn = gdi.CreateRectRgn(0, 0, -1, -1)
            bb = BLURBEHIND(0x1 | 0x2, True, rgn, False)   # DWM_BB_ENABLE | DWM_BB_BLURREGION
            ctypes.windll.dwmapi.DwmEnableBlurBehindWindow(wt.HWND(island.hwnd), ctypes.byref(bb))
            gdi.DeleteObject(wt.HANDLE(rgn))
            # pywebview switches on the dark Mica backdrop in dark mode (and
            # again on every theme change); that was the #202020 box.
            no_backdrop()

        island._glass = glass

        def key():
            glass()
            wv = island.window.native.browser.webview          # used by the folder mapping below
            # The clip-saved card plays the clip: the page may not read E:            # directly, so the clips folder is mapped to a private host name
            # (WebView2 virtual host; nothing is copied).
            # (CoreWebView2 exists only once the engine has started: retried.)
            def map_clips():
                for _ in range(60):
                    done = []

                    def attempt():
                        core = wv.CoreWebView2
                        if core is not None:
                            from Microsoft.Web.WebView2.Core import CoreWebView2HostResourceAccessKind
                            os.makedirs(clips_dir(), exist_ok=True)
                            core.SetVirtualHostNameToFolderMapping("clips.island", clips_dir(),
                                                                   CoreWebView2HostResourceAccessKind.Allow)
                            os.makedirs(extras.THUMBS, exist_ok=True)
                            core.SetVirtualHostNameToFolderMapping("thumbs.island", extras.THUMBS,
                                                                   CoreWebView2HostResourceAccessKind.Allow)
                            done.append(1)
                    try:
                        ui_thread(island.window, attempt)
                    except Exception as e:
                        dbg("clips mapping", repr(e))
                    if done:
                        dbg("clips mapped")
                        return
                    time.sleep(0.5)
            threading.Thread(target=map_clips, daemon=True).start()
            try:
                form.update_title_bar_theme = no_backdrop
            except Exception:
                pass

        def no_backdrop():
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                wt.HWND(island.hwnd), 38, ctypes.byref(ctypes.c_int(1)), 4)   # DWMWA_SYSTEMBACKDROP_TYPE = none
        ui_thread(island.window, key)
        island.place_initial()
        ui_thread(island.window, lambda: island.set_region(False))
        threading.Thread(target=island.media_loop, daemon=True).start()
        threading.Thread(target=tray, args=(island,), daemon=True).start()
        threading.Thread(target=island.hover_loop, daemon=True).start()
        threading.Thread(target=island.rec_loop, daemon=True).start()
        threading.Thread(target=island.prayer_loop, daemon=True).start()
        threading.Thread(target=island.first_city, daemon=True).start()
        threading.Thread(target=island.update_loop, daemon=True).start()
        threading.Thread(target=island.extras_loop, daemon=True).start()
        threading.Thread(target=island.clip_watch, daemon=True).start()
        # Dropped files: pywebview gives the real path to a Python handler.
        try:
            from webview.dom import DOMEventHandler
            island.window.dom.document.events.drop += DOMEventHandler(island.on_drop, True, True)
        except Exception as e:
            dbg("drop handler", repr(e))

    def closing():
        """Alt+F4, Ctrl+F4 or anything else asking the window to close is
        refused: only the tray menu's Quit ends the island."""
        if getattr(island, "quitting", False):
            return True
        dbg("close refused")
        return False
    island.window.events.closing += closing

    webview.start(started)


class IslandApi:
    """What window.pywebview.api exposes to bridge.js (names match bridge.js)."""
    def __init__(self, island):
        self._i = island

    def get_state(self):
        return self._i.get_state()

    def save_config(self, config):
        return self._i.save_config(config or {})

    def connect_spotify(self):
        return self._i.connect_spotify()

    def open_dashboard(self):
        return self._i.open_dashboard()

    def playback(self, action):
        return self._i.playback_action(action)

    def seek(self, position_ms):
        return self._i.seek(position_ms)

    def set_expanded(self, expanded):
        return self._i.set_expanded(expanded)

    def resize_expanded(self, size):
        return self._i.resize_expanded(size or {})

    def start_drag(self):
        return self._i.start_drag()

    def recenter(self):
        return self._i.recenter()

    def get_volume(self):
        return self._i.get_volume()

    def set_volume(self, level=None, muted=None):
        return self._i.set_volume(level, muted)

    def set_extra(self, px):
        return self._i.set_extra(px)

    def record(self, on):
        return self._i.record(bool(on))

    def get_prayers(self):
        return self._i.get_prayers()

    def hold_open(self, on):
        return self._i.hold_open(on)

    def chime(self):
        return self._i.chime()

    def set_pill_wide(self, on):
        return self._i.set_pill_wide(bool(on))

    def set_pill_width(self, px):
        return self._i.set_pill_width(px)

    def set_big(self, on):
        return self._i.set_big(on)

    def open_file(self, path):
        return self._i.open_file(path)

    def copy_file(self, path):
        return self._i.copy_file(path)

    def get_today(self):
        return self._i.get_today()

    def get_clips(self):
        return self._i.get_clips()

    def open_clips_folder(self):
        return self._i.open_clips_folder()

    def get_sys(self):
        return extras.sys_stats()

    def ping(self):
        return extras.ping()

    def speedtest(self):
        try:
            return extras.speedtest()
        except Exception:
            return None

    def mic_muted(self):
        return extras.mic_muted()

    def set_mic(self, muted):
        return extras.set_mic_muted(bool(muted))

    def snip(self):
        extras.snip()
        return True

    def get_clipboard(self):
        cb = getattr(self._i, "clipboard", None)
        return list(cb.items) if cb else []

    def copy_text(self, text):
        threading.Thread(target=extras.copy_text, args=(str(text),), daemon=True).start()
        return True

    def log(self, msg):
        dbg("page:", str(msg)[:300])
        return True

    def open_settings(self):
        threading.Thread(target=self._i.open_settings, daemon=True).start()
        return True

    def restart_app(self):
        threading.Thread(target=self._i.restart_app, daemon=True).start()
        return True

    def update_answer(self, go):
        return self._i.update_answer(bool(go))

    def swiped(self):
        return self._i.swiped()


class SettingsApi(IslandApi):
    """The settings window's API. Its live preview runs the real island page,
    so it gets the same calls, but everything that would move, resize, hold,
    ring or record the REAL island does nothing here."""
    def _noop(self, *a, **k):
        return True
    set_expanded = resize_expanded = start_drag = recenter = set_extra = _noop
    hold_open = chime = set_pill_wide = set_pill_width = set_big = snip = _noop
    save_config = open_settings = restart_app = update_answer = swiped = _noop

    def record(self, on):
        return None

    def get_layout(self):
        return self._i.get_layout()

    def set_layout(self, layout):
        return self._i.set_layout(layout or {})

    def reset_layout(self):
        return self._i.reset_layout()

    def get_position(self):
        return self._i.get_position()

    def set_position(self, x_pct=None, top=None):
        return self._i.set_position(x_pct, top)

    def reset_position(self):
        return self._i.reset_position()

    def get_clipper(self):
        return self._i.get_clipper()

    def set_clipper(self, settings):
        return self._i.set_clipper(settings)

    def start_clipper(self):
        return self._i.start_clipper()

    def pick_folder(self):
        return self._i.pick_folder()

    def get_location(self):
        return self._i.get_location()

    def search_city(self, q):
        return self._i.search_city(q)

    def get_update(self):
        return self._i.get_update()

    def check_update(self):
        return self._i.check_update()

    def set_auto_update(self, on):
        return self._i.set_auto_update(bool(on))

    def open_release(self):
        return self._i.open_release()

    def set_location(self, loc=None, method=None, school=None):
        return self._i.set_location(loc, method, school)

    def open_clips_folder(self):
        return self._i.open_clips_folder()


if __name__ == "__main__":
    main()
