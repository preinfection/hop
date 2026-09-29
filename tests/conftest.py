"""Shared setup for Hop's tests.

REAL, NOT FAKE: the tests run the real code against real things (the host's
own API, the Aladhan / Open-Meteo / mutate.lol services, ffmpeg, this PC's
own CPU, drives and screen). Only one thing is swapped: every settings folder
points at a fresh temporary directory, BEFORE the apps are imported, so a test
run can never change the settings of a Hop that is installed on the machine.

Markers:  network (needs internet)   slow (encodes video / installs)
"""
import os
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The test browser (Playwright) lives under the REAL LocalAppData: pin it first.
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright"))
SANDBOX = tempfile.mkdtemp(prefix="hop-tests-")
for var in ("APPDATA", "LOCALAPPDATA"):
    os.environ[var] = os.path.join(SANDBOX, var)
    os.makedirs(os.environ[var], exist_ok=True)

# ffmpeg: the repo's own copy (ffmpeg\, as build.ps1 lays it out) or PATH
FFMPEG_DIR = os.path.join(ROOT, "ffmpeg")
if os.path.exists(os.path.join(FFMPEG_DIR, "ffmpeg.exe")):
    os.environ["HOP_FFMPEG_DIR"] = FFMPEG_DIR

sys.path[:0] = [os.path.join(ROOT, "island"), os.path.join(ROOT, "clipper")]


def pytest_configure(config):
    config.addinivalue_line("markers", "network: needs the internet")
    config.addinivalue_line("markers", "slow: encodes video or runs the installer")


@pytest.fixture(scope="session")
def sandbox():
    return SANDBOX


@pytest.fixture(scope="session")
def host():
    import host as h
    return h


@pytest.fixture(scope="session")
def clipper():
    import clipper as c
    return c


@pytest.fixture()
def island(host):
    """A real Island (no window): its config lives in the sandbox and starts
    empty for every test."""
    if os.path.exists(host.CONFIG):
        os.remove(host.CONFIG)
    cs = host.CLIPPER_SETTINGS
    if os.path.exists(cs):
        os.remove(cs)
    return host.Island()
