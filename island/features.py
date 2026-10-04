r"""The host side of the island's newer features (0.1.3). Everything here
feeds window.__hopEvent(kind, data) in the page (ui\features.js) or answers
its calls (FeatureApi, mixed into IslandApi).

    agents      Claude Code hooks -> a tiny local server (127.0.0.1:47613)
    watch       notifications, mic / camera, the app in front (hide-in-apps,
                game mode, profiles), Caps Lock, Wi-Fi, focus, downloads,
                screenshots, download speed, battery, clips today
    calendar    an iCal link, every 10 minutes
    sports      ESPN's public scoreboards for your teams
    rain        Open-Meteo's next hour, for your city
    scrobble    Last.fm, when it is connected
    and the calls behind the settings app: profiles, theme codes, backup,
    diagnostics, extensions, in-app updates.

Nothing here runs unless the island's settings switch it on, and nothing
leaves the PC except the requests named above."""
import base64
import ctypes
import ctypes.wintypes as wt
import datetime as dt
import hashlib
import http.server
import json
import math
import os
import re
import shutil
import socketserver
import struct
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import wave
import zipfile

import extras
import options
import watch

NO_WINDOW = 0x08000000
u32 = ctypes.windll.user32
host = None                     # the host module (host.py sets this; the frozen app can't "import host")
AGENT_PORT = 47613
HOOK_CMD = f'curl -s -m 120 -X POST -H "Content-Type: application/json" --data-binary @- http://127.0.0.1:{AGENT_PORT}/hook'
HOOK_EVENTS = ["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PermissionRequest", "Notification", "Stop",
               "SessionEnd"]
CLAUDE_SETTINGS = os.path.join(os.path.expanduser("~"), ".claude", "settings.json")
EXT_DIR = os.path.join(os.environ.get("APPDATA", ""), "Hop", "extensions")
LOOK_KEYS = ["style", "pillW", "pillH", "notchW", "notchH", "openW", "openH", "radiusClosed", "radiusOpen", "topGap", "bg",
             "bgOpacity", "bgStyle", "border", "borderColor", "borderOpacity", "glow", "accentMode", "accentColor", "font",
             "clock24", "clockSeconds", "anim", "bounce", "speed", "slotLeft", "slotCenter", "slotRight", "customCss"]


def ago_text(seconds):
    s = max(0, int(seconds))
    if s < 3600:
        return f"{max(1, s // 60)}m"
    if s < 86400:
        return f"{s // 3600}h {s % 3600 // 60}m"
    return f"{s // 86400}d {s % 86400 // 3600}h"


# ------------------------------------------------------------------ sounds (made once, no files shipped)
SOUND_SPECS = {"tick": [(1500, 0.035)], "pop": [(620, 0.05), (930, 0.06)], "chime": [(880, 0.35), (1320, 0.55)],
               "bell": [(523, 0.9), (784, 0.9)], "soft": [(440, 0.6), (554, 0.7)]}


def make_sound(path, notes, rate=22050):
    """A short sine tone (or two, one after the other) with a soft fade."""
    frames = bytearray()
    for freq, length in notes:
        n = int(rate * length)
        for i in range(n):
            env = min(1.0, i / (rate * 0.005)) * math.exp(-4.0 * i / n)
            v = int(0.32 * 32767 * env * (math.sin(2 * math.pi * freq * i / rate) + 0.25 * math.sin(4 * math.pi * freq * i / rate)) / 1.25)
            frames += struct.pack("<h", v)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))


# ------------------------------------------------------------------ AI agents (Claude Code hooks)
def tool_summary(tool, inp):
    """A short line for what a tool is about to do."""
    inp = inp or {}
    if tool == "Bash":
        return (inp.get("command") or "")[:140]
    for k in ("file_path", "path", "notebook_path", "url", "pattern", "query"):
        if inp.get(k):
            v = str(inp[k])
            return f"{tool} {os.path.basename(v) if k.endswith('path') else v}"[:140]
    return tool


def edit_counts(tool, inp):
    """(file, lines added, lines removed) for Edit / Write / MultiEdit."""
    inp = inp or {}
    path = inp.get("file_path") or ""
    lines = lambda t: len((t or "").splitlines()) if t else 0
    if tool == "Write":
        return path, lines(inp.get("content")), 0
    if tool == "Edit":
        return path, lines(inp.get("new_string")), lines(inp.get("old_string"))
    if tool == "MultiEdit":
        es = inp.get("edits") or []
        return path, sum(lines(e.get("new_string")) for e in es), sum(lines(e.get("old_string")) for e in es)
    return None


