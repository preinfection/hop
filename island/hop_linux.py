"""Hop on Linux: the few Windows calls Hop makes, answered by Linux.

Hop Island and Hop Clipper were written against Windows (user32, the media
controls, the registry...). Rather than a second copy of their logic, this
module is imported first on Linux and stands in for the small part of the
Windows API they use: window geometry and the click region come from GTK,
"is Hop Clipper there / tell it to save" goes over a local socket, files open
with xdg-open, folders follow the XDG layout. Everything the island and the
clipper DECIDE stays shared; only how they ask the system differs.

Linux backends for the rest (music via MPRIS, battery via /sys, the app in
front via X11, notifications via D-Bus...) are in linux_backends.py.

Session: Hop runs its windows through XWayland on Wayland desktops
(GDK_BACKEND=x11), so placing the island at the top of the screen and keeping
it above other windows works the same on X11, KDE, GNOME, Hyprland and Sway.
"""
import ctypes
import os
import socket
import subprocess
import sys
import threading
import types

LINUX = sys.platform.startswith("linux")
HOME = os.path.expanduser("~")

# ---------------------------------------------------------------- the session (X11 / Wayland, which desktop)
SESSION = os.environ.get("XDG_SESSION_TYPE", "") or ("wayland" if os.environ.get("WAYLAND_DISPLAY") else "x11")
DESKTOP = os.environ.get("XDG_CURRENT_DESKTOP", "")


def install():
    """Call once, before importing any of Hop's modules."""
    if not LINUX or getattr(install, "done", False):
        return
    install.done = True
    import mimetypes
    mimetypes.init()                  # before the stand-ins: it would read "winreg" for file types
    # windows go through X11 (XWayland on Wayland): see the module docstring
    os.environ.setdefault("GDK_BACKEND", "x11")
    os.environ.setdefault("WEBKIT_DISABLE_COMPOSITING_MODE", "0")
    # Windows' folders, the XDG way: settings in ~/.config, data in ~/.local/share
    os.environ.setdefault("APPDATA", os.environ.get("XDG_CONFIG_HOME") or os.path.join(HOME, ".config"))
    os.environ.setdefault("LOCALAPPDATA", os.environ.get("XDG_DATA_HOME") or os.path.join(HOME, ".local", "share"))
    os.environ.setdefault("USERPROFILE", HOME)
    os.environ.setdefault("TEMP", "/tmp")
    os.startfile = startfile
    # Windows-only process options (no console window, job objects): Linux has none
    _popen = subprocess.Popen.__init__

    def _no_windows_flags(self, *a, **k):
        k.pop("creationflags", None)
        k.pop("startupinfo", None)
        _popen(self, *a, **k)
    subprocess.Popen.__init__ = _no_windows_flags
    ctypes.windll = _Windll()
    ctypes.oledll = ctypes.windll
    if not hasattr(ctypes, "WINFUNCTYPE"):
        ctypes.WINFUNCTYPE = ctypes.CFUNCTYPE
    try:
        __import__("ctypes.wintypes")      # pure ctypes structures (importing it here must not rebind "ctypes")
    except Exception:
        sys.modules["ctypes.wintypes"] = _wintypes()
    for name in ("winreg", "winsound", "pycaw", "pycaw.pycaw", "comtypes", "clr", "System", "System.Drawing",
                 "winrt", "winrt.windows", "winrt.windows.media", "winrt.windows.media.control",
                 "winrt.windows.storage", "winrt.windows.storage.streams", "winrt.windows.foundation"):
        sys.modules.setdefault(name, _Stub(name))


def startfile(path, *a):
    """os.startfile: open a file, folder or link with the desktop's default app."""
    subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def _wintypes():
    m = types.ModuleType("ctypes.wintypes")
    for n, t in {"DWORD": ctypes.c_uint32, "WORD": ctypes.c_uint16, "BOOL": ctypes.c_int, "UINT": ctypes.c_uint,
                 "HWND": ctypes.c_void_p, "HANDLE": ctypes.c_void_p, "LPARAM": ctypes.c_ssize_t, "WPARAM": ctypes.c_size_t,
                 "LPCWSTR": ctypes.c_wchar_p, "LONG": ctypes.c_long, "HMODULE": ctypes.c_void_p, "HICON": ctypes.c_void_p,
                 "HBITMAP": ctypes.c_void_p, "LPVOID": ctypes.c_void_p, "ULONG": ctypes.c_ulong, "HDC": ctypes.c_void_p}.items():
        setattr(m, n, t)

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class MSG(ctypes.Structure):
        _fields_ = [("hwnd", ctypes.c_void_p), ("message", ctypes.c_uint), ("wParam", ctypes.c_size_t), ("lParam", ctypes.c_ssize_t)]
    m.RECT, m.POINT, m.MSG = RECT, POINT, MSG
    return m


class _Stub(types.ModuleType):
    """A Windows-only module on Linux: any name in it is a do-nothing stand-in."""

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Nothing()


