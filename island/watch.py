"""What the island watches for on its own (host.py polls these):

    NotifWatcher     new Windows notifications (Discord, mail, ...), read from the
                     user's own notification database, as island pop-ups
    privacy_in_use() which apps are using the microphone / camera right now
    foreground_exe() the app in front (to hide the island in chosen apps)
    parse_ics()      upcoming events from a calendar's iCal (.ics) link

No package identity is needed for any of it, so it works for a plain desktop
app: Windows' UserNotificationListener refuses unpackaged apps, but the
notifications it would hand out are in wpndatabase.db, readable by the user."""
import ctypes
import datetime as dt
import os
import re
import sqlite3
import urllib.parse
import winreg
import xml.etree.ElementTree as ET
from ctypes import wintypes as wt

# ------------------------------------------------------------------ notifications
WPN_DB = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows\Notifications\wpndatabase.db")

# Windows' own chatter, and Hop itself: never shown as island pop-ups.
IGNORED_APPS = ("Windows.SystemToast", "Microsoft.Windows.Explorer", "Microsoft.WindowsStore",
                "Windows.Defender", "MicrosoftWindows.Client", "HopIsland", "HopClipper", "hop")

KNOWN_NAMES = {
    "discord": "Discord", "spotify": "Spotify", "outlook": "Outlook", "olk": "Outlook", "teams": "Teams",
    "whatsapp": "WhatsApp", "telegram": "Telegram", "chrome": "Chrome", "msedge": "Edge", "brave": "Brave",
    "firefox": "Firefox", "slack": "Slack", "steam": "Steam", "roblox": "Roblox", "mail": "Mail",
}


def app_display_name(aumid):
    """A readable app name from a notification's app id:
    'com.squirrel.Discord.Discord' -> 'Discord', 'Chrome' -> 'Chrome',
    '{...}\\WindowsPowerShell\\v1.0\\powershell.exe' -> 'Powershell'."""
    if not aumid:
        return "Notification"
    tail = re.split(r"[\\/!]", aumid)[-1]
    tail = re.sub(r"\.exe$", "", tail, flags=re.I)
    parts = [p for p in re.split(r"[._]", tail) if p and not p.isdigit()]
    for p in reversed(parts):
        if p.lower() in KNOWN_NAMES:
            return KNOWN_NAMES[p.lower()]
    word = parts[-1] if parts else tail
    return word[:1].upper() + word[1:] if word else "Notification"


def toast_image(payload):
    """The picture a toast shows beside its text (Discord and other Electron
    apps put the SENDER's avatar there, placement="appLogoOverride"): a local
    path or an https link, or ''."""
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", "replace")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return ""
    imgs = list(root.iter("image"))
    imgs.sort(key=lambda i: i.get("placement") != "appLogoOverride")       # the sender's picture first
    for img in imgs:
        src = (img.get("src") or "").strip()
        if src.lower().startswith("https://"):
            return src
        if src.lower().startswith("file:///"):
            src = urllib.parse.unquote(src[8:]).replace("/", "\\")
        if re.match(r"^[a-zA-Z]:\\", src) and os.path.isfile(src):
            return src
    return ""