def last_reply(transcript_path, limit=140):
    """The agent's last words, from the end of its transcript (JSON lines)."""
    try:
        with open(transcript_path, "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - 200_000))
            tail = fh.read().decode("utf-8", "replace").splitlines()
    except (OSError, TypeError):
        return ""
    for line in reversed(tail):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        msg = d.get("message") or {}
        if d.get("type") == "assistant" and isinstance(msg.get("content"), list):
            text = " ".join(c.get("text", "") for c in msg["content"] if isinstance(c, dict) and c.get("type") == "text").strip()
            if text:
                text = re.sub(r"\s+", " ", re.sub(r"[*_`#>]", "", text))
                return text[:limit] + ("…" if len(text) > limit else "")
    return ""


def hooks_connected(path=CLAUDE_SETTINGS):
    try:
        with open(path, encoding="utf-8") as fh:
            return f"{AGENT_PORT}/hook" in fh.read()
    except OSError:
        return False


def set_hooks(on, path=CLAUDE_SETTINGS):
    """Add (or remove) Hop's hook to Claude Code's user settings. A backup of
    the file is kept once (settings.json.hop-backup); other hooks are left."""
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except FileNotFoundError:
        cfg = {}
    except ValueError:
        return False                                            # not valid JSON: never overwrite it
    if os.path.exists(path) and not os.path.exists(path + ".hop-backup"):
        shutil.copyfile(path, path + ".hop-backup")
    hooks = cfg.setdefault("hooks", {})
    for ev in HOOK_EVENTS:
        groups = [g for g in hooks.get(ev, []) if not any(f"{AGENT_PORT}/hook" in (h.get("command") or "") for h in g.get("hooks", []))]
        if on:
            groups.append({"matcher": "*", "hooks": [{"type": "command", "command": HOOK_CMD, "timeout": 120}]}
                          if ev in ("PreToolUse", "PostToolUse", "PermissionRequest") else
                          {"hooks": [{"type": "command", "command": HOOK_CMD, "timeout": 120}]})
        if groups:
            hooks[ev] = groups
        else:
            hooks.pop(ev, None)
    if not hooks:
        cfg.pop("hooks", None)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
    os.replace(tmp, path)
    return True


class AgentHub:
    """Claude Code sessions, from its hooks. Permission requests and
    questions wait here (up to `wait` seconds) for an answer from the island;
    no answer means Claude Code asks in the terminal as usual."""

    def __init__(self, f, wait=50):
        self.f = f
        self.wait = wait
        self.sessions = {}
        self.pending = {}                                          # id -> [Event, answer]
        self.lock = threading.Lock()
        self.usage = None
        self.usage_soon = False                                    # a reply just finished: read the usage again

    def public(self):
        order = {"ask": 0, "work": 1, "done": 2, "idle": 3}
        ss = sorted(self.sessions.values(), key=lambda s: (order.get(s["status"], 9), -s["at"]))
        return {"sessions": [{k: s[k] for k in ("id", "tool", "name", "status", "detail")} for s in ss],
                "usage": self.usage if self.f.L().get("usagePill") else None}

    def _push(self):
        self.f.js("agents", self.public())

    def answer(self, pid, ans):
        with self.lock:
            p = self.pending.get(pid)
        if p:
            p[1] = ans
            p[0].set()
        return bool(p)

    def _ask(self, card):
        pid = hashlib.sha1(f"{time.time()}{card}".encode()).hexdigest()[:12]
        ev = threading.Event()
        with self.lock:
            self.pending[pid] = [ev, None]
        self.f.js("agentAsk", dict(card, id=pid))
        if self.f.L().get("agentSound"):
            self.f.sound("pop")
        ev.wait(self.wait)
        with self.lock:
            ans = self.pending.pop(pid, [None, None])[1]
        return ans

    def handle(self, d):
        """One hook call -> the JSON Claude Code reads back ({} = carry on)."""
        L = self.f.L()
        if not L.get("agentsOn", True):
            return {}
        ev, sid = d.get("hook_event_name", ""), d.get("session_id", "") or "?"
        cwd = d.get("cwd") or ""
        s = self.sessions.setdefault(sid, {"id": sid, "tool": "claude", "name": os.path.basename(cwd.rstrip("\\/")) or "Claude",
                                           "status": "idle", "detail": "", "cwd": cwd, "at": time.time()})
        s["at"] = time.time()
        tool, inp = d.get("tool_name", ""), d.get("tool_input") or {}
        out = {}
        if ev == "SessionStart":
            s.update(status="idle", detail="New session")
        elif ev == "UserPromptSubmit":
            s.update(status="work", detail="Thinking…")
        elif ev == "PreToolUse":
            s.update(status="work", detail=tool_summary(tool, inp))
            if tool == "AskUserQuestion" and L.get("agentApprove", True):
                qs = inp.get("questions") or []
                q = qs[0] if qs else {}
                opts = [o.get("label", str(o)) if isinstance(o, dict) else str(o) for o in (q.get("options") or [])][:6]
                if opts:
                    s.update(status="ask", detail="Has a question")
                    self._push()
                    ans = self._ask({"kind": "question", "tool": "claude", "name": s["name"], "question": q.get("question", ""),
                                     "options": opts, "multi": bool(q.get("multiSelect"))})
                    if isinstance(ans, dict) and ans.get("choice"):
                        s.update(status="work", detail="Answered from the island")
                        # the island answered: the tool is skipped and Claude reads the answer as its reason
                        out = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                      "permissionDecisionReason": "The user answered this question in Hop Island: "
                                                      + ", ".join(ans["choice"]) + ". Continue with that answer; don't ask again."}}
        elif ev == "PermissionRequest" and L.get("agentApprove", True):
            s.update(status="ask", detail="Wants: " + tool_summary(tool, inp))
            self._push()
            if self.f.terminal_in_front(s) and L.get("agentSuppress", True):
                return {}                                            # you're looking at it: answer there
            if tool == "ExitPlanMode":
                card = {"kind": "plan", "tool": "claude", "name": s["name"], "plan": str(inp.get("plan", ""))[:4000]}
            else:
                card = {"kind": "permission", "tool": "claude", "name": s["name"], "summary": tool_summary(tool, inp),
                        "verb": "run" if tool == "Bash" else "edit" if tool in ("Edit", "Write", "MultiEdit") else "use " + tool}
            ans = self._ask(card)
            s.update(status="work", detail=tool_summary(tool, inp))
            if ans == "allow":
                out = {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}}
            elif ans == "deny" or isinstance(ans, dict) and ans.get("deny"):
                msg = ans["deny"] if isinstance(ans, dict) else "Denied in Hop Island."
                out = {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "deny", "message": msg}}}
        elif ev == "PostToolUse":
            got = edit_counts(tool, inp)
            if got and got[0]:
                self.f.js("agentEdit", {"tool": "claude", "file": got[0], "plus": got[1], "minus": got[2]})
                s["detail"] = f"Edited {os.path.basename(got[0])}"
        elif ev == "Notification":
            msg = d.get("message", "")
            s.update(status="ask" if "permission" in msg.lower() else "idle", detail=msg[:100] or "Waiting for you")
        elif ev == "Stop":
            self.usage_soon = True
            summary = last_reply(d.get("transcript_path"))
            s.update(status="done", detail=summary or "Finished")
            if not (L.get("agentSuppress", True) and self.f.terminal_in_front(s)):
                self.f.js("agentAsk", {"kind": "done", "session": sid, "tool": "claude", "name": s["name"], "summary": summary})
                if L.get("agentSound"):
                    self.f.sound("chime")
        elif ev == "SessionEnd":
            self.sessions.pop(sid, None)
        self._push()
        return out

    # the hook endpoint
    def serve(self):
        hub = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                if self.path != "/hook" or self.client_address[0] != "127.0.0.1":
                    self.send_response(404)
                    self.end_headers()
                    return
                try:
                    n = min(int(self.headers.get("Content-Length") or 0), 4_000_000)
                    d = json.loads(self.rfile.read(n).decode("utf-8", "replace") or "{}")
                    out = hub.handle(d)
                except Exception as e:
                    extras.log("agent hook", repr(e))
                    out = {}
                body = json.dumps(out).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
            daemon_threads = True

        try:
            srv = Server(("127.0.0.1", int(os.environ.get("HOP_AGENT_PORT", AGENT_PORT))), Handler)
        except OSError as e:
            extras.log("agent port busy", repr(e))
            return
        srv.serve_forever()

    def sync(self, root=None):
        """Match Claude Code's own list of running sessions (~/.claude/sessions,
        one file per open window): a window closed without SessionEnd (killed,
        crashed, the PC slept) is dropped, one opened before the island started
        is added, and each is named after the folder it was started in."""
        live = live_claude_sessions(root)
        if live is None:
            return False                                    # an older Claude Code: hooks only
        changed = False
        now = time.time()
        with self.lock:
            for sid, s in list(self.sessions.items()):
                if s["tool"] == "claude" and sid not in live and now - s["at"] > 5:
                    del self.sessions[sid]
                    changed = True
            for sid, x in live.items():
                name = os.path.basename(x["cwd"].rstrip("\\/")) or "Claude"
                s = self.sessions.get(sid)
                if s is None:
                    busy = x["status"] == "busy"
                    self.sessions[sid] = {"id": sid, "tool": "claude", "name": name, "status": "work" if busy else "idle",
                                          "detail": "Working" if busy else "Waiting for you", "cwd": x["cwd"], "at": now - 6}
                    changed = True
                elif s["name"] != name:
                    s["name"] = name
                    changed = True
        if changed:
            self._push()
        return changed

    def sync_loop(self):
        while True:
            try:
                self.sync()
            except Exception as e:
                extras.log("agent sync", repr(e))
            time.sleep(4)

    def usage_loop(self):
        """Claude plan usage (5-hour and weekly), only when switched on: read
        with Claude Code's own sign-in from ~/.claude/.credentials.json."""
        # every minute, and soon after a reply finishes (that's when it moves),
        # never more than once in 20 s
        last = 0.0
        while True:
            on = self.f.L().get("usagePill")
            now = time.time()
            if not on:
                last = 0.0                                  # switched on again: fetch at once
            elif now - last >= 60 or (self.usage_soon and now - last >= 20):
                last, self.usage_soon = now, False
                try:
                    self.usage = claude_usage()
                    self._push()
                except Exception as e:
                    extras.log("usage", repr(e))
            time.sleep(3)


