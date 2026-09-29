# Tests

Over 1,000 tests. They run the real code against real things rather than stand-ins:

| File | What it checks |
|---|---|
| `test_layout.py` | The island's layout rules: every page order, every set of hidden pages, every switch, every choice, and bad or damaged values |
| `test_clipper.py` | Hop Clipper's settings, plus **real screen recordings** in every combination of frame rate (30/60/120), quality, watermark and cursor, checked with ffprobe. Also real clips at 15 s, 30 s and 1 min, a clip across two recorder runs, a clean stop, and ffmpeg never outliving the clipper |
| `test_prayer_and_extras.py` | **Real prayer times** from Aladhan for six cities across all 14 calculation methods, real weather and Hijri dates, this PC's real CPU/GPU/RAM/drives, and damaged cache files |
| `test_host.py` | The island's API as the settings app and the installer use it: config files, the installer handoff, **real city search**, Hop Clipper's settings, the Clips page with real thumbnails, and a **real anonymous upload** to mutate.lol |
| `test_ui.py` | The settings app and the island page in Chromium (the engine WebView2 uses), wired to the real host API: every switch, choice, page move, undo, reset, size, position, theme, tooltip and the Clipper tab |
| `test_startup.py` | Starts a second real island for about 20 seconds and checks it comes up cleanly |
| `test_installer.py` | The real installer: silent installs of each component choice, startup entries, a customised install, and a clean uninstall |

`RESULTS.md` is the latest full run: every test, its result, and the real values it measured. Personal details (user name, PC name, home folder, the tester's own city and the like) are replaced by `*` of the same length.

## Running them

```powershell
pip install -r requirements.txt pytest pytest-timeout playwright
python -m playwright install chromium
python -m pytest tests -m "not slow"                            # quick: about 2 minutes
python -m pytest tests --junitxml=build\test-results\all.xml     # everything: about 15 minutes
python tests\make_report.py                                     # writes tests\RESULTS.md
```

- **Isolation:** the tests use their own temporary settings folders, so they never change an installed Hop's settings. The one exception is the customised-install test: it backs up this PC's real settings files first and restores them afterwards.
- **Network:** tests that need the internet are marked `network`.
- **Slow:** tests that record video or install are marked `slow`.
- **Screen:** recording tests capture your screen for a few seconds each, and the startup test shows a second island briefly.
