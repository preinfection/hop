"""Hop Island on Linux: where the island's information comes from.

Windows gives Hop its media controls, notification database, battery and the
app in front; on Linux the same things come from:

  music          MPRIS (Spotify, Firefox, Chrome, Brave, VLC...) via playerctl
  volume         the player's own MPRIS volume
  battery        /sys/class/power_supply
  app in front   X11's _NET_ACTIVE_WINDOW (also under XWayland) -> its process
  full screen    that window's _NET_WM_STATE_FULLSCREEN
  notifications  the session D-Bus (org.freedesktop.Notifications.Notify)
  clipboard      wl-copy / xclip
  Wi-Fi name     NetworkManager (nmcli)
  start on login ~/.config/autostart/*.desktop
"""
import json
import os
import re
import shutil
import subprocess
import threading
import time

HOME = os.path.expanduser("~")
_NULL = subprocess.DEVNULL


def _run(cmd, timeout=2.0):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


def have(cmd):
    return shutil.which(cmd) is not None


# ---------------------------------------------------------------- battery
def power():
    """(on mains power, battery % or None)."""
    base = "/sys/class/power_supply"
    on_ac, pcts = None, []
    try:
        for name in os.listdir(base):
            p = os.path.join(base, name)
            kind = _read(os.path.join(p, "type"))
            if kind == "Mains":
                on_ac = (on_ac or False) or _read(os.path.join(p, "online")) == "1"
            elif kind == "Battery" and _read(os.path.join(p, "scope")) != "Device":
                c = _read(os.path.join(p, "capacity"))
                if c.isdigit():
                    pcts.append(int(c))
                st = _read(os.path.join(p, "status"))
                if st in ("Charging", "Full") and on_ac is None:
                    on_ac = True
    except OSError:
        pass
    pct = round(sum(pcts) / len(pcts)) if pcts else None
    return (True if on_ac is None and pct is None else bool(on_ac)), pct


def battery_details():
    """For the Battery page: health and cycles when the battery reports them."""
    base = "/sys/class/power_supply"
    try:
        for name in os.listdir(base):
            p = os.path.join(base, name)
            if _read(os.path.join(p, "type")) != "Battery":
                continue
            full = _num(p, "energy_full") or _num(p, "charge_full")
            design = _num(p, "energy_full_design") or _num(p, "charge_full_design")
            return {"health": round(full * 100 / design) if full and design else None, "cycles": _num(p, "cycle_count"),
                    "design": round(design / 1000) if design else None, "full": round(full / 1000) if full else None}
    except OSError:
        pass
    return {}


def _read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _num(p, name):
    v = _read(os.path.join(p, name))
    return int(v) if v.isdigit() else None


# ---------------------------------------------------------------- the app in front, and full screen (X11 / XWayland)
def _active_window():
    out = _run(["xprop", "-root", "_NET_ACTIVE_WINDOW"])
    m = re.search(r"window id # (0x[0-9a-f]+)", out)
    return m.group(1) if m and m.group(1) != "0x0" else None


def foreground_exe():
    """The front window's program, lowercase, like Windows' 'robloxplayerbeta.exe'
    but without '.exe' on Linux ('code', 'firefox', 'steam_app_...'). ''."""
    w = _active_window()
    if not w:
        return ""
    m = re.search(r"= (\d+)", _run(["xprop", "-id", w, "_NET_WM_PID"]))
    if m:
        try:
            with open(f"/proc/{m.group(1)}/comm", encoding="utf-8") as fh:
                return fh.read().strip().lower()
        except OSError:
            pass
    m = re.search(r'"([^"]+)"\s*$', _run(["xprop", "-id", w, "WM_CLASS"]))
    return m.group(1).lower() if m else ""


def app_label():
    """The app in front as a clip name: 'Roblox', 'Firefox', 'Minecraft'..."""
    w = _active_window()
    if not w:
        return ""
    m = re.search(r'"([^"]*)",\s*"([^"]*)"', _run(["xprop", "-id", w, "WM_CLASS"]))
    name = (m.group(2) or m.group(1)) if m else ""
    if not name or name.lower() in ("host.py", "clipper.py", "hop island", "hop-island", "hop-clipper", "xfdesktop", "desktop_window"):
        return ""
    if name.lower().startswith("steam_app_"):                    # Steam games: their window title
        t = re.search(r'= "(.*)"', _run(["xprop", "-id", w, "_NET_WM_NAME"]))
        return t.group(1)[:40] if t else "Steam game"
    known = {"robloxplayerbeta": "Roblox", "sober": "Roblox", "minecraft": "Minecraft", "code": "VS Code", "firefox": "Firefox",
             "google-chrome": "Chrome", "brave-browser": "Brave", "discord": "Discord", "steam": "Steam"}
    return known.get(name.lower(), name[:1].upper() + name[1:])