def _proc_start(pid):
    """The process's creation time as a FILETIME number, or None if it has exited."""
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x1000, False, int(pid))                 # QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        code = wt.DWORD()
        if not k.GetExitCodeProcess(h, ctypes.byref(code)) or code.value != 259:   # STILL_ACTIVE
            return None
        c, e, kt, ut = (wt.FILETIME() for _ in range(4))
        if not k.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(kt), ctypes.byref(ut)):
            return 0
        return (c.dwHighDateTime << 32) | c.dwLowDateTime
    finally:
        k.CloseHandle(h)


def live_claude_sessions(root=None):
    """{sessionId: {cwd, status}} for the Claude Code windows open right now,
    from the files it keeps in ~/.claude/sessions (named <pid>.json). A file
    whose process is gone, or whose pid now belongs to another program, is
    skipped. None when there is no such folder."""
    root = root or os.path.join(os.path.expanduser("~"), ".claude", "sessions")
    if not os.path.isdir(root):
        return None
    out = {}
    for n in os.listdir(root):
        if not n.endswith(".json"):
            continue
        try:
            with open(os.path.join(root, n), encoding="utf-8") as fh:
                d = json.load(fh)
            pid, sid = int(d.get("pid") or n[:-5]), str(d.get("sessionId") or "")
        except (OSError, ValueError, TypeError, AttributeError):
            continue
        if not sid:
            continue
        started = _proc_start(pid)
        if started is None:
            continue
        want = str(d.get("procStart") or "")
        if started and want.isdigit() and abs(started - int(want)) > 10_000_000:   # > 1 s apart: the pid was reused
            continue
        out[sid] = {"cwd": str(d.get("cwd") or ""), "status": str(d.get("status") or "")}
    return out


def claude_usage():
    p = os.path.join(os.path.expanduser("~"), ".claude", ".credentials.json")
    with open(p, encoding="utf-8") as fh:
        tok = json.load(fh)["claudeAiOauth"]["accessToken"]
    req = urllib.request.Request("https://api.anthropic.com/api/oauth/usage",
                                 headers={"Authorization": "Bearer " + tok, "anthropic-beta": "oauth-2025-04-20",
                                          "User-Agent": "hop-island"})
    with urllib.request.urlopen(req, timeout=10) as r:
        d = json.loads(r.read().decode())

    def part(k):
        x = d.get(k) or {}
        reset = ""
        if x.get("resets_at"):
            try:
                t = dt.datetime.fromisoformat(x["resets_at"].replace("Z", "+00:00"))
                reset = ago_text((t - dt.datetime.now(dt.timezone.utc)).total_seconds())
            except ValueError:
                pass
        return float(x.get("utilization") or 0), reset
    five, five_r = part("five_hour")
    week, week_r = part("seven_day")
    return {"five": five, "fiveReset": five_r, "week": week, "weekReset": week_r}


# ------------------------------------------------------------------ Windows bits
def game_running():
    """A full-screen game or presentation, as Windows itself judges it."""
    state = ctypes.c_int(0)
    try:
        ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state))
    except Exception:
        return False
    return state.value in (2, 3, 4)          # BUSY (full-screen app), RUNNING_D3D_FULL_SCREEN, PRESENTATION_MODE


class _WNF(ctypes.Structure):
    _fields_ = [("data", ctypes.c_ulonglong)]


def focus_on():
    """Windows focus / Do not disturb (Focus Assist), via its WNF state."""
    try:
        ntdll = ctypes.windll.ntdll
        sn = ctypes.c_ulonglong(0xD83063EA3BF1C75)              # WNF_SHEL_QUIETHOURS_ACTIVE_PROFILE_CHANGED
        stamp, buf, size = ctypes.c_ulong(0), ctypes.c_ulong(0), ctypes.c_ulong(4)
        if ntdll.NtQueryWnfStateData(ctypes.byref(sn), None, None, ctypes.byref(stamp), ctypes.byref(buf), ctypes.byref(size)) != 0:
            return False
        return buf.value != 0
    except Exception:
        return False


def net_fingerprint():
    """Which adapters are up and their IPv4 addresses. Cheap, and unlike the
    Wi-Fi name it isn't location data: Windows 11 lights the location icon
    ("Network Command Shell") every time netsh reads the SSID, so wifi_ssid()
    only runs when this changes (a network joined, dropped or switched)."""
    import psutil
    import socket
    stats, addrs = psutil.net_if_stats(), psutil.net_if_addrs()
    return tuple(sorted((name, st.isup, tuple(sorted(a.address for a in addrs.get(name, []) if a.family == socket.AF_INET)))
                        for name, st in stats.items()))


def wifi_ssid():
    """The connected Wi-Fi network's name, '' when not connected, None without Wi-Fi."""
    try:
        out = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True, text=True, timeout=5,
                             creationflags=NO_WINDOW).stdout
    except Exception:
        return None
    if "There is no wireless interface" in out or not out.strip():
        return None
    state = re.search(r"^\s*State\s*:\s*(\S+)", out, re.M)
    ssid = re.search(r"^\s*SSID\s*:\s*(.+)$", out, re.M)
    return ssid.group(1).strip() if state and state.group(1).lower() == "connected" and ssid else ""


def known_folder(guid):
    from ctypes import oledll, c_wchar_p, byref
    class GUID(ctypes.Structure):
        _fields_ = [("a", ctypes.c_ulong), ("b", ctypes.c_ushort), ("c", ctypes.c_ushort), ("d", ctypes.c_ubyte * 8)]
    p = c_wchar_p()
    g = GUID()
    ctypes.windll.ole32.CLSIDFromString(guid, byref(g))
    try:
        oledll.shell32.SHGetKnownFolderPath(byref(g), 0, None, byref(p))
        return p.value
    except OSError:
        return None


DOWNLOADS = lambda: known_folder("{374DE290-123F-4565-9164-39C4925E467B}") or os.path.join(os.path.expanduser("~"), "Downloads")
PICTURES = lambda: known_folder("{33E28130-4E1E-4676-835A-98395C3BC3BB}") or os.path.join(os.path.expanduser("~"), "Pictures")
DESKTOP = lambda: known_folder("{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}") or os.path.join(os.path.expanduser("~"), "Desktop")
PARTIAL = (".crdownload", ".part", ".partial", ".tmp", ".download", ".opdownload", ".!ut")


