"""Hop Clipper on Linux: start-up, the F8 keys, the toast window, and the
socket Hop Island talks to. Recording, the ring of pieces, cutting a clip
and the toast's drawing are clipper.py's, unchanged.

  picture   ffmpeg x11grab (the whole screen; XWayland apps on Wayland)
  sound     PulseAudio / PipeWire's monitor of your speakers (soundcard)
  F8        a global key grab (pynput, X11); on GNOME / KDE Wayland also
            `hop-clipper --save`, set as a keyboard shortcut on first start
  toast     a small always-on-top Tk window (no per-pixel transparency on
            X11, so the card is drawn on its own colour, without its shadow)
"""
import fcntl
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk

import clipper as C
import hop_linux
import linux_backends as lx

LOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "hop-clipper.lock")
WM_HOTKEY = 0x0312


# ---------------------------------------------------------------- the toast window
class LinuxLayered:
    """clipper.Layered on Linux: the same calls, a Tk window underneath."""
    root = None

    def __init__(self, on_mouse):
        self.on_mouse = on_mouse
        self.visible = False
        self.size = (1, 1)
        self.m = 0
        self.photo = None
        r = LinuxLayered.root
        self.w = tk.Toplevel(r)
        self.w.withdraw()
        self.w.overrideredirect(True)
        self.w.attributes("-topmost", True)
        try:
            self.w.attributes("-type", "notification")
        except tk.TclError:
            pass
        self.label = tk.Label(self.w, bd=0, highlightthickness=0, cursor="hand2")
        self.label.pack()
        self.label.bind("<Motion>", lambda e: self.on_mouse("move", e.x + self.m, e.y + self.m))
        self.label.bind("<Leave>", lambda e: self.on_mouse("leave", 0, 0))
        self.label.bind("<ButtonRelease-1>", lambda e: self.on_mouse("click", e.x + self.m, e.y + self.m))

    def apply_affinity(self):
        return None

    def set_image(self, img):
        from PIL import Image, ImageTk
        from toastui import MARGIN
        w, h = img.size
        m = min(int(MARGIN * C.Toast.SCALE), w // 3, h // 3)
        card = img.crop((m, m, w - m, h - m))
        bg = card.getpixel((card.width // 2, 4))[:3]                 # the card's own colour, behind its rounded corners
        flat = Image.new("RGB", card.size, bg)
        flat.paste(card, mask=card.split()[3])
        self.m, self.size = m, img.size
        self.photo = ImageTk.PhotoImage(flat)
        self.label.configure(image=self.photo, bg="#%02x%02x%02x" % bg)

    def present(self, x, y, alpha):
        self.w.geometry(f"+{int(x) + self.m}+{int(y) + self.m}")
        try:
            self.w.attributes("-alpha", max(0.0, min(1.0, alpha / 255)))
        except tk.TclError:
            pass
        if not self.visible:
            self.visible = True
            self.w.deiconify()
            self.w.lift()

    def hide(self):
        if self.visible:
            self.visible = False
            self.w.withdraw()


def _patch():
    C.FOLLOW_GAMES = False                         # always the whole screen (x11grab)
    C.Layered = LinuxLayered
    C.Toast.SCALE = 1.0
    C.work_area = lx.workarea
    C.game_label = lambda h=None: lx.app_label() or "Desktop"
    C.foreground = lambda: lx.foreground_exe() or "?"
    C.capture_target = lambda: None
    C.click_sound = _click
    orig_run_tk, orig_run = C.Toast._run_tk, C.Toast._run

    def run_tk(self):
        self.root = tk.Tk()
        self.root.withdraw()
        LinuxLayered.root = self.root
        self.beat_win = None
        hop_linux.Win.tk = self.root

        def poll():
            try:
                while True:
                    self._beat(self.bq.get_nowait())
            except Exception:
                pass
            self.root.after(100, poll)
        self.root.after(100, poll)
        self.tk_ready.set()
        self.root.mainloop()

    def run(self):
        self.tk_ready.wait(5)                     # the toast window lives in Tk
        orig_run(self)
    C.Toast._run_tk, C.Toast._run = run_tk, run


def _click():
    if not C.settings()["sounds"]:
        return
    for cmd in (["paplay", C.CLICK], ["pw-play", C.CLICK], ["aplay", "-q", C.CLICK]):
        if lx.have(cmd[0]):
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return


# ---------------------------------------------------------------- one clipper at a time
def take_over():
    fh = open(LOCK, "a+")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        hop_linux.clipper_send(WM_HOTKEY, 2)          # the older one quits the way Ctrl+Shift+F8 does
        for _ in range(120):
            time.sleep(0.1)
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                continue
        else:
            return None
    fh.seek(0)
    fh.truncate()
    fh.write(str(os.getpid()))
    fh.flush()
    return fh


# ---------------------------------------------------------------- the keyboard shortcut on Wayland desktops
def gnome_shortcut():
    """GNOME on Wayland lets no app grab F8: add a custom shortcut that runs
    `hop-clipper --save` (once; you can change the key in Settings -> Keyboard)."""
    if hop_linux.SESSION != "wayland" or "GNOME" not in hop_linux.DESKTOP.upper() or not lx.have("gsettings"):
        return
    base = "org.gnome.settings-daemon.plugins.media-keys"
    path = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/hop-clipper/"
    cur = subprocess.run(["gsettings", "get", base, "custom-keybindings"], capture_output=True, text=True).stdout.strip()
    if path in cur:
        return
    items = re.findall(r"'([^']+)'", cur)
    subprocess.run(["gsettings", "set", base, "custom-keybindings", str(items + [path])])
    kb = f"{base}.custom-keybinding:{path}"
    exe = sys.executable if C.FROZEN else f"{sys.executable} {os.path.abspath(C.__file__)}"
    for k, v in (("name", "Hop Clipper: save a clip"), ("command", f"{exe} --save"), ("binding", "F8")):
        subprocess.run(["gsettings", "set", kb, k, v])
    C.log("added the GNOME shortcut F8 -> --save")


def main():
    if "--save" in sys.argv or "--quit" in sys.argv:
        got = hop_linux.clipper_send(WM_HOTKEY, 2 if "--quit" in sys.argv else 1)
        sys.exit(0 if got is not None else 1)
    lock = take_over()
    if not lock:
        sys.exit(0)
    _patch()
    toast = C.Toast()
    later = []

    def check_updates(by_hand=False):
        got = C.latest_release()
        if got and C.version_tuple(got[0]) > C.version_tuple(C.VERSION):
            n = C.UpdateNotice(*got)
            later.append(n)
            toast.show(n)
        elif by_hand:
            toast.show(C.Note("Hop is up to date", f"You have v{C.VERSION}"))

    def update_loop():
        time.sleep(20)
        while True:
            if not any(getattr(n, "answered", False) for n in later):
                check_updates()
            time.sleep(24 * 3600)
    threading.Thread(target=update_loop, daemon=True).start()

    def save():
        C.log("F8 pressed;", C.foreground())
        press = C.Press(on_change=lambda: toast.q.put(("retitle", None)))
        toast.show(press)
        press.take()
        press.save()

    def rec_start():
        if C.Recording.CURRENT and C.Recording.CURRENT.running:
            return
        toast.show(C.Recording(on_change=lambda: toast.q.put(("retitle", None))))

    def rec_stop():
        r = C.Recording.CURRENT
        if r and r.running:
            r.stop()
            toast.show(r)

    quit_now = threading.Event()
    rec = {}

    def handle(msg, wparam):
        """Hop Island's messages (the same numbers as on Windows); the answer is an int."""
        if msg == WM_HOTKEY:
            if wparam == 1:
                threading.Thread(target=save, daemon=True).start()
            elif wparam == 2:
                quit_now.set()
            return 0
        if msg == C.WM_CLIP_RELOAD:
            C.apply_save_dir()
            if not (C.Recording.CURRENT and C.Recording.CURRENT.running):
                rec["run_id"] = "restart"
            return 0
        if msg in (C.WM_REC_START, C.WM_REC_STOP, C.WM_REC_TOGGLE):
            running = bool(C.Recording.CURRENT and C.Recording.CURRENT.running)
            if msg == C.WM_REC_START or (msg == C.WM_REC_TOGGLE and not running):
                rec_start()
            else:
                rec_stop()
        r = C.Recording.CURRENT
        return int(r.started * 1000) if r and r.running else 0          # also WM_REC_QUERY and 0 (are you there?)

    def serve():
        try:
            os.remove(hop_linux.SOCK)
        except OSError:
            pass
        os.makedirs(os.path.dirname(hop_linux.SOCK), exist_ok=True)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(hop_linux.SOCK)
        os.chmod(hop_linux.SOCK, 0o600)
        srv.listen(8)
        while not quit_now.is_set():
            try:
                c, _ = srv.accept()
                with c:
                    c.settimeout(1)
                    parts = (c.recv(64).decode() or "0 0 0").split()
                    msg, wparam = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
                    c.sendall(f"{handle(msg, wparam)}\n".encode())
            except Exception as e:
                C.log("socket", repr(e))
    threading.Thread(target=serve, daemon=True).start()

    # F8 and Ctrl+Shift+F8 (X11, and XWayland apps on Wayland)
    try:
        from pynput import keyboard
        keys = keyboard.GlobalHotKeys({"<f8>": lambda: handle(WM_HOTKEY, 1), "<ctrl>+<shift>+<f8>": lambda: handle(WM_HOTKEY, 2)})
        keys.daemon = True
        keys.start()
    except Exception as e:
        C.log("no global F8 here (use `hop-clipper --save` as a shortcut):", repr(e))
    try:
        gnome_shortcut()
    except Exception as e:
        C.log("gnome shortcut", repr(e))

    signal.signal(signal.SIGTERM, lambda *a: quit_now.set())
    stop = threading.Event()
    threading.Thread(target=C._keep_recording_forever, args=(stop, rec, toast.heartbeat), daemon=True).start()
    _click()
    C.log("Hop Clipper started on Linux:", hop_linux.SESSION, hop_linux.DESKTOP)
    quit_now.wait()
    r = C.Recording.CURRENT
    if r:
        r.stop()
        r.thread.join(60)
    stop.set()
    C.stop_ffmpeg(rec.get("ff"))
    C.Press.wait_all()
    os._exit(0)