class _Nothing:
    def __call__(self, *a, **k):
        return 0

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Nothing()

    def __bool__(self):
        return False


def _out(arg):
    """The structure behind ctypes.byref(x) (what Windows would write into)."""
    return getattr(arg, "_obj", arg)


def _warn(fn, e):
    if os.environ.get("HOP_DEBUG") or not getattr(_warn, "seen", set()) >= {getattr(fn, "__qualname__", "?")}:
        _warn.seen = getattr(_warn, "seen", set()) | {getattr(fn, "__qualname__", "?")}
        print("hop_linux:", getattr(fn, "__qualname__", fn), repr(e), file=sys.stderr, flush=True)


# ---------------------------------------------------------------- the GTK window behind HWND 1 (the island)
class Win:
    """Set by the Linux host once pywebview's GTK window exists. Every call
    runs on the GTK thread and waits for its answer (at most a second)."""
    gtk = None            # Gtk.Window
    shape = None          # the click region (l, t, r, b), window-relative px
    pos = (0, 0)
    size = (0, 0)

    @classmethod
    def call(cls, fn, default=None):
        if cls.gtk is None:
            return default
        from gi.repository import GLib
        if threading.current_thread() is threading.main_thread():
            try:
                return fn()
            except Exception as e:
                _warn(fn, e)
                return default
        box, ev = [default], threading.Event()

        def run():
            try:
                box[0] = fn()
            except Exception as e:
                _warn(fn, e)
            ev.set()
            return False
        GLib.idle_add(run)
        ev.wait(1.0)
        return box[0]

    @classmethod
    def rect(cls):
        def get():
            x, y = cls.gtk.get_position()
            w, h = cls.gtk.get_size()
            cls.pos, cls.size = (x, y), (w, h)
            return x, y, w, h
        r = cls.call(get)
        return r or (*cls.pos, *cls.size)

    @classmethod
    def move_resize(cls, x, y, w, h):
        def go():
            if (w, h) != tuple(cls.gtk.get_size()):
                cls.gtk.resize(int(w), int(h))
            cls.gtk.move(int(x), int(y))
            cls.pos, cls.size = (int(x), int(y)), (int(w), int(h))
        cls.call(go)

    @classmethod
    def set_shape(cls, l, t, r, b):
        """Only this box takes clicks; the rest of the window lets them through."""
        cls.shape = (l, t, r, b)

        def go():
            import cairo
            gw = cls.gtk.get_window()
            if gw is not None:
                gw.input_shape_combine_region(cairo.Region(cairo.RectangleInt(int(l), int(t), max(1, int(r - l)), max(1, int(b - t)))), 0, 0)
        cls.call(go)

    @classmethod
    def pointer(cls):
        """The cursor on screen and whether the left button is down."""
        def get():
            from gi.repository import Gdk
            seat = Gdk.Display.get_default().get_default_seat()
            ptr = seat.get_pointer()
            _, x, y = ptr.get_position()
            gw = cls.gtk.get_window()
            mask = gw.get_device_position(ptr)[3] if gw is not None else 0
            return x, y, bool(int(mask) & int(Gdk.ModifierType.BUTTON1_MASK))
        return cls.call(get, (0, 0, False))

    @classmethod
    def workarea(cls, x=None, y=None):
        """The usable area (minus panels) of the monitor at (x, y), or the island's."""
        def get():
            from gi.repository import Gdk
            d = Gdk.Display.get_default()
            if x is not None:
                mon = d.get_monitor_at_point(int(x), int(y))
            elif cls.gtk.get_window() is not None:
                mon = d.get_monitor_at_window(cls.gtk.get_window())
            else:
                mon = d.get_primary_monitor() or d.get_monitor(0)
            r = mon.get_workarea()
            return r.x, r.y, r.x + r.width, r.y + r.height
        return cls.call(get, (0, 0, 1920, 1080))

    @classmethod
    def monitors(cls):
        def get():
            from gi.repository import Gdk
            d = Gdk.Display.get_default()
            out = []
            for i in range(d.get_n_monitors()):
                m = d.get_monitor(i)
                g, w = m.get_geometry(), m.get_workarea()
                out.append({"rect": (g.x, g.y, g.x + g.width, g.y + g.height), "work": (w.x, w.y, w.x + w.width, w.y + w.height),
                            "primary": m.is_primary(), "name": m.get_model() or f"Screen {i + 1}"})
            return out
        return cls.call(get, [])


# ---------------------------------------------------------------- Hop Clipper's "clipper-tray" window = a local socket
SOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/hop-{os.getuid() if hasattr(os, 'getuid') else 0}", "hop-clipper.sock")


def clipper_send(msg, wparam=0, lparam=0, timeout=0.5):
    """Send Hop Clipper one of its window messages; its answer (an int) or None."""
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(SOCK)
        s.sendall(f"{int(msg)} {int(wparam)} {int(lparam)}\n".encode())
        data = s.recv(64)
        s.close()
        return int(data.strip() or 0)
    except (OSError, ValueError):
        return None


