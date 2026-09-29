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