def size_text(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") or n >= 100 else f"{n:.1f} {unit}"
        n /= 1024


class NewFiles:
    """Files that newly appear (and stop growing) in a folder."""

    def __init__(self, folder, exts=None):
        self.folder, self.exts = folder, exts
        self.seen = set(self._list())
        self.growing = {}

    def _list(self):
        try:
            return [e.name for e in os.scandir(self.folder) if e.is_file()]
        except OSError:
            return []

    def poll(self):
        out = []
        for name in self._list():
            if name in self.seen or name.lower().endswith(PARTIAL) or name.startswith("~$"):
                continue
            if self.exts and not name.lower().endswith(self.exts):
                self.seen.add(name)
                continue
            p = os.path.join(self.folder, name)
            try:
                size = os.path.getsize(p)
            except OSError:
                continue
            if self.growing.get(name) == size and size > 0:
                self.seen.add(name)
                self.growing.pop(name, None)
                out.append(p)
            else:
                self.growing[name] = size
        return out


def image_thumb(path, w=192):
    try:
        from PIL import Image
        import io
        with Image.open(path) as im:
            size = im.size
            im.thumbnail((w, w))
            buf = io.BytesIO()
            im.convert("RGB").save(buf, "JPEG", quality=72)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode(), size
    except Exception:
        return "", None


def copy_image(path):
    """A picture onto the clipboard as a bitmap (paste into Discord, Paint...)."""
    from PIL import Image
    import io
    with Image.open(path) as im:
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "BMP")
    data = buf.getvalue()[14:]                                   # CF_DIB: the BMP without its file header
    k32 = ctypes.windll.kernel32
    k32.GlobalAlloc.restype = wt.HGLOBAL
    k32.GlobalLock.restype = ctypes.c_void_p
    k32.GlobalLock.argtypes = [wt.HGLOBAL]
    u32.SetClipboardData.argtypes = [wt.UINT, wt.HANDLE]
    h = k32.GlobalAlloc(0x0002, len(data))
    p = k32.GlobalLock(h)
    ctypes.memmove(p, data, len(data))
    k32.GlobalUnlock(wt.HGLOBAL(h))
    for _ in range(10):
        if u32.OpenClipboard(None):
            break
        time.sleep(0.05)
    try:
        u32.EmptyClipboard()
        u32.SetClipboardData(8, h)                               # CF_DIB
    finally:
        u32.CloseClipboard()
    return True


def monitors():
    """[{index, name, primary, work: (l, t, r, b)}] for every screen."""
    class MI(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD),
                    ("szDevice", wt.WCHAR * 32)]
    out = []
    PROC = ctypes.WINFUNCTYPE(ctypes.c_int, wt.HANDLE, wt.HDC, ctypes.POINTER(wt.RECT), wt.LPARAM)

    def cb(hmon, hdc, rc, lp):
        mi = MI(cbSize=ctypes.sizeof(MI))
        u32.GetMonitorInfoW(hmon, ctypes.byref(mi))
        r, w = mi.rcMonitor, mi.rcWork
        out.append({"index": len(out), "name": f"Screen {len(out) + 1} ({r.right - r.left}×{r.bottom - r.top})",
                    "primary": bool(mi.dwFlags & 1), "work": (w.left, w.top, w.right, w.bottom), "handle": hmon})
        return 1
    u32.EnumDisplayMonitors(None, None, PROC(cb), 0)
    return out


def label_monitors(rects, current):
    """Names for the screens, from where they sit (Windows' own arrangement):
    the island's screen is "This monitor"; the others "Left monitor",
    "Right monitor", "Top monitor", "Bottom monitor" (numbered when there are
    two on one side). Returned left to right, then top to bottom."""
    if not rects:
        return []
    cx = lambda r: (r[0] + r[2]) / 2
    cy = lambda r: (r[1] + r[3]) / 2
    me = rects[current]
    out = []
    for i, r in enumerate(rects):
        if i == current:
            side = "This"
        else:
            dx, dy = cx(r) - cx(me), cy(r) - cy(me)
            side = ("Right" if dx > 0 else "Left") if abs(dx) >= abs(dy) else ("Bottom" if dy > 0 else "Top")
        out.append({"index": i, "side": side, "x": cx(r), "y": cy(r)})
    out.sort(key=lambda o: (o["x"], o["y"]))
    for side in ("Left", "Right", "Top", "Bottom"):
        same = [o for o in out if o["side"] == side]
        if side in ("Left", "Top"):
            same.reverse()                                   # the nearest one is "Left monitor", the next "Left monitor 2"
        for n, o in enumerate(same):
            o["label"] = f"{side} monitor" + (f" {n + 1}" if len(same) > 1 and n else "")
    for o in out:
        o.setdefault("label", "This monitor")
    return [{"index": o["index"], "label": o["label"]} for o in out]


def top_windows():
    """(hwnd, title, exe) of every visible top-level window with a title."""
    out = []
    PROC = ctypes.WINFUNCTYPE(ctypes.c_int, wt.HWND, wt.LPARAM)

    def cb(h, lp):
        if u32.IsWindowVisible(h):
            n = u32.GetWindowTextLengthW(h)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                u32.GetWindowTextW(h, buf, n + 1)
                out.append((h, buf.value))
        return 1
    u32.EnumWindows(PROC(cb), 0)
    return out


def bring_to_front(hwnd):
    u32.ShowWindow(hwnd, 9)                                       # SW_RESTORE
    u32.keybd_event(0x12, 0, 0, 0)                                 # a tap of Alt lets a background app hand over focus
    u32.keybd_event(0x12, 0, 2, 0)
    u32.SetForegroundWindow(hwnd)


