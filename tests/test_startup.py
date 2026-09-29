"""The real island, started for real: a second copy (its own settings, its own
log) runs for ~20 s and must come up cleanly: window up, clips folders mapped
for the Clips page, no Python errors. It shows on screen while it runs.

Added after a bug slipped through: the clips-folder mapping failed on every
start (a variable lost in a refactor), so the Clips page showed broken
thumbnails, and no test started the app itself."""
import os
import subprocess
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.mark.slow
def test_island_starts_cleanly(sandbox, record_property):
    temp = os.path.join(sandbox, "startup-temp")
    os.makedirs(temp, exist_ok=True)
    env = dict(os.environ, ISLAND_DEBUG="1", TEMP=temp, TMP=temp, HOP_TEST_INSTANCE="-test")
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    p = subprocess.Popen([pyw, os.path.join(ROOT, "island", "host.py")], cwd=os.path.join(ROOT, "island"), env=env)
    log = os.path.join(temp, "island-debug.txt")
    try:
        mapped = False
        for _ in range(40):
            time.sleep(0.5)
            if os.path.exists(log) and "clips mapped" in open(log, encoding="utf-8", errors="replace").read():
                mapped = True
                break
        assert p.poll() is None, "the island exited on its own"
        text = open(log, encoding="utf-8", errors="replace").read() if os.path.exists(log) else ""
        assert mapped, "the clips folders were never mapped:\n" + text[-800:]
        for bad in ("Traceback", "NameError", "AttributeError", "TypeError", "clips mapping"):
            assert bad not in text, f"{bad} in the log:\n" + text[-800:]
        record_property("started", "window up, clips + thumbnails folders mapped, no errors")
    finally:
        p.kill()
        p.wait(10)


def _start_island(tag, temp):
    env = dict(os.environ, ISLAND_DEBUG="1", TEMP=temp, TMP=temp, HOP_TEST_INSTANCE=tag)
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return subprocess.Popen([pyw, os.path.join(ROOT, "island", "host.py")], cwd=os.path.join(ROOT, "island"), env=env)


@pytest.mark.slow
def test_newer_island_takes_over(sandbox):
    """Starting Hop Island while one is running: the NEW one wins (after an
    update, the old version used to keep running until the PC restarted)."""
    temp = os.path.join(sandbox, "takeover")
    os.makedirs(temp, exist_ok=True)
    first = _start_island("-takeover", temp)
    try:
        time.sleep(8)
        assert first.poll() is None, "the first island didn't start"
        second = _start_island("-takeover", temp)
        try:
            first.wait(15)                              # asked to quit, and it did
            time.sleep(3)
            assert second.poll() is None, "the new island didn't stay up"
        finally:
            second.kill()
    finally:
        if first.poll() is None:
            first.kill()


# an "old version": holds the lock, has the window, ignores every message
STUBBORN = r"""
import ctypes, ctypes.wintypes as wt, sys, time
k = ctypes.windll.kernel32; u = ctypes.windll.user32
k.CreateMutexW(None, False, sys.argv[1])
WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
u.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]; u.DefWindowProcW.restype = ctypes.c_ssize_t
proc = WNDPROC(lambda h, m, w, l: 0 if m >= 0x8000 or m == 0x0312 else u.DefWindowProcW(h, m, w, l))
class WC(ctypes.Structure):
    _fields_ = [("style", wt.UINT), ("proc", WNDPROC), ("a", ctypes.c_int), ("b", ctypes.c_int), ("inst", wt.HINSTANCE),
                ("icon", wt.HICON), ("cur", wt.HANDLE), ("bg", wt.HBRUSH), ("menu", wt.LPCWSTR), ("cls", wt.LPCWSTR)]
wc = WC(proc=proc, cls=sys.argv[2]); u.RegisterClassW(ctypes.byref(wc))
u.CreateWindowExW.restype = wt.HWND
u.CreateWindowExW(0, sys.argv[2], "old", 0, 0, 0, 0, 0, None, None, None, None)
print("up", flush=True)
msg = wt.MSG()
while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
    u.DispatchMessageW(ctypes.byref(msg))
"""


@pytest.mark.parametrize("app", ["island", "clipper"])
def test_takes_over_from_an_old_unresponsive_copy(app):
    """An older version that doesn't understand the quit message is closed by
    force, and the new copy takes over."""
    mod = __import__("host" if app == "island" else "clipper")
    name, cls = f"Local\\hop-test-{app}-old", f"hop-test-{app}-old"
    old = subprocess.Popen([sys.executable, "-c", STUBBORN, name, cls], stdout=subprocess.PIPE, text=True)
    assert old.stdout.readline().strip() == "up"
    t0 = time.time()
    h = mod.take_over(name, cls, 0x8004, 0, wait=1.0)
    try:
        assert h, "didn't get the lock"
        old.wait(5)
        assert old.returncode is not None and time.time() - t0 < 6
    finally:
        if old.poll() is None:
            old.kill()
        if h:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(h)


@pytest.mark.parametrize("app", ["island", "clipper"])
def test_first_copy_gets_the_lock(app):
    mod = __import__("host" if app == "island" else "clipper")
    import ctypes
    h = mod.take_over(f"Local\\hop-test-{app}-first", f"hop-test-{app}-none", 0x8004, 0, wait=1.0)
    assert h
    ctypes.windll.kernel32.CloseHandle(h)


@pytest.mark.slow
def test_grey_backdrop_is_switched_off_again(sandbox):
    """Windows' Mica backdrop (the grey box around the open island) is switched
    back on by the window library on theme changes; the island turns it off."""
    import ctypes
    temp = os.path.join(sandbox, "backdrop")
    os.makedirs(temp, exist_ok=True)
    p = _start_island("-backdrop", temp)
    try:
        time.sleep(10)
        u, d = ctypes.windll.user32, ctypes.windll.dwmapi
        import psutil
        hwnds = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def each(h, _):
            pid = ctypes.c_ulong()
            u.GetWindowThreadProcessId(ctypes.c_void_p(h), ctypes.byref(pid))
            buf = ctypes.create_unicode_buffer(64)
            u.GetWindowTextW(ctypes.c_void_p(h), buf, 64)
            if pid.value == p.pid and buf.value == "Lyrics Island" and u.IsWindowVisible(ctypes.c_void_p(h)):
                hwnds.append(h)
            return True
        u.EnumWindows(each, 0)
        assert hwnds, "the test island's window wasn't found"
        h = ctypes.c_void_p(hwnds[0])
        d.DwmSetWindowAttribute(h, 38, ctypes.byref(ctypes.c_int(2)), 4)       # Mica on, as a theme change does
        kind = ctypes.c_int(-1)
        for _ in range(10):
            time.sleep(0.5)
            d.DwmGetWindowAttribute(h, 38, ctypes.byref(kind), 4)
            if kind.value == 1:
                break
        assert kind.value == 1, f"the backdrop stayed on ({kind.value})"
    finally:
        p.kill()
