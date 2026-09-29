"""The island's extra live data. Everything here is light: small fetches that
are cached on disk, and cheap polls of Windows state.

    today()          weather (Open-Meteo) + Hijri date and the next Ramadan /
                     Eid (Aladhan), refreshed every 30 min / daily, cached
    lyrics(...)      one song's synced lines from LRCLIB (free, no account)
    power()          (on_ac, percent) from GetSystemPowerStatus
    bt_output()      the default sound output if it is a Bluetooth device:
                     (name, battery % or None), else None
    upload(path)     put a file on mutate.lol (anonymous, or with a personal upload key)
"""
import ctypes
import ctypes.wintypes as wt
import datetime
import json
import os
import urllib.error
import shutil
import sys
import re
import subprocess
import time
import urllib.parse
import urllib.request

import prayer

DIR = os.path.join(os.environ["APPDATA"], "LyricsIslandLite")
TODAY_CACHE = os.path.join(DIR, "today.json")
KEY_FILE = os.path.join(DIR, "mutate-upload-key.txt")
UA = {"User-Agent": "hop-island"}
NO_WINDOW = 0x08000000


def _get(url, timeout=10):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# ------------------------------------------------------------------ today page
def _weather():
    if prayer.LAT is None:                    # no city chosen yet
        return None
    d = _get(f"https://api.open-meteo.com/v1/forecast?latitude={prayer.LAT}&longitude={prayer.LON}"
             "&current=temperature_2m,apparent_temperature,weather_code"
             "&daily=temperature_2m_max,temperature_2m_min&timezone=auto&forecast_days=1")
    c = d["current"]
    return {"temp": c["temperature_2m"], "feels": c["apparent_temperature"], "code": c["weather_code"],
            "high": d["daily"]["temperature_2m_max"][0], "low": d["daily"]["temperature_2m_min"][0],
            "at": time.time()}


def _hijri():
    today = datetime.date.today()
    h = _get(f"https://api.aladhan.com/v1/gToH/{today:%d-%m-%Y}")["data"]["hijri"]
    year = int(h["year"])
    events = []
    for name, dm in (("Ramadan", "01-09"), ("Eid al-Fitr", "01-10"), ("Eid al-Adha", "10-12")):
        for y in (year, year + 1):
            g = _get(f"https://api.aladhan.com/v1/hToG/{dm}-{y}")["data"]["gregorian"]["date"]
            day = datetime.datetime.strptime(g, "%d-%m-%Y").date()
            if day >= today:
                events.append({"name": name, "date": day.isoformat()})
                break
    return {"day": h["day"], "month": h["month"]["en"], "year": h["year"], "events": events,
            "for": today.isoformat()}


def today():
    """Weather (fresh within 30 min) and Hijri (fresh for today), from the
    cache when the network is down. Days-until are counted here, every call."""
    try:
        with open(TODAY_CACHE, encoding="utf-8") as fh:
            cache = json.load(fh)
    except (OSError, ValueError):
        cache = {}
    if not isinstance(cache, dict):
        cache = {}
    changed = False
    if time.time() - (cache.get("weather") or {}).get("at", 0) > 1800:
        try:
            cache["weather"], changed = _weather(), True
        except Exception:
            pass
    if (cache.get("hijri") or {}).get("for") != datetime.date.today().isoformat():
        try:
            cache["hijri"], changed = _hijri(), True
        except Exception:
            pass
    if changed:
        os.makedirs(DIR, exist_ok=True)
        with open(TODAY_CACHE, "w", encoding="utf-8") as fh:
            json.dump(cache, fh)
    h = cache.get("hijri")
    if h:
        today_ = datetime.date.today()
        for e in h["events"]:
            e["days"] = (datetime.date.fromisoformat(e["date"]) - today_).days
    return {"weather": cache.get("weather"), "hijri": h, "prayers": prayer.today_and_tomorrow()}


# ------------------------------------------------------------------ lyrics
LRC = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")