def screen_size():
    m = re.search(r"dimensions:\s+(\d+)x(\d+)", _run(["xdpyinfo"]))
    return (int(m.group(1)), int(m.group(2))) if m else (1920, 1080)


def workarea():
    """The usable screen area (minus panels) as (left, top, right, bottom)."""
    nums = re.findall(r"\d+", _run(["xprop", "-root", "_NET_WORKAREA"]).split("=", 1)[-1])
    if len(nums) >= 4:
        x, y, w, h = map(int, nums[:4])
        return x, y, x + w, y + h
    w, h = screen_size()
    return 0, 0, w, h


def fullscreen_app():
    """A full-screen window in front (a game, a video, a presentation)."""
    w = _active_window()
    return bool(w) and "_NET_WM_STATE_FULLSCREEN" in _run(["xprop", "-id", w, "_NET_WM_STATE"])


def focus_on():
    """Do not disturb: GNOME's switch, KDE's, or (elsewhere) off."""
    out = _run(["gsettings", "get", "org.gnome.desktop.notifications", "show-banners"]) if have("gsettings") else ""
    if out.strip() == "false":
        return True
    out = _run(["qdbus", "org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications.Inhibited"]) if have("qdbus") else ""
    return out.strip() == "true"


# ---------------------------------------------------------------- Wi-Fi (NetworkManager)
def wifi_ssid():
    """The connected Wi-Fi's name, '' when not connected, None without Wi-Fi."""
    if not have("nmcli"):
        return None
    out = _run(["nmcli", "-t", "-f", "TYPE,STATE,CONNECTION", "device"])
    wifi = [l.split(":", 2) for l in out.splitlines() if l.startswith("wifi:")]
    if not wifi:
        return None
    for _, state, name in wifi:
        if state == "connected":
            return name
    return ""


# ---------------------------------------------------------------- clipboard
def copy_text(text):
    for cmd in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
        if have(cmd[0]) and (cmd[0] != "wl-copy" or os.environ.get("WAYLAND_DISPLAY")):
            try:
                subprocess.run(cmd, input=text, text=True, timeout=5)
                return True
            except Exception:
                pass
    return False


def paste_text():
    for cmd in (["wl-paste", "-n"], ["xclip", "-selection", "clipboard", "-o"], ["xsel", "--clipboard", "--output"]):
        if have(cmd[0]) and (cmd[0] != "wl-paste" or os.environ.get("WAYLAND_DISPLAY")):
            out = _run(cmd, timeout=1)
            if out:
                return out
    return ""


class Clipboard:
    """Text you copy, kept in memory for the clipboard history (newest first)."""

    def __init__(self):
        self.items, self._last = [], paste_text()

    def poll(self):
        t = paste_text()
        if t and t != self._last and len(t) < 20000:
            self._last = t
            self.items = [t] + [x for x in self.items if x != t][:29]


# ---------------------------------------------------------------- sound output
def default_output():
    out = _run(["pactl", "get-default-sink"]) if have("pactl") else ""
    return out.strip()