# ------------------------------------------------------------------ the features
class Features:
    def __init__(self, island):
        self.i = island
        self.need = {}
        self.agents = AgentHub(self)
        self._sounds = {}
        self._before_rule = None
        self._rule_profile = None
        self.gaming = False
        self.hidden_for_app = False

    # ---- helpers
    def L(self):
        return self.i.layout

    @property
    def cfg(self):
        return self.i.cfg

    def save(self):
        host.write_config(self.cfg)

    def js(self, kind, data):
        self.i._js(f"window.__hopEvent && window.__hopEvent({json.dumps(kind)}, {json.dumps(data)})")

    def sound(self, name):
        import winsound
        name = name if name in SOUND_SPECS else "chime"
        path = self._sounds.get(name)
        if not path:
            d = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Hop Island", "sounds")
            os.makedirs(d, exist_ok=True)
            path = os.path.join(d, name + ".wav")
            if not os.path.exists(path):
                make_sound(path, SOUND_SPECS[name])
            self._sounds[name] = path
        try:
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        except RuntimeError:
            pass
        return True

    def terminal_in_front(self, s):
        """Is the agent's own window in front (so a pop-up would be noise)?"""
        exe = watch.foreground_exe()
        if exe not in ("windowsterminal.exe", "code.exe", "cursor.exe", "cmd.exe", "pwsh.exe", "powershell.exe", "wezterm-gui.exe",
                       "alacritty.exe", "conhost.exe"):
            return False
        h = u32.GetForegroundWindow()
        n = u32.GetWindowTextLengthW(h)
        buf = ctypes.create_unicode_buffer(n + 1)
        u32.GetWindowTextW(h, buf, n + 1)
        title = buf.value.lower()
        if s["name"].lower() in title:
            return True
        # Claude Code titles its terminal after the task, not the folder: a
        # Claude terminal in front only counts when this is the only session
        busy = [x for x in self.agents.sessions.values() if x["status"] != "done"]
        return ("claude" in title or "✳" in buf.value) and len(busy) <= 1

    def start(self):
        os.makedirs(EXT_DIR, exist_ok=True)
        self._seed_extensions()
        for target in (self.agents.serve, self.agents.usage_loop, self.agents.sync_loop, self.watch_loop, self.notif_loop, self.calendar_loop,
                       self.sports_loop, self.rain_loop, self.scrobble_loop, self.monitor_loop):
            threading.Thread(target=self._safe, args=(target,), daemon=True).start()

    def _safe(self, fn):
        while True:
            try:
                fn()
                return
            except Exception as e:
                extras.log("features", fn.__name__, repr(e))
                time.sleep(10)

    def hello(self):
        """Everything the page should know at start."""
        return {"agents": self.agents.public(), "calSet": bool(self.cfg.get("calendarUrl")), "calendar": getattr(self, "events", []),
                "extensions": self.list_extensions(), "privacy": getattr(self, "_privacy", {"mic": [], "cam": []}),
                "clipStats": self.clip_stats(), "shelf": self.get_shelf()}

    def pace(self):
        return {"normal": 1.0, "smart": 1.5, "low": 3.0}.get(self.L().get("power"), 1.0)

    # ---- the watchers
    def watch_loop(self):
        tick = 0
        ssid = wifi_ssid() if self.L().get("wifiPop") else None
        net = net_fingerprint() if self.L().get("wifiPop") else None      # None: read the SSID at the next check
        focus = focus_on()
        dl = NewFiles(DOWNLOADS())
        shots = NewFiles(os.path.join(PICTURES(), "Screenshots"), (".png", ".jpg"))
        last_net = None
        import psutil
        while True:
            time.sleep(0.5)
            tick += 1
            L = self.L()
            slow = self.pace()
            if tick % max(1, int(2 * slow)) == 0:
                self._front(L)
                p = watch.privacy_in_use()
                if p != getattr(self, "_privacy", None):
                    self._privacy = p
                    self.js("privacy", p)
                g = game_running()
                if g != self.gaming:
                    self.gaming = g
                    self.js("game", g)
            if tick % max(2, int(6 * slow)) == 0:
                f = focus_on()
                if f != focus:
                    focus = f
                    self.js("focus", f)
                for p in dl.poll():
                    if self.L()["popups"]["download"]["on"]:
                        self.js("download", {"name": os.path.basename(p), "path": p, "size": size_text(os.path.getsize(p))})
                for p in shots.poll():
                    thumb, size = image_thumb(p)
                    self.js("snip", {"path": p, "name": os.path.basename(p), "thumb": thumb, "size": f"{size[0]} × {size[1]}" if size else ""})
            if tick % max(4, int(10 * slow)) == 0:
                if not L.get("wifiPop", True):
                    net = None
                elif (n := net_fingerprint()) != net:
                    net = n
                    s = wifi_ssid()
                    if s is not None and ssid is not None and s != ssid:
                        self.js("wifi", {"ssid": s})
                    ssid = s
            if self.need.get("net") and tick % 4 == 0:
                n = psutil.net_io_counters()
                now = time.time()
                if last_net:
                    dt_ = max(0.1, now - last_net[2])
                    self.js("net", {"down": (n.bytes_recv - last_net[0]) / dt_, "up": (n.bytes_sent - last_net[1]) / dt_})
                last_net = (n.bytes_recv, n.bytes_sent, now)
            if self.need.get("battery") and tick % 60 == 1:
                self.js("battery", self.battery_light())
            if self.need.get("clipStats") and tick % 20 == 3:
                self.js("clipStats", self.clip_stats())

    def _front(self, L):
        """The app in front: hide the island in chosen apps, and switch
        profiles by app."""
        exe = watch.foreground_exe()
        hide = exe in (L.get("hideApps") or [])
        if hide != self.hidden_for_app and self.i.window:
            self.hidden_for_app = hide
            try:
                self.i.window.hide() if hide else self.i.window.show()
            except Exception:
                pass
        rules = self.cfg.get("profileRules") or []
        want = next((r["profile"] for r in rules if r.get("exe") and r["exe"] == exe and r.get("profile") in (self.cfg.get("profiles") or {})), None)
        if want and want != self._rule_profile:
            if self._rule_profile is None:
                self._before_rule = dict(self.L())
            self._rule_profile = want
            self.i.set_layout(self.cfg["profiles"][want])
        elif not want and self._rule_profile and exe and exe not in ("hopisland.exe", "python.exe", "pythonw.exe"):
            self._rule_profile = None
            if self._before_rule:
                self.i.set_layout(self._before_rule)
                self._before_rule = None

    def notif_loop(self):
        w = watch.NotifWatcher()
        while True:
            time.sleep(1.5 * self.pace())
            if not self.L()["popups"]["notif"]["on"]:
                w.last = w._newest()
                continue
            for n in w.poll():
                icon = watch.image_data_url(n["image"]) if n.get("image") else ""
                self.js("notif", {"app": n["app"], "title": n["title"], "text": n["body"], "icon": icon})

    def calendar_loop(self):
        last_url, last_fetch = None, 0
        while True:
            url = self.cfg.get("calendarUrl") or ""
            if url and (url != last_url or time.time() - last_fetch > 600):
                last_url, last_fetch = url, time.time()
                try:
                    evs = watch.parse_ics(watch.fetch_ics(url), days=7, limit=12)
                    self.events = [dict(e, start=int(dt.datetime.fromisoformat(e["start"]).timestamp() * 1000),
                                        end=int(dt.datetime.fromisoformat(e["end"]).timestamp() * 1000)) for e in evs]
                    self.js("calendar", self.events)
                except Exception as e:
                    extras.log("calendar", repr(e))
            time.sleep(15)

    def sports_loop(self):
        while True:
            teams = self.L().get("teams") or []
            live = False
            if teams:
                try:
                    ms = scores(teams)
                    live = any(m["live"] for m in ms)
                    self.js("sports", ms)
                except Exception as e:
                    extras.log("sports", repr(e))
            time.sleep(60 if live else 600)

    def rain_loop(self):
        told = 0
        while True:
            loc = self.cfg.get("location") or {}
            if self.L().get("rainAlert", True) and loc.get("lat") is not None and time.time() - told > 3 * 3600:
                try:
                    r = rain_soon(loc["lat"], loc["lon"])
                    if r:
                        told = time.time()
                        self.js("rain", {"title": f"Rain in about {r['mins']} min", "text": f"{loc.get('name', '')} · {r['mm']:.1f} mm in the next hour"})
                except Exception as e:
                    extras.log("rain", repr(e))
            time.sleep(600)

    def monitor_loop(self):
        """The island follows the mouse to another screen, or sits on a chosen one."""
        last = None
        while True:
            time.sleep(0.6)
            L = self.L()
            mode = L.get("monitor", "primary")
            if mode == "primary" or not self.i.hwnd or self.i.expanded:
                last = None
                continue
            ms = monitors()
            if mode == "fixed":
                target = next((m for m in ms if m["index"] == L.get("monitorIndex", 0)), None)
            else:
                pt = wt.POINT()
                u32.GetCursorPos(ctypes.byref(pt))
                u32.MonitorFromPoint.restype = wt.HANDLE
                h = u32.MonitorFromPoint(pt, 2)
                target = next((m for m in ms if m["handle"] == h), None)
            if not target or target["work"] == last:
                continue
            last = target["work"]
            u32.MonitorFromWindow.restype = wt.HANDLE
            if u32.MonitorFromWindow(wt.HWND(self.i.hwnd), 2) == target["handle"]:
                continue
            l, t, r, b = target["work"]

            def move():
                _, _, w, h = self.i.rect()
                self.i.set_bounds(l + (r - l - w) / 2, t + self.i.top_gap() * self.i.scale(), w, h)
                self.i.reflow()
            host.ui_thread(self.i.window, move)

    # ---- Last.fm
    def scrobble_loop(self):
        key, start, played, done, last_t = None, 0, 0.0, False, time.time()
        while True:
            time.sleep(5)
            now = time.time()
            pb = self.i.playback or {}
            lf = self.cfg.get("lastfm") or {}
            on = self.L().get("scrobble") and lf.get("session")
            k = pb.get("uri") if pb and not pb.get("empty") else None
            if k != key:
                key, start, played, done = k, int(now), 0.0, False
                if on and k:
                    threading.Thread(target=lastfm_call, daemon=True, args=(lf, "track.updateNowPlaying",
                                     {"artist": pb.get("artist", ""), "track": pb.get("track", ""), "album": pb.get("album", "")})).start()
            elif k and pb.get("isPlaying"):
                played += now - last_t
            last_t = now
            dur = (pb.get("durationMs") or 0) / 1000
            if on and k and not done and dur > 30 and played >= min(dur / 2, 240):
                done = True
                threading.Thread(target=lastfm_call, daemon=True, args=(lf, "track.scrobble",
                                 {"artist": pb.get("artist", ""), "track": pb.get("track", ""), "album": pb.get("album", ""),
                                  "timestamp": str(start)})).start()

    # ---- what the page / settings app ask for
    def battery_light(self):
        import psutil
        b = psutil.sensors_battery()
        if not b:
            return {"pct": None}
        mins = None if b.secsleft in (psutil.POWER_TIME_UNLIMITED, psutil.POWER_TIME_UNKNOWN) else int(b.secsleft // 60)
        return {"pct": int(round(b.percent)), "charging": bool(b.power_plugged), "minutes": mins}

    def get_battery(self):
        import psutil
        out = self.battery_light()
        now = time.time()
        if now - getattr(self, "_health_at", 0) > 600:
            self._health_at = now
            # powercfg's battery report has the design and full capacity and
            # the cycle count without admin (the WMI design query needs it)
            xml = os.path.join(os.environ.get("TEMP", ""), "hop-battery.xml")
            try:
                subprocess.run(["powercfg", "/batteryreport", "/xml", "/output", xml], capture_output=True, timeout=20,
                               creationflags=NO_WINDOW)
                text = open(xml, encoding="utf-8", errors="replace").read()
                grab = lambda tag: int(m.group(1)) if (m := re.search(rf"<{tag}>(\d+)</{tag}>", text)) else None
                full, design, cycles = grab("FullChargeCapacity"), grab("DesignCapacity"), grab("CycleCount")
                self._health = {"full": full, "design": design, "cycles": cycles,
                                "health": round(100 * full / design) if full and design else None}
            except Exception:
                self._health = {}
        out.update(getattr(self, "_health", {}))
        procs = []
        for p in psutil.process_iter(["name"]):
            try:
                p.cpu_percent(None)
                procs.append(p)
            except psutil.Error:
                pass
        time.sleep(0.6)
        use = {}
        for p in procs:
            try:
                n = (p.info["name"] or "").replace(".exe", "")
                if n.lower() in ("system idle process", "idle", ""):
                    continue
                use[n] = use.get(n, 0) + p.cpu_percent(None) / psutil.cpu_count()
            except psutil.Error:
                pass
        out["drainers"] = [{"name": n, "cpu": c} for n, c in sorted(use.items(), key=lambda x: -x[1])[:3] if c > 0.2]
        return out

    def clip_stats(self):
        d = host.clips_dir()
        today = dt.date.today()
        n = 0
        try:
            for root, dirs, files in os.walk(d):
                if root.count(os.sep) - d.count(os.sep) > 1 or os.path.basename(root).startswith("."):
                    dirs[:] = []
                    continue
                for f in files:
                    if f.lower().endswith(".mp4") and dt.date.fromtimestamp(os.path.getmtime(os.path.join(root, f))) == today:
                        n += 1
        except OSError:
            pass
        return {"running": bool(u32.FindWindowW("clipper-tray", None)), "today": n}

    # shelf
    def get_shelf(self):
        items = []
        for it in self.cfg.get("shelf") or []:
            p = it.get("path", "")
            d = {"name": os.path.basename(p.rstrip("\\/")) or p, "path": p, "pinned": bool(it.get("pinned")),
                 "dir": os.path.isdir(p), "missing": not os.path.exists(p)}
            if p.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")) and os.path.exists(p):
                d["thumb"] = image_thumb(p, 96)[0]
            items.append(d)
        return items

    def shelf(self, op, path):
        items = [x for x in (self.cfg.get("shelf") or []) if x.get("path")]
        if op == "add" and path and os.path.exists(path):
            items = [x for x in items if x["path"] != path]
            items.insert(sum(1 for x in items if x.get("pinned")), {"path": path, "pinned": False, "at": time.time()})
        elif op == "remove":
            items = [x for x in items if x["path"] != path]
        elif op == "pin":
            for x in items:
                if x["path"] == path:
                    x["pinned"] = not x.get("pinned")
            items.sort(key=lambda x: not x.get("pinned"))
        self.cfg["shelf"] = items[:30]
        self.save()
        out = self.get_shelf()
        self.js("shelf", out)
        return out

    def drop(self, path):
        """A file was dropped on the island: what the settings say, or ask."""
        how = self.L().get("dropAction", "ask")
        if how == "shelf":
            self.shelf("add", path)
            self.js("reminder", {"title": "On the shelf", "text": os.path.basename(path), "icon": "pin", "bg": "#c7c7cc", "app": "Shelf"})
        elif how == "upload":
            self.i._upload(path)
        else:
            self.js("drop", {"name": os.path.basename(path), "path": path})

    def drop_choice(self, path, choice):
        if not path or not os.path.exists(path):
            return False
        if choice == "shelf":
            self.shelf("add", path)
        else:
            threading.Thread(target=self.i._upload, args=(path,), daemon=True).start()
        return True

    def trim(self, path, a, b):
        """The clip from a to b seconds, saved beside it as "<name> (trimmed)".
        Re-encoded (fast x264, every audio track kept), so the cut is exact:
        a stream copy could only cut on keyframes, up to 2 s off."""
        if not path or not os.path.exists(path):
            return None
        a, b = max(0.0, float(a)), float(b)
        if b - a < 0.4:
            return None
        stem, ext = os.path.splitext(path)
        out = f"{stem} (trimmed){ext}"
        n = 2
        while os.path.exists(out):
            out, n = f"{stem} (trimmed {n}){ext}", n + 1
        r = subprocess.run([extras.FFMPEG, "-v", "error", "-y", "-ss", f"{a:.3f}", "-i", path, "-t", f"{b - a:.3f}",
                            "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-map_metadata", "0",
                            "-movflags", "+faststart", out],
                           capture_output=True, creationflags=NO_WINDOW, timeout=300)
        if r.returncode or not os.path.exists(out):
            extras.log("trim failed", r.stderr[-300:])
            return None
        return {"path": out, "name": os.path.basename(out)}

    # extensions
    def _seed_extensions(self):
        """The bundled examples, copied once into the user's folder."""
        src = os.path.join(host.HERE, "extensions")
        if not os.path.isdir(src):
            return
        for name in os.listdir(src):
            dst = os.path.join(EXT_DIR, name)
            if not os.path.exists(dst):
                shutil.copytree(os.path.join(src, name), dst)

    def list_extensions(self):
        out = []
        try:
            names = sorted(os.listdir(EXT_DIR))
        except OSError:
            return out
        for name in names:
            if not re.fullmatch(r"[\w-]{1,40}", name):
                continue
            try:
                with open(os.path.join(EXT_DIR, name, "manifest.json"), encoding="utf-8") as fh:
                    m = json.load(fh)
            except (OSError, ValueError):
                continue
            page = str(m.get("page") or "page.html")
            if not re.fullmatch(r"[\w./-]{1,80}", page) or ".." in page:
                continue
            out.append({"id": name, "name": str(m.get("name") or name)[:40], "description": str(m.get("description") or "")[:120],
                        "url": f"https://ext.island/{name}/{page}"})
        return out

    # profiles, themes, backup
    def profile_save(self, name):
        name = str(name).strip()[:30]
        if name:
            self.cfg.setdefault("profiles", {})[name] = dict(self.L())
            self.cfg["activeProfile"] = name
            self.save()
        return sorted(self.cfg.get("profiles", {}))

    def profile_load(self, name):
        L = (self.cfg.get("profiles") or {}).get(name)
        if not L:
            return dict(self.L())
        self.cfg["activeProfile"] = name
        return self.i.set_layout(L)

    def profile_delete(self, name):
        (self.cfg.get("profiles") or {}).pop(name, None)
        self.cfg["profileRules"] = [r for r in self.cfg.get("profileRules") or [] if r.get("profile") != name]
        self.save()
        return sorted(self.cfg.get("profiles", {}))

    def theme_code(self):
        look = {k: self.L()[k] for k in LOOK_KEYS if k in self.L()}
        return "hop1." + base64.urlsafe_b64encode(json.dumps(look, separators=(",", ":")).encode()).decode().rstrip("=")

    def theme_apply(self, code):
        code = str(code or "").strip()
        if code.startswith("hop1."):
            code = code[5:]
        try:
            look = json.loads(base64.urlsafe_b64decode(code + "=" * (-len(code) % 4)).decode())
        except Exception:
            return None
        if not isinstance(look, dict):
            return None
        return self.i.set_layout(dict(self.L(), **{k: v for k, v in look.items() if k in LOOK_KEYS}))

    def export_settings(self):
        safe = {k: v for k, v in self.cfg.items() if k not in ("lastfm",)}
        path = os.path.join(DESKTOP(), f"Hop settings {dt.date.today().isoformat()}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"hop": 1, "config": safe}, fh, indent=2)
        return path

    def import_settings(self, path):
        try:
            with open(path, encoding="utf-8") as fh:
                d = json.load(fh)
            cfg = d["config"] if isinstance(d, dict) and "config" in d else d
            if not isinstance(cfg, dict):
                return None
        except (OSError, ValueError, KeyError):
            return None
        for k in ("calendarUrl", "notes", "prompter", "shelf", "profiles", "profileRules", "location", "prayerMethod", "asrSchool"):
            if k in cfg:
                self.cfg[k] = cfg[k]
        self.save()
        return self.i.set_layout(cfg.get("layout") or {})

    def diagnostics(self):
        path = os.path.join(DESKTOP(), f"Hop diagnostics {dt.datetime.now():%Y-%m-%d %H-%M}.zip")
        la = os.environ.get("LOCALAPPDATA", "")
        files = [extras.LOG, extras.LOG + ".old", os.path.join(os.environ.get("TEMP", ""), "island-debug.txt"),
                 os.path.join(la, "clipper", "clipper.log"), os.path.join(la, "clipper", "ffmpeg.log"),
                 os.path.join(la, "clipper", "settings.json")]
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            for f in files:
                if os.path.exists(f):
                    z.write(f, os.path.basename(f))
            cfg = {k: v for k, v in self.cfg.items() if k not in ("lastfm", "location", "calendarUrl", "notes")}
            z.writestr("island-config.json", json.dumps(cfg, indent=2))
            z.writestr("about.txt", f"Hop {host.VERSION}\n{dt.datetime.now().isoformat()}\n")
        return path

    def get_extra(self):
        lf = self.cfg.get("lastfm") or {}
        return {"calendarUrl": self.cfg.get("calendarUrl", ""), "prompter": self.cfg.get("prompter", ""),
                "profiles": sorted(self.cfg.get("profiles", {})), "activeProfile": self.cfg.get("activeProfile", ""),
                "profileRules": self.cfg.get("profileRules", []),
                "lastfm": {"user": lf.get("user", ""), "connected": bool(lf.get("session"))},
                "agents": {"connected": hooks_connected()},
                "monitors": [{k: m[k] for k in ("index", "name", "primary")} for m in monitors()],
                "extensions": self.list_extensions()}

    def set_extra(self, patch):
        patch = patch or {}
        if isinstance(patch.get("calendarUrl"), str):
            url = patch["calendarUrl"].strip()
            if url == "" or re.match(r"^(https?|webcal)://", url, re.I):
                self.cfg["calendarUrl"] = url
                self.js("calSet", bool(url))
        if isinstance(patch.get("prompter"), str):
            self.cfg["prompter"] = patch["prompter"][:20000]
        if isinstance(patch.get("profileRules"), list):
            self.cfg["profileRules"] = [{"exe": str(r.get("exe", "")).strip().lower()[:80], "profile": str(r.get("profile", ""))[:30]}
                                        for r in patch["profileRules"] if isinstance(r, dict)][:20]
        self.save()
        return self.get_extra()

    def lastfm_login(self, user, password, key, secret):
        try:
            r = lastfm_call({"key": key, "secret": secret}, "auth.getMobileSession", {"username": user, "password": password}, sign=True)
            sess = r["session"]["key"]
        except Exception as e:
            return {"connected": False, "error": "Last.fm said no: check the name, password, key and secret"}
        self.cfg["lastfm"] = {"user": user, "key": key, "secret": secret, "session": sess}
        self.save()
        return {"user": user, "connected": True}

    def agent_jump(self, sid):
        s = self.agents.sessions.get(sid) or {}
        name = (s.get("name") or "").lower()
        best = None
        for h, title in top_windows():
            t = title.lower()
            if name and name in t and ("claude" in t or "terminal" in t or "code" in t or "powershell" in t or ":\\" in t):
                best = h
                break
            if best is None and ("claude" in t and ("terminal" in t or "✳" in title)):
                best = h
        if best:
            bring_to_front(best)
        return bool(best)

    # in-app updates
    def install_update(self):
        def go():
            try:
                req = urllib.request.Request("https://api.github.com/repos/preinfection/hop/releases/latest",
                                             headers={"User-Agent": "hop-island", "Accept": "application/vnd.github+json"})
                with urllib.request.urlopen(req, timeout=15) as r:
                    rel = json.loads(r.read().decode())
                asset = next(a for a in rel.get("assets", []) if re.match(r"HopSetup-.*\.exe$", a.get("name", "")))
                latest = rel.get("tag_name", "").lstrip("vV")
                path = os.path.join(os.environ.get("TEMP", ""), asset["name"])
                with urllib.request.urlopen(urllib.request.Request(asset["browser_download_url"], headers={"User-Agent": "hop-island"}), timeout=60) as r, \
                        open(path, "wb") as fh:
                    total, got, last = int(r.headers.get("Content-Length") or asset.get("size") or 1), 0, 0
                    while True:
                        chunk = r.read(1 << 18)
                        if not chunk:
                            break
                        fh.write(chunk)
                        got += len(chunk)
                        if time.time() - last > 0.3:
                            last = time.time()
                            self.js("update", {"latest": latest, "state": "downloading", "progress": got / total})
                self.js("update", {"latest": latest, "state": "downloading", "progress": 1})
                # the installer closes both apps, installs over them and starts them again
                # (installer\hop.iss: the silent-install [Run] entries)
                self.js("update", {"latest": latest, "state": "installing"})
                time.sleep(1.2)                                  # the card says so before the island closes
                subprocess.Popen([path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], creationflags=NO_WINDOW)
            except Exception as e:
                extras.log("install update", repr(e))
                self.js("reminder", {"title": "Update failed", "text": "Opening the download page instead", "icon": "alert-triangle", "bg": "#ff9f0a", "app": "Hop"})
                self.i.open_release()
        threading.Thread(target=go, daemon=True).start()
        return True


# ------------------------------------------------------------------ outside services
def lastfm_call(cred, method, params, sign=True):
    p = dict(params, method=method, api_key=cred["key"])
    if cred.get("session"):
        p["sk"] = cred["session"]
    if sign:
        p["api_sig"] = hashlib.md5(("".join(k + str(p[k]) for k in sorted(p)) + cred["secret"]).encode("utf-8")).hexdigest()
    p["format"] = "json"
    data = urllib.parse.urlencode(p).encode()
    with urllib.request.urlopen(urllib.request.Request("https://ws.audioscrobbler.com/2.0/", data=data,
                                                       headers={"User-Agent": "hop-island"}), timeout=10) as r:
        return json.loads(r.read().decode())


def scores(teams):
    """Today's games for your teams from ESPN's public scoreboards."""
    out = []
    for league in sorted({t["league"] for t in teams}):
        names = [t["team"].lower() for t in teams if t["league"] == league]
        url = f"https://site.api.espn.com/apis/site/v2/sports/{options.LEAGUES[league]}/scoreboard"
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "hop-island"}), timeout=10) as r:
            d = json.loads(r.read().decode())
        lname = (d.get("leagues") or [{}])[0].get("abbreviation") or league.upper()
        for e in d.get("events", []):
            comp = (e.get("competitions") or [{}])[0]
            cs = comp.get("competitors") or []
            if len(cs) != 2:
                continue
            labels = " ".join((c.get("team") or {}).get(k, "") for c in cs for k in ("displayName", "shortDisplayName", "name", "abbreviation")).lower()
            if not any(n in labels for n in names):
                continue
            home = next((c for c in cs if c.get("homeAway") == "home"), cs[0])
            away = next((c for c in cs if c.get("homeAway") == "away"), cs[1])
            st = (comp.get("status") or e.get("status") or {}).get("type") or {}
            state = st.get("state", "pre")
            status = st.get("shortDetail") or st.get("detail") or ""
            out.append({"id": e.get("id"), "league": lname, "home": home["team"].get("shortDisplayName", "?"),
                        "homeLogo": home["team"].get("logo", ""), "awayLogo": away["team"].get("logo", ""),
                        "sport": options.LEAGUES[league].split("/")[0],
                        "away": away["team"].get("shortDisplayName", "?"), "hs": home.get("score", "0"), "as": away.get("score", "0"),
                        "state": state, "live": state == "in", "status": status})
    return out