def lyrics(title, artist, album="", duration_ms=0):
    """[[ms, line], ...] for a song, or [] (LRCLIB; one request per song)."""
    q = {"track_name": title, "artist_name": artist}
    if album:
        q["album_name"] = album
    if duration_ms:
        q["duration"] = round(duration_ms / 1000)
    for url in ("https://lrclib.net/api/get?" + urllib.parse.urlencode(q),
                "https://lrclib.net/api/search?" + urllib.parse.urlencode({"track_name": title, "artist_name": artist})):
        try:
            d = _get(url, timeout=8)
        except Exception:
            continue
        if isinstance(d, list):
            d = next((x for x in d if x.get("syncedLyrics")), None)
        synced = (d or {}).get("syncedLyrics")
        if synced:
            out = []
            for line in synced.splitlines():
                stamps = LRC.findall(line)
                text = LRC.sub("", line).strip()
                for m, s in stamps:
                    out.append([int((int(m) * 60 + float(s)) * 1000), text])
            return sorted(out)
    return []


# ------------------------------------------------------------------ power
class _SPS(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte), ("BatteryLifePercent", ctypes.c_ubyte),
                ("SystemStatusFlag", ctypes.c_ubyte), ("BatteryLifeTime", wt.DWORD), ("BatteryFullLifeTime", wt.DWORD)]


def power():
    s = _SPS()
    ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s))
    pct = s.BatteryLifePercent if s.BatteryLifePercent <= 100 else None
    return s.ACLineStatus == 1, pct


# ------------------------------------------------------------------ bluetooth output
def default_output():
    """The default sound output's friendly name, e.g. 'Headphones (Soundcore Q30)'."""
    import comtypes
    from pycaw.pycaw import AudioUtilities
    try:
        comtypes.CoInitialize()
    except OSError:
        pass
    dev = AudioUtilities.GetSpeakers()
    name = getattr(dev, "FriendlyName", None)
    if name is None:
        name = AudioUtilities.CreateDevice(dev).FriendlyName
    return name


def bt_output(name):
    """(device name, battery %) if the output `name` is a Bluetooth device, else
    None. Windows names the endpoint 'Headphones (<device>)'; the device itself
    is a Bluetooth PnP node whose battery (when the device reports one) is the
    property {104EA319-...} 2. One PowerShell call, only when the output changes."""
    inner = re.search(r"\(([^()]+)\)\s*$", name or "")
    device = (inner.group(1) if inner else name or "").strip()
    if not device:
        return None
    ps = ("$d = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | Where-Object { $_.FriendlyName -eq '"
          + device.replace("'", "''") + "' -and $_.InstanceId -like 'BTHENUM*' } | Select-Object -First 1; "
          "if ($d) { $b = (Get-PnpDeviceProperty -InstanceId $d.InstanceId -KeyName "
          "'{104EA319-6EE2-4701-BD47-8DDBF425BBE5} 2' -ErrorAction SilentlyContinue).Data; "
          "'BT|' + $b } else { $all = Get-PnpDevice -Class Bluetooth -PresentOnly -ErrorAction SilentlyContinue | "
          "Where-Object { $_.FriendlyName -eq '" + device.replace("'", "''") + "' } | Select-Object -First 1; "
          "if ($all) { $b = (Get-PnpDeviceProperty -InstanceId $all.InstanceId -KeyName "
          "'{104EA319-6EE2-4701-BD47-8DDBF425BBE5} 2' -ErrorAction SilentlyContinue).Data; 'BT|' + $b } }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                             timeout=15, creationflags=NO_WINDOW).stdout.strip()
    except Exception:
        return None
    if not out.startswith("BT|"):
        return None
    bat = out[3:].strip()
    return device, (int(bat) if bat.isdigit() else None)


# ------------------------------------------------------------------ mutate.lol upload
SITE = "https://mutate.lol"
SMALL = 4 * 1024 * 1024


def _key():
    try:
        with open(KEY_FILE, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return None


def _call(method, url, key, data=None, ctype=None, timeout=120):
    headers = {"Authorization": f"Bearer {key}", **UA}
    if ctype:
        headers["Content-Type"] = ctype
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8")).get("error")
        except Exception:
            msg = None
        raise RuntimeError(msg or f"mutate.lol said {e.code}")


def _anon_upload(path, progress):
    """No upload key: mutate.lol's anonymous host. The link says "by
    Anonymous", shows no profile, and the file deletes itself in 7 days
    (50 MB max; images are checked)."""
    boundary = "----hop" + os.urandom(8).hex()
    with open(path, "rb") as fh:
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"upload\"\r\n"
                "Content-Type: application/octet-stream\r\n\r\n").encode() + fh.read() + f"\r\n--{boundary}--\r\n".encode()
    progress(0.5)
    req = urllib.request.Request(f"{SITE}/api/files/anon", data=body, method="POST",
                                 headers={**UA, "Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            d = json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8")).get("error")
        except Exception:
            msg = None
        raise RuntimeError(msg or f"mutate.lol said {e.code}")
    progress(1.0)
    return d["url"]


def upload(path, progress=lambda f: None):
    """Upload a dropped file. With a personal upload key (mutate-upload-key.txt
    in the settings folder) it goes to that account; without one, to the
    anonymous host. Returns the share link."""
    key = _key()
    if not key:
        return _anon_upload(path, progress)
    size = os.path.getsize(path)
    if size <= SMALL:
        boundary = "----island" + os.urandom(8).hex()
        with open(path, "rb") as fh:
            body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"upload\"\r\n"
                    "Content-Type: application/octet-stream\r\n\r\n").encode() + fh.read() + f"\r\n--{boundary}--\r\n".encode()
        progress(0.5)
        d = _call("POST", f"{SITE}/api/files", key, body, f"multipart/form-data; boundary={boundary}")
    else:
        start = _call("POST", f"{SITE}/api/files/big?step=start", key, json.dumps({"size": size}).encode(), "application/json")
        k, part = start["key"], start["partSize"]
        parts, n = [], 1
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(part)
                if not chunk:
                    break
                r = _call("PUT", f"{SITE}/api/files/big?step=part&key={k}&n={n}", key, chunk, "application/octet-stream", 600)
                parts.append({"n": n, "etag": r["etag"]})
                progress(min(0.95, fh.tell() / size))
                n += 1
        d = _call("POST", f"{SITE}/api/files/big?step=finish", key, json.dumps({"key": k, "parts": parts}).encode(), "application/json")
    progress(1.0)
    return f"{SITE}/i/{d['file']['link']}"