def clipper_running():
    return clipper_send(0) is not None


# ---------------------------------------------------------------- user32 & co: the calls Hop makes
class _User32(_Nothing):
    def _FindWindowW(self, cls, title=None):
        """Only Hop Clipper's tray window is ever looked for: HWND 2 if it runs."""
        return 2 if cls == "clipper-tray" and clipper_running() else 0

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        f = getattr(type(self), "_" + name, None)
        if f is None:
            return _Nothing()
        return _Fn(lambda *a: f(self, *a))

    # geometry of the island's window (HWND 1)
    def _GetWindowRect(self, h, r):
        x, y, w, hh = Win.rect()
        o = _out(r)
        o.left, o.top, o.right, o.bottom = x, y, x + w, y + hh
        return 1

    def _SetWindowPos(self, h, after, x, y, w, hh, flags):
        if int(flags) & 0x0003 == 0x0003:              # NOSIZE | NOMOVE: just "stay on top"
            return 1
        Win.move_resize(x, y, w, hh)
        return 1

    def _GetCursorPos(self, p):
        x, y, _ = Win.pointer()
        o = _out(p)
        o.x, o.y = x, y
        return 1

    def _GetAsyncKeyState(self, vk):
        return 0x8000 if int(vk) == 0x01 and Win.pointer()[2] else 0

    def _GetDpiForWindow(self, h):
        return 96                                        # GTK scales by itself: Hop works in its logical pixels

    def _GetDpiForSystem(self):
        return 96

    def _GetWindowLongW(self, h, idx):
        return 0x8 if int(idx) == -20 else 0           # GWL_EXSTYLE: WS_EX_TOPMOST

    def _SystemParametersInfoW(self, what, a, r, b):
        if int(what) == 0x30:                           # SPI_GETWORKAREA
            o = _out(r)
            o.left, o.top, o.right, o.bottom = Win.workarea()
        return 1

    def _MonitorFromWindow(self, h, flags):
        return 1

    def _GetMonitorInfoW(self, mon, mi):
        o = _out(mi)
        l, t, r, b = Win.workarea()
        o.rcWork.left, o.rcWork.top, o.rcWork.right, o.rcWork.bottom = l, t, r, b
        o.rcMonitor.left, o.rcMonitor.top, o.rcMonitor.right, o.rcMonitor.bottom = l, t, r, b
        return 1

    def _SetWindowRgn(self, h, rgn, redraw):
        box = REGIONS.get(getattr(rgn, "value", rgn))
        if box:
            Win.set_shape(*box)
        return 1

    def _IsWindow(self, h):
        return 1 if h else 0

    # Hop Clipper's tray window: messages go over its socket
    def _PostMessageW(self, h, msg, w, l):
        if h == 2:
            return 1 if clipper_send(msg, w, l) is not None else 0
        return 0

    def _SendMessageTimeoutW(self, h, msg, w, l, flags, timeout, res):
        if h != 2:
            return 0
        got = clipper_send(msg, w, l, timeout=max(0.1, int(timeout) / 1000))
        if got is None:
            return 0
        try:
            _out(res).value = got
        except Exception:
            pass
        return 1

    def _GetSystemMetrics(self, i):
        l, t, r, b = Win.workarea()
        return {0: r - l, 1: b - t}.get(int(i), 0)


class _Fn:
    """A stand-in function that also takes ctypes' .restype / .argtypes."""

    def __init__(self, f):
        self.f = f
        self.restype = None
        self.argtypes = None

    def __call__(self, *a):
        return self.f(*a)


REGIONS = {}                          # CreateRectRgn's regions, by handle number


class _Gdi32(_Nothing):
    def __getattr__(self, name):
        if name == "CreateRectRgn":
            return _Fn(self._rgn)
        return _Nothing()

    @staticmethod
    def _rgn(l, t, r, b):
        n = len(REGIONS) % 1000 + 1
        REGIONS[n] = (int(l), int(t), int(r), int(b))
        return n


class _Kernel32(_Nothing):
    def __getattr__(self, name):
        if name == "GetSystemPowerStatus":
            return _Fn(self._power)
        return _Nothing()

    @staticmethod
    def _power(s):
        """Battery, as Windows' SYSTEM_POWER_STATUS (read from /sys)."""
        import linux_backends
        on_ac, pct = linux_backends.power()
        o = _out(s)
        o.ACLineStatus = 1 if on_ac else 0
        o.BatteryLifePercent = 255 if pct is None else int(pct)
        o.BatteryFlag = 128 if pct is None else 0
        return 1


class _Windll:
    def __init__(self):
        self.user32 = _User32()
        self.gdi32 = _Gdi32()
        self.kernel32 = _Kernel32()

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Nothing()


# install() runs as soon as this module is imported
install()