def rain_soon(lat, lon):
    """{'mins', 'mm'} if it is dry now and rain starts within 45 minutes."""
    url = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&minutely_15=precipitation"
           f"&forecast_minutely_15=6&timezone=auto")
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "hop-island"}), timeout=10) as r:
        d = json.loads(r.read().decode())
    mm = (d.get("minutely_15") or {}).get("precipitation") or []
    if not mm or mm[0] > 0.05:
        return None
    for i, v in enumerate(mm[1:4], start=1):
        if v and v >= 0.1:
            return {"mins": i * 15, "mm": sum(x or 0 for x in mm[:4])}
    return None


# ------------------------------------------------------------------ the calls the page / settings app make
class FeatureApi:
    """Mixed into IslandApi (host.py): pywebview exposes these to the page."""

    @property
    def _f(self):
        return self._i.features

    def hop_hello(self):
        return self._f.hello()

    def need(self, n):
        self._f.need = n if isinstance(n, dict) else {}
        return True

    def sound(self, name):
        return self._f.sound(name)

    def play_sound(self, name):
        return self._f.sound(name)

    def get_battery(self):
        return self._f.get_battery()

    def get_shelf(self):
        return self._f.get_shelf()

    def shelf(self, op, path):
        return self._f.shelf(op, path)

    def drop_choice(self, path, choice):
        return self._f.drop_choice(path, choice)

    def get_notes(self):
        return self._i.cfg.get("notes", "")

    def set_notes(self, text):
        self._i.cfg["notes"] = str(text or "")[:20000]
        self._f.save()
        return True

    def get_startup(self):
        """Does Hop Island start with Windows? (Its startup shortcut, as the installer makes it.)"""
        return os.path.exists(os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup", "Hop Island.lnk"))

    def set_startup(self, on):
        self._i.cfg["startAtLogin"] = bool(on)
        host.write_config(self._i.cfg)
        host.set_startup(bool(on))
        return self.get_startup()

    def get_city(self):
        loc = self._i.cfg.get("location") or {}
        return loc.get("name") or (loc.get("label") or "").split(",")[0]

    def get_prompter(self):
        return self._i.cfg.get("prompter", "")

    def agent_answer(self, pid, ans):
        return self._f.agents.answer(pid, ans)

    def agent_jump(self, sid):
        return self._f.agent_jump(sid)

    def trim_clip(self, path, a, b):
        return self._f.trim(path, a, b)

    def upload_file(self, path):
        if path and os.path.isfile(path):
            threading.Thread(target=self._i._upload, args=(path,), daemon=True).start()
        return True

    def copy_image(self, path):
        try:
            return copy_image(path)
        except Exception as e:
            extras.log("copy image", repr(e))
            return False

    def show_file(self, path):
        if path and os.path.exists(path):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        return True

    def open_url(self, url):
        if isinstance(url, str) and re.match(r"^https://", url):
            os.startfile(url)
        return True

    def open_calendar(self):
        url = self._i.cfg.get("calendarUrl", "")
        os.startfile("https://calendar.google.com" if "google" in url else "https://outlook.live.com/calendar"
                     if re.search(r"outlook|office|live\.com", url) else "https://calendar.google.com")
        return True

    def want_keys(self, on):
        """Let the island take the keyboard while a text box is in use."""
        h = wt.HWND(self._i.hwnd)
        ex = u32.GetWindowLongW(h, -20)
        if on:
            u32.SetWindowLongW(h, -20, ex & ~0x08000000)           # not NOACTIVATE
            u32.SetForegroundWindow(h)
        else:
            u32.SetWindowLongW(h, -20, ex | 0x08000000)
        return True

    def install_update(self):
        return self._f.install_update()

    # settings app
    def get_extra(self):
        return self._f.get_extra()

    def set_extra(self, patch):
        return self._f.set_extra(patch)

    def agents_connect(self, on):
        set_hooks(bool(on))
        return {"connected": hooks_connected()}

    def profile_save(self, name):
        return self._f.profile_save(name)

    def profile_load(self, name):
        return self._f.profile_load(name)

    def profile_delete(self, name):
        return self._f.profile_delete(name)

    def theme_code(self):
        return self._f.theme_code()

    def theme_apply(self, code):
        return self._f.theme_apply(code)

    def export_settings(self):
        try:
            return self._f.export_settings()
        except OSError:
            return None

    def import_settings(self):
        import webview
        w = self._i.settings_win or self._i.window
        got = w.create_file_dialog(webview.OPEN_DIALOG, file_types=("Hop settings (*.json)",)) if w else None
        return self._f.import_settings(got[0]) if got else None

    def diagnostics(self):
        try:
            return self._f.diagnostics()
        except OSError:
            return None

    def lastfm_login(self, user, password, key, secret):
        return self._f.lastfm_login(user, password, key, secret)

    def open_extensions_folder(self):
        os.makedirs(EXT_DIR, exist_ok=True)
        os.startfile(EXT_DIR)
        return True