def copy_text(text):
    subprocess.run(["powershell", "-NoProfile", "-Command", "Set-Clipboard -Value $input"], input=text, text=True,
                   creationflags=NO_WINDOW, timeout=10)


def copy_file(path):
    """Put the FILE on the clipboard (paste into Discord uploads it)."""
    subprocess.run(["powershell", "-NoProfile", "-Command", f"Set-Clipboard -Path '{path.replace(chr(39), chr(39) * 2)}'"],
                   creationflags=NO_WINDOW, timeout=10)


# ------------------------------------------------------------------ page 3: recent clips
CLIPS = os.path.join(os.path.expanduser("~"), "Videos", "Hop Clips")   # the clipper's folder; host.py sets it
_LEN = re.compile(r"\((\d+)s\)|\((\d+)min\)")


APP_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))


def _find_tool(name):
    """The ffmpeg the installer put in <install>\\ffmpeg (shared with the
    clipper), one next to the app, $HOP_FFMPEG_DIR, or PATH."""
    for d in (os.environ.get("HOP_FFMPEG_DIR", ""), os.path.join(APP_DIR, "..", "ffmpeg"),
              os.path.join(APP_DIR, "ffmpeg"), APP_DIR):
        if d and os.path.exists(os.path.join(d, name)):
            return os.path.abspath(os.path.join(d, name))
    return shutil.which(name) or name


FFMPEG = _find_tool("ffmpeg.exe")
THUMBS = os.path.join(os.environ.get("LOCALAPPDATA", DIR), "LyricsIslandLite", "thumbs")


def thumb(path):
    """A small JPEG of the clip (320 px, a frame 1 s in), made once and cached
    by name + time, so page 3 shows three tiny pictures instead of loading
    three 1080p videos. Returns the file name inside THUMBS, or None."""
    import hashlib
    try:
        key = hashlib.sha1(f"{os.path.basename(path)}|{os.path.getmtime(path)}".encode()).hexdigest()[:16] + ".jpg"
    except OSError:
        return None
    out = os.path.join(THUMBS, key)
    if os.path.exists(out):
        return key
    os.makedirs(THUMBS, exist_ok=True)
    for at in ("1", "0"):
        try:
            subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-ss", at, "-i", path, "-frames:v", "1",
                            "-vf", "scale=320:-2", "-q:v", "5", out], creationflags=NO_WINDOW, timeout=20)
        except Exception:
            pass
        if os.path.exists(out) and os.path.getsize(out) > 0:
            break
    # keep the cache small: the newest 24 pictures
    try:
        olds = sorted((os.path.join(THUMBS, f) for f in os.listdir(THUMBS)), key=os.path.getmtime)[:-24]
        for f in olds:
            os.remove(f)
    except OSError:
        pass
    return key if os.path.exists(out) else None