# ---------------------------------------------------------------- notifications (session D-Bus)
class NotifWatcher:
    """Notifications as they are sent, read from the session bus with
    dbus-monitor (the same messages your desktop's notification bubbles get)."""

    def __init__(self):
        self.last = 0
        self._q = []
        self._lock = threading.Lock()
        if have("dbus-monitor"):
            threading.Thread(target=self._run, daemon=True).start()

    def _newest(self):
        return 0

    def _run(self):
        cmd = ["dbus-monitor", "--session", "interface='org.freedesktop.Notifications',member='Notify'"]
        while True:
            try:
                p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=_NULL, text=True)
                strings, collecting = [], False
                for line in p.stdout:
                    line = line.strip()
                    if line.startswith("method call") and "member=Notify" in line:
                        if collecting:
                            self._add(strings)
                        strings, collecting = [], True
                    elif collecting and line.startswith("string "):
                        strings.append(json.loads(line[7:]) if line[7:].startswith('"') else line[7:])
                    elif collecting and line.startswith("array [") and len(strings) >= 4:
                        self._add(strings)
                        collecting = False
                p.wait()
            except Exception:
                pass
            time.sleep(5)

    def _add(self, s):
        # Notify(app_name, replaces_id, app_icon, summary, body, actions, hints, timeout)
        if len(s) < 4:
            return
        app, icon, title, body = s[0], s[1], s[2], s[3] if len(s) > 3 else ""
        if app.lower() in ("hop", "hop island", "notify-send") and not title:
            return
        with self._lock:
            self._q.append({"app": app or "Notification", "title": title, "body": body, "image": None, "appIcon": ""})

    def poll(self):
        with self._lock:
            out, self._q = self._q, []
        return out


# ---------------------------------------------------------------- music: MPRIS via playerctl
FMT = "{{playerName}}\t{{status}}\t{{position}}\t{{mpris:length}}\t{{title}}\t{{artist}}\t{{album}}\t{{mpris:artUrl}}\t{{volume}}\t{{shuffle}}\t{{loop}}"


def players():
    return [p for p in _run(["playerctl", "-l"]).split() if p] if have("playerctl") else []


def pick_player():
    """Whatever is playing wins (Spotify first if several are); else Spotify;
    else the first player."""
    ps = players()
    if not ps:
        return None
    status = {p: _run(["playerctl", "-p", p, "status"]).strip() for p in ps}
    live = [p for p in ps if status[p] == "Playing"]
    for pool in (live, ps):
        for p in pool:
            if p.lower().startswith("spotify"):
                return p
        if pool is live and live:
            return live[0]
    return ps[0]


def now_playing(player):
    out = _run(["playerctl", "-p", player, "metadata", "--format", FMT])
    f = out.rstrip("\n").split("\t")
    if len(f) < 11:
        return None
    name, status, pos, length, title, artist, album, art, vol, shuffle, loop = f[:11]
    try:
        pos_ms, dur_ms = int(float(pos or 0) / 1000), int(float(length or 0) / 1000)
    except ValueError:
        pos_ms, dur_ms = 0, 0
    return {"app": name, "isPlaying": status == "Playing", "progressMs": pos_ms, "durationMs": dur_ms,
            "track": title, "artist": artist, "album": album, "art": art,
            "volume": float(vol) if re.match(r"^[0-9.]+$", vol or "") else None,
            "shuffle": {"true": True, "false": False}.get(shuffle.lower()),
            "repeat": {"None": "off", "Track": "one", "Playlist": "all"}.get(loop)}


def control(player, action):
    cmd = {"play": ["play"], "pause": ["pause"], "next": ["next"], "previous": ["previous"]}.get(action)
    if action == "shuffle":
        cmd = ["shuffle", "toggle"]
    elif action == "repeat":
        cur = _run(["playerctl", "-p", player, "loop"]).strip()
        cmd = ["loop", {"None": "Playlist", "Playlist": "Track", "Track": "None"}.get(cur, "Playlist")]
    if cmd:
        subprocess.run(["playerctl", "-p", player, *cmd], stdout=_NULL, stderr=_NULL, timeout=3)


def seek(player, ms):
    subprocess.run(["playerctl", "-p", player, "position", f"{max(0, ms) / 1000:.3f}"], stdout=_NULL, stderr=_NULL, timeout=3)


def set_volume(player, level):
    subprocess.run(["playerctl", "-p", player, "volume", f"{max(0.0, min(1.0, level)):.3f}"], stdout=_NULL, stderr=_NULL, timeout=3)


# ---------------------------------------------------------------- start on login
AUTOSTART = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(HOME, ".config"), "autostart")


def set_autostart(name, command, on):
    path = os.path.join(AUTOSTART, f"{name.lower().replace(' ', '-')}.desktop")
    if not on:
        if os.path.exists(path):
            os.remove(path)
        return
    os.makedirs(AUTOSTART, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f"[Desktop Entry]\nType=Application\nName={name}\nExec={command}\nIcon=hop\n"
                 "X-GNOME-Autostart-enabled=true\nNoDisplay=false\nTerminal=false\n")