def image_data_url(src, size=96):
    """A local file or https picture as a small round-cropped PNG data: URL."""
    import base64
    import io
    try:
        from PIL import Image, ImageDraw
        if src.lower().startswith("https://"):
            import urllib.request
            with urllib.request.urlopen(urllib.request.Request(src, headers={"User-Agent": "Hop Island"}), timeout=5) as r:
                data = r.read(2_000_000)
        else:
            with open(src, "rb") as fh:
                data = fh.read(2_000_000)
        im = Image.open(io.BytesIO(data)).convert("RGBA")
        w, h = im.size
        side = min(w, h)
        im = im.crop(((w - side) // 2, (h - side) // 2, (w + side) // 2, (h + side) // 2)).resize((size, size), Image.LANCZOS)
        mask = Image.new("L", (size * 4, size * 4), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
        im.putalpha(mask.resize((size, size), Image.LANCZOS))
        buf = io.BytesIO()
        im.save(buf, "PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""


def parse_toast(payload):
    """(title, body) from a toast's XML payload, or None if it has no text."""
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", "replace")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return None
    texts = [(t.text or "").strip() for t in root.iter("text")]
    texts = [t for t in texts if t]
    if not texts:
        return None
    return texts[0][:120], " ".join(texts[1:])[:200]


class NotifWatcher:
    """New toasts since the last poll. Starts at whatever is newest now, so
    the island never replays old notifications on start."""

    def __init__(self, db=WPN_DB):
        self.db = db
        self.last = self._newest()

    def _connect(self):
        return sqlite3.connect(f"file:{self.db}?mode=ro", uri=True, timeout=1)

    def _newest(self):
        try:
            con = self._connect()
            try:
                row = con.execute("select max([Order]) from Notification").fetchone()
            finally:
                con.close()
            return row[0] or 0
        except sqlite3.Error:
            return 0

    def poll(self):
        try:
            con = self._connect()
            try:
                rows = con.execute(
                    "select n.[Order], n.Payload, h.PrimaryId from Notification n "
                    "join NotificationHandler h on h.RecordId = n.HandlerId "
                    "where n.Type = 'toast' and n.[Order] > ? order by n.[Order]", (self.last,)).fetchall()
            finally:
                con.close()
        except sqlite3.Error:
            return []
        out = []
        for order, payload, aumid in rows:
            self.last = max(self.last, order)
            if any(x.lower() in (aumid or "").lower() for x in IGNORED_APPS):
                continue
            got = parse_toast(payload)
            if got:
                out.append({"app": app_display_name(aumid), "title": got[0], "body": got[1], "image": toast_image(payload)})
        return out


# ------------------------------------------------------------------ microphone / camera in use
CONSENT = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore"


def _apps_using(capability):
    """Apps whose LastUsedTimeStop is 0 (still using it) under the consent store."""
    found = []

    def walk(path, packaged):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path)
        except OSError:
            return
        with key:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(key, i)
                except OSError:
                    break
                i += 1
                if sub == "NonPackaged":
                    walk(path + "\\" + sub, False)
                    continue
                try:
                    with winreg.OpenKey(key, sub) as k:
                        stop, _ = winreg.QueryValueEx(k, "LastUsedTimeStop")
                        start, _ = winreg.QueryValueEx(k, "LastUsedTimeStart")
                except OSError:
                    continue
                if stop == 0 and start:
                    found.append(app_display_name(sub.replace("#", "\\")))
    walk(CONSENT + "\\" + capability, True)
    return sorted(set(found))


def privacy_in_use():
    """{'mic': [apps], 'cam': [apps]} using the microphone / camera right now."""
    return {"mic": _apps_using("microphone"), "cam": _apps_using("webcam")}


# ------------------------------------------------------------------ the app in front
_u32 = ctypes.windll.user32
_k32 = ctypes.windll.kernel32
_u32.GetForegroundWindow.restype = wt.HWND


def foreground_exe():
    """The front window's program, lowercase, like 'robloxplayerbeta.exe', or ''."""
    try:
        h = _u32.GetForegroundWindow()
        pid = wt.DWORD()
        _u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        hp = _k32.OpenProcess(0x1000, False, pid.value)          # QUERY_LIMITED_INFORMATION
        if not hp:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            n = wt.DWORD(1024)
            if not _k32.QueryFullProcessImageNameW(hp, 0, buf, ctypes.byref(n)):
                return ""
            return os.path.basename(buf.value).lower()
        finally:
            _k32.CloseHandle(hp)
    except Exception:
        return ""


def clean_hide_list(raw):
    """The settings' 'hide in these apps' text -> ['roblox.exe', ...]: one per
    line or comma, '.exe' added when missing, duplicates and junk dropped."""
    out = []
    for part in re.split(r"[\n,;]+", str(raw or "")):
        name = os.path.basename(part.strip().strip('"')).lower()
        if not name or not re.fullmatch(r"[\w .()+-]+", name):
            continue
        if not name.endswith(".exe"):
            name += ".exe"
        if name not in out:
            out.append(name)
    return out[:40]


# ------------------------------------------------------------------ calendar (iCal link)
def _unfold(text):
    return re.sub(r"\r?\n[ \t]", "", text.replace("\r\n", "\n"))


def _when(value, params):
    """An iCal DTSTART/DTEND value -> (local naive datetime, all_day)."""
    v = value.strip()
    if "VALUE=DATE" in params or re.fullmatch(r"\d{8}", v):
        return dt.datetime.strptime(v[:8], "%Y%m%d"), True
    if v.endswith("Z"):
        utc = dt.datetime.strptime(v, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc)
        return utc.astimezone().replace(tzinfo=None), False
    return dt.datetime.strptime(v[:15], "%Y%m%dT%H%M%S"), False   # TZID=...: taken as local time


def _unescape(t):
    return t.replace("\\n", " ").replace("\\N", " ").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\").strip()


def parse_ics(text, now=None, days=7, limit=8):
    """The next events (within `days`) from an iCal file, soonest first:
    [{'title', 'start' (iso), 'end' (iso), 'allDay'}]. Repeats with
    FREQ=DAILY/WEEKLY (INTERVAL, COUNT, UNTIL) are expanded; other repeats
    show their first time only."""
    now = now or dt.datetime.now()
    horizon = now + dt.timedelta(days=days)
    events = []
    for block in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", _unfold(text or ""), flags=re.S):
        props = {}
        for line in block.split("\n"):
            if ":" not in line:
                continue
            head, value = line.split(":", 1)
            name, _, params = head.partition(";")
            props.setdefault(name.upper(), (value, params.upper()))
        if "DTSTART" not in props or props.get("STATUS", ("",))[0].strip().upper() == "CANCELLED":
            continue
        try:
            start, all_day = _when(*props["DTSTART"])
            end = _when(*props["DTEND"])[0] if "DTEND" in props else start + (dt.timedelta(days=1) if all_day else dt.timedelta(hours=1))
        except ValueError:
            continue
        title = _unescape(props.get("SUMMARY", ("(no title)",))[0]) or "(no title)"
        length = end - start
        starts = [start]
        rule = props.get("RRULE", ("",))[0].upper()
        if rule:
            r = dict(p.split("=", 1) for p in rule.split(";") if "=" in p)
            step = {"DAILY": dt.timedelta(days=1), "WEEKLY": dt.timedelta(weeks=1)}.get(r.get("FREQ"))
            if step:
                step *= max(1, int(r.get("INTERVAL", "1") or 1))
                count = int(r["COUNT"]) if r.get("COUNT", "").isdigit() else None
                until = None
                if r.get("UNTIL"):
                    try:
                        until = _when(r["UNTIL"], "")[0]
                    except ValueError:
                        until = None
                t, n, starts = start, 1, []
                while t <= horizon and (count is None or n <= count) and (until is None or t <= until) and n < 5000:
                    starts.append(t)
                    t, n = t + step, n + 1
        where = _unescape(props.get("LOCATION", ("",))[0])
        text = " ".join(_unescape(props.get(k, ("",))[0]) for k in ("LOCATION", "URL", "DESCRIPTION", "X-GOOGLE-CONFERENCE"))
        uid = props.get("UID", ("",))[0].strip()
        for s in starts:
            e = s + length
            if e > now and s < horizon:
                events.append({"title": title[:80], "start": s.isoformat(timespec="minutes"),
                               "end": e.isoformat(timespec="minutes"), "allDay": all_day,
                               "location": where[:80], "link": meeting_link(text), "uid": uid[:120]})
    events.sort(key=lambda x: x["start"])
    return events[:limit]


MEETING = re.compile(r"https://(?:[\w-]+\.)?(?:zoom\.us/j/[\w?=&./-]+|meet\.google\.com/[a-z]{3}-[a-z]{4}-[a-z]{3}"
                     r"|teams\.microsoft\.com/l/meetup-join/[^\s\"<>]+|teams\.live\.com/meet/[^\s\"<>]+|[\w.-]*webex\.com/[^\s\"<>]+)", re.I)


def meeting_link(text):
    """The first Zoom / Meet / Teams / Webex link in an event's text, or ''."""
    m = MEETING.search(text or "")
    return m.group(0).rstrip(".,;)") if m else ""


def fetch_ics(url, timeout=10):
    """Download an iCal link (webcal:// works too)."""
    import urllib.request
    url = re.sub(r"^webcal://", "https://", (url or "").strip(), flags=re.I)
    if not re.match(r"^https?://", url, flags=re.I):
        raise ValueError("not a calendar link")
    req = urllib.request.Request(url, headers={"User-Agent": "Hop Island"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(4_000_000).decode("utf-8", "replace")