def recent_clips(n=3):
    """The newest clips / recordings: name, path, size, when, length (from the name)."""
    try:
        files = [os.path.join(CLIPS, f) for f in os.listdir(CLIPS) if f.lower().endswith(".mp4")]
    except OSError:
        return []
    files.sort(key=os.path.getmtime, reverse=True)
    out = []
    for p in files[:n]:
        m = _LEN.search(os.path.basename(p))
        secs = int(m.group(1)) if m and m.group(1) else int(m.group(2)) * 60 if m else None
        out.append({"name": os.path.basename(p), "path": p, "size": os.path.getsize(p),
                    "at": os.path.getmtime(p), "seconds": secs,
                    "kind": "recording" if os.path.basename(p).startswith("recording") else "clip"})
    return out


# ------------------------------------------------------------------ page 4: PC & utility
class _PDH:
    """CPU and GPU load the way Task Manager counts them (PDH, no PowerShell).
    CPU is "% Processor Utility" (Task Manager's number; psutil's % Processor
    Time reads differently on turbo CPUs). GPU is, per adapter, every engine
    type's summed utilisation, and the busiest type wins (Task Manager's GPU %)."""
    class _ITEM(ctypes.Structure):      # PDH_FMT_COUNTERVALUE_ITEM_W: 24 bytes on x64
        _fields_ = [("name", ctypes.c_wchar_p), ("status", wt.DWORD), ("value", ctypes.c_double)]

    def __init__(self):
        self.pdh = ctypes.windll.pdh
        self.q, self.gpu, self.cpu = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
        self.pdh.PdhOpenQueryW(None, 0, ctypes.byref(self.q))
        self.pdh.PdhAddEnglishCounterW(self.q, r"\GPU Engine(*)\Utilization Percentage", 0, ctypes.byref(self.gpu))
        self.pdh.PdhAddEnglishCounterW(self.q, r"\Processor Information(_Total)\% Processor Utility", 0, ctypes.byref(self.cpu))
        self.pdh.PdhCollectQueryData(self.q)

    def _array(self, counter):
        size, count = wt.DWORD(0), wt.DWORD(0)
        self.pdh.PdhGetFormattedCounterArrayW(counter, 0x8200, ctypes.byref(size), ctypes.byref(count), None)   # DOUBLE | NOCAP100
        if not size.value:
            return []
        buf = ctypes.create_string_buffer(size.value)
        if self.pdh.PdhGetFormattedCounterArrayW(counter, 0x8200, ctypes.byref(size), ctypes.byref(count), buf):
            return []
        items = ctypes.cast(buf, ctypes.POINTER(self._ITEM))
        return [(items[i].name, items[i].value) for i in range(count.value) if items[i].status in (0, 1)]

    def read(self):
        """(cpu %, gpu %); either may be None. Needs about a second between calls."""
        self.pdh.PdhCollectQueryData(self.q)
        cpu = self._array(self.cpu)
        per = {}
        for name, v in self._array(self.gpu):
            m = re.search(r"luid_(\w+?)_phys.*engtype_(\w+)", name or "")
            if m:
                per[m.groups()] = per.get(m.groups(), 0.0) + v
        return (min(100.0, cpu[0][1]) if cpu else None,
                min(100.0, max(per.values())) if per else None)


_gpu = None


def sys_stats():
    import psutil
    global _gpu
    if _gpu is None:
        try:
            _gpu = _PDH()
        except Exception:
            _gpu = False
    vm = psutil.virtual_memory()
    disks = {}
    # Slot "C" = the system drive, slot "E" = the biggest other fixed drive
    # (the island's two disk gauges), each with its real letter for the label.
    system = os.environ.get("SystemDrive", "C:").rstrip(":\\").upper()
    found = []
    try:
        for part in psutil.disk_partitions(all=False):
            letter = part.mountpoint.rstrip(":\\").upper()
            if len(letter) != 1 or "cdrom" in part.opts or not part.fstype:
                continue
            try:
                d = psutil.disk_usage(part.mountpoint)
            except OSError:
                continue
            found.append((letter, d))
    except Exception:
        pass
    found.sort(key=lambda x: (x[0] != system, -x[1].total))
    for slot, (letter, d) in zip(("C", "E"), found):
        disks[slot] = {"free": d.free, "total": d.total, "letter": letter}
    cpu, gpu = _gpu.read() if _gpu else (None, None)
    if cpu is None:
        cpu = psutil.cpu_percent(0.2)
    return {"cpu": cpu, "gpu": gpu,
            "ram": {"used": vm.used, "total": vm.total}, "disks": disks}


def ping(host="1.1.1.1"):
    try:
        out = subprocess.run(["ping", "-n", "1", "-w", "1500", host], capture_output=True, text=True,
                             timeout=4, creationflags=NO_WINDOW).stdout
    except Exception:
        return None
    m = re.search(r"time[=<](\d+)ms", out)
    return int(m.group(1)) if m else None


def speedtest():
    """Download speed in Mbps: 15 MB from Cloudflare's speed test endpoint."""
    t = time.perf_counter()
    got = 0
    # Cloudflare refuses non-browser clients (403), so it is asked like its own page asks.
    req = urllib.request.Request("https://speed.cloudflare.com/__down?bytes=15000000",
                                 headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                                          "Referer": "https://speed.cloudflare.com/"})
    with urllib.request.urlopen(req, timeout=20) as r:
        while True:
            chunk = r.read(262144)
            if not chunk:
                break
            got += len(chunk)
    return round(got * 8 / (time.perf_counter() - t) / 1e6)


def _mic():
    import comtypes
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    try:
        comtypes.CoInitialize()
    except OSError:
        pass
    dev = AudioUtilities.GetMicrophone()
    if dev is None:
        return None
    iface = dev.Activate(IAudioEndpointVolume._iid_, comtypes.CLSCTX_ALL, None)
    return iface.QueryInterface(IAudioEndpointVolume)


def mic_muted():
    try:
        m = _mic()
        return None if m is None else bool(m.GetMute())
    except Exception:
        return None


def set_mic_muted(on):
    try:
        m = _mic()
        if m is not None:
            m.SetMute(1 if on else 0, None)
    except Exception:
        pass
    return mic_muted()


def snip():
    """Windows' own screen snip (the Win+Shift+S overlay)."""
    os.startfile("ms-screenclip:")


# ------------------------------------------------------------------ clipboard history (memory only)
class Clipboard:
    """The last few TEXT things copied, kept in memory only (never written
    anywhere). Anything a password manager marks as private is skipped:
    KeePassXC and others set these formats exactly so tools like this don't
    record them."""
    PRIVATE = ("ExcludeClipboardContentFromMonitorProcessing", "Clipboard Viewer Ignore")

    def __init__(self, keep=5):
        self.keep, self.items, self.seq = keep, [], None
        u = ctypes.windll.user32
        u.RegisterClipboardFormatW.restype = wt.UINT
        self.private = [u.RegisterClipboardFormatW(n) for n in self.PRIVATE]
        self.no_history = u.RegisterClipboardFormatW("CanIncludeInClipboardHistory")

    def poll(self):
        u, k = ctypes.windll.user32, ctypes.windll.kernel32
        seq = u.GetClipboardSequenceNumber()
        if seq == self.seq:
            return False
        self.seq = seq
        if any(u.IsClipboardFormatAvailable(f) for f in self.private) or u.IsClipboardFormatAvailable(self.no_history):
            return False
        if not u.IsClipboardFormatAvailable(13) or not u.OpenClipboard(None):   # CF_UNICODETEXT
            return False
        try:
            u.GetClipboardData.restype = wt.HANDLE
            k.GlobalLock.restype = ctypes.c_void_p
            k.GlobalLock.argtypes = [wt.HANDLE]
            k.GlobalUnlock.argtypes = [wt.HANDLE]
            h = u.GetClipboardData(13)
            p = k.GlobalLock(h) if h else None
            text = ctypes.wstring_at(p) if p else ""
            if h:
                k.GlobalUnlock(h)
        finally:
            u.CloseClipboard()
        text = text.strip()
        if not text:
            return False
        self.items = [text[:500]] + [t for t in self.items if t != text[:500]]
        self.items = self.items[: self.keep]
        return True


def forget_weather():
    """The city changed: fetch the weather again on the next today() call."""
    try:
        with open(TODAY_CACHE, encoding="utf-8") as fh:
            cache = json.load(fh)
        cache.pop("weather", None)
        with open(TODAY_CACHE, "w", encoding="utf-8") as fh:
            json.dump(cache, fh)
    except (OSError, ValueError):
        pass
