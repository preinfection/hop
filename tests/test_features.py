"""The 0.1.3 features' host side (features.py, options.py, watch.py): the
option cleaning, Claude Code's hooks (installing them, and every decision
the island sends back), new-file watching, sounds, theme codes, trimming,
and the scoreboard / rain readers (with the services' replies recorded)."""
import io
import json
import os
import shutil
import subprocess
import threading
import time
import wave

import pytest

import extras
import features
import options
import watch


# ================================================================ options
def test_defaults_are_complete_and_clean():
    assert options.clean({}) == options.DEFAULTS
    assert options.clean("junk") == options.DEFAULTS


@pytest.mark.parametrize("key,given,expected", [
    ("pillW", 9999, 280), ("pillW", -5, 96), ("pillW", "150", 150), ("pillW", "wide", 126), ("pillW", True, 126),
    ("openH", 175.6, 176), ("radiusOpen", -1, -1), ("bounce", float("nan"), 60),
    ("bg", "#ABCDEF", "#abcdef"), ("bg", "red", "#000000"), ("bg", "#12345", "#000000"),
    ("quietFrom", "22:30", "22:30"), ("quietFrom", "25:00", "23:00"), ("quietFrom", 2230, "23:00"),
    ("font", "comic", "inter"), ("openOn", "click", "click"),
])
def test_values_are_clamped_or_fall_back(key, given, expected):
    assert options.clean({key: given})[key] == expected


def test_custom_css_is_capped():
    assert options.clean({"customCss": "x" * 30000})["customCss"] == "x" * 20000


def test_priority_keeps_every_kind_once():
    got = options.clean({"priority": ["timer", "timer", "nope", "rec"]})["priority"]
    assert got[:2] == ["timer", "rec"] and sorted(got) == sorted(options.LIVE)


def test_popups_merge_over_defaults():
    P = options.clean({"popups": {"notif": {"on": False, "ms": 99999, "sound": "bell"}, "evil": {"on": True},
                                  "download": {"sound": "airhorn"}}})["popups"]
    assert P["notif"] == {"on": False, "ms": 60000, "sound": "bell"}
    assert "evil" not in P and P["download"]["sound"] == "none" and P["timer"]["sound"] == "chime"


def test_lists_drop_junk():
    c = options.clean({"countdowns": [{"name": "Eid", "date": "2027-03-20"}, {"name": "", "date": "2027-01-01"}, {"name": "x", "date": "soon"}, 5],
                       "reminders": [{"text": "Water", "every": 1}, {"text": " "}, {"text": "Stretch", "from": "9", "to": "21:00"}],
                       "teams": [{"league": "epl", "team": "Arsenal"}, {"league": "nope", "team": "X"}],
                       "hideApps": ["PowerPnt.exe", "notepad", "../evil.exe", "a.exe", "a.exe"],
                       "alarmPrayers": ["Isha", "Fajr", "Lunch"], "extensions": ["world-clock", "../x", "a b"]})
    assert c["countdowns"] == [{"name": "Eid", "date": "2027-03-20"}]
    assert [r["text"] for r in c["reminders"]] == ["Water", "Stretch"] and c["reminders"][0]["every"] == 5
    assert c["reminders"][1]["from"] == "09:00"
    assert c["teams"] == [{"league": "epl", "team": "Arsenal"}]
    assert c["hideApps"] == ["powerpnt.exe", "a.exe"]
    assert c["alarmPrayers"] == ["Fajr", "Isha"] and c["extensions"] == ["world-clock"]


@pytest.mark.parametrize("now,start,end,inside", [
    ("23:30", "23:00", "07:00", True), ("03:00", "23:00", "07:00", True), ("07:00", "23:00", "07:00", False),
    ("12:00", "23:00", "07:00", False), ("13:00", "12:00", "14:00", True), ("09:00", "09:00", "09:00", False)])
def test_quiet_hours_cross_midnight(now, start, end, inside):
    assert options.in_quiet(now, start, end) is inside


# ================================================================ Claude Code hooks
def test_hooks_added_and_removed_keeping_yours(tmp_path):
    p = tmp_path / "settings.json"
    mine = {"model": "opus", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo mine"}]}]}}
    p.write_text(json.dumps(mine))
    assert features.set_hooks(True, str(p))
    cfg = json.loads(p.read_text())
    assert cfg["model"] == "opus"
    for ev in features.HOOK_EVENTS:
        assert any(features.HOOK_CMD == h["command"] for g in cfg["hooks"][ev] for h in g["hooks"]), ev
    assert any(h["command"] == "echo mine" for g in cfg["hooks"]["Stop"] for h in g["hooks"])
    assert features.hooks_connected(str(p))
    features.set_hooks(True, str(p))                                # twice: still one of ours per event
    assert sum(features.HOOK_CMD == h["command"] for g in json.loads(p.read_text())["hooks"]["Stop"] for h in g["hooks"]) == 1
    features.set_hooks(False, str(p))
    assert json.loads(p.read_text()) == mine
    assert not features.hooks_connected(str(p))
    assert json.loads((tmp_path / "settings.json.hop-backup").read_text()) == mine


def test_broken_claude_settings_never_overwritten(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("{ not json")
    assert features.set_hooks(True, str(p)) is False
    assert p.read_text() == "{ not json"


class FakeFeatures:
    def __init__(self, **layout):
        self.layout = dict(options.DEFAULTS, **layout)
        self.events = []
        self.front = False

    def L(self):
        return self.layout

    def js(self, kind, data):
        self.events.append((kind, data))

    def sound(self, name):
        pass

    def terminal_in_front(self, s):
        return self.front


def _answer_when_asked(hub, f, answer):
    seen = len(f.events)                                    # only a card asked from now on

    def go():
        for _ in range(200):
            asks = [d for k, d in f.events[seen:] if k == "agentAsk" and "id" in d]
            if asks:
                hub.answer(asks[-1]["id"], answer)
                return
            time.sleep(0.01)
    threading.Thread(target=go, daemon=True).start()


S = {"session_id": "s1", "cwd": r"C:\code\hop"}


def test_session_status_and_edits():
    f = FakeFeatures()
    hub = features.AgentHub(f, wait=1)
    assert hub.handle(dict(S, hook_event_name="SessionStart")) == {}
    hub.handle(dict(S, hook_event_name="UserPromptSubmit"))
    assert hub.public()["sessions"][0] | {} == {"id": "s1", "tool": "claude", "name": "hop", "status": "work", "detail": "Thinking…"}
    hub.handle(dict(S, hook_event_name="PostToolUse", tool_name="MultiEdit",
                    tool_input={"file_path": r"C:\code\hop\a.py", "edits": [{"old_string": "a", "new_string": "a\nb"}, {"old_string": "x\ny", "new_string": ""}]}))
    assert ("agentEdit", {"tool": "claude", "file": r"C:\code\hop\a.py", "plus": 2, "minus": 3}) in f.events
    hub.handle(dict(S, hook_event_name="SessionEnd"))
    assert hub.public()["sessions"] == []


@pytest.mark.parametrize("answer,behavior", [("allow", "allow"), ("deny", "deny"), ({"deny": "Use rg instead"}, "deny")])
def test_permission_answered_on_the_island(answer, behavior):
    f = FakeFeatures()
    hub = features.AgentHub(f, wait=3)
    _answer_when_asked(hub, f, answer)
    out = hub.handle(dict(S, hook_event_name="PermissionRequest", tool_name="Bash", tool_input={"command": "rm -rf build"}))
    d = out["hookSpecificOutput"]["decision"]
    assert out["hookSpecificOutput"]["hookEventName"] == "PermissionRequest" and d["behavior"] == behavior
    if isinstance(answer, dict):
        assert d["message"] == "Use rg instead"
    card = next(d for k, d in f.events if k == "agentAsk")
    assert card["kind"] == "permission" and card["summary"] == "rm -rf build" and card["verb"] == "run"


def test_no_answer_or_terminal_means_claude_asks_as_usual():
    f = FakeFeatures()
    hub = features.AgentHub(f, wait=0.2)
    assert hub.handle(dict(S, hook_event_name="PermissionRequest", tool_name="Bash", tool_input={"command": "ls"})) == {}
    _answer_when_asked(hub, f, "pass")
    assert hub.handle(dict(S, hook_event_name="PermissionRequest", tool_name="Bash", tool_input={"command": "ls"})) == {}
    f.front = True
    n = len(f.events)
    assert hub.handle(dict(S, hook_event_name="PermissionRequest", tool_name="Bash", tool_input={"command": "ls"})) == {}
    assert not any(k == "agentAsk" for k, _ in f.events[n:])        # looking at the terminal: no card


def test_switched_off_does_nothing():
    f = FakeFeatures(agentsOn=False)
    hub = features.AgentHub(f, wait=0.2)
    assert hub.handle(dict(S, hook_event_name="PermissionRequest", tool_name="Bash", tool_input={})) == {}
    assert f.events == [] and hub.sessions == {}


def test_plan_and_question():
    f = FakeFeatures()
    hub = features.AgentHub(f, wait=3)
    _answer_when_asked(hub, f, "allow")
    out = hub.handle(dict(S, hook_event_name="PermissionRequest", tool_name="ExitPlanMode", tool_input={"plan": "1. do it"}))
    assert out["hookSpecificOutput"]["decision"]["behavior"] == "allow"
    assert any(k == "agentAsk" and d["kind"] == "plan" and d["plan"] == "1. do it" for k, d in f.events)
    _answer_when_asked(hub, f, {"choice": ["0.1.3"]})
    out = hub.handle(dict(S, hook_event_name="PreToolUse", tool_name="AskUserQuestion",
                          tool_input={"questions": [{"question": "Which?", "options": [{"label": "0.1.3"}, {"label": "0.2"}]}]}))
    h = out["hookSpecificOutput"]
    assert h["permissionDecision"] == "deny" and "0.1.3" in h["permissionDecisionReason"]


def test_done_card_has_the_last_reply(tmp_path):
    t = tmp_path / "t.jsonl"
    t.write_text("\n".join(json.dumps(x) for x in [
        {"type": "user", "message": {"content": "hi"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "**All 688 tests** pass. Committed."}]}}]))
    f = FakeFeatures()
    hub = features.AgentHub(f)
    hub.handle(dict(S, hook_event_name="Stop", transcript_path=str(t)))
    card = next(d for k, d in f.events if k == "agentAsk")
    assert card["kind"] == "done" and card["summary"] == "All 688 tests pass. Committed."


def test_the_hook_server_answers_over_http():
    f = FakeFeatures()
    hub = features.AgentHub(f, wait=0.2)
    os.environ["HOP_AGENT_PORT"] = "47681"
    threading.Thread(target=hub.serve, daemon=True).start()
    import urllib.request
    for _ in range(50):
        try:
            r = urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:47681/hook", data=json.dumps(dict(S, hook_event_name="SessionStart")).encode(),
                                                              headers={"Content-Type": "application/json"}), timeout=2)
            break
        except OSError:
            time.sleep(0.05)
    assert json.loads(r.read()) == {} and "s1" in hub.sessions
    os.environ.pop("HOP_AGENT_PORT")


# ================================================================ small pieces
def test_meeting_links():
    assert watch.meeting_link("Join https://meet.google.com/abc-defg-hij.") == "https://meet.google.com/abc-defg-hij"
    assert watch.meeting_link("x https://us02web.zoom.us/j/123?pwd=a y") == "https://us02web.zoom.us/j/123?pwd=a"
    assert watch.meeting_link("no link here https://example.com") == ""


def test_new_files_wait_until_finished(tmp_path):
    w = features.NewFiles(str(tmp_path))
    (tmp_path / "old.txt").write_text("x")
    w.seen.add("old.txt")
    (tmp_path / "a.zip.crdownload").write_text("partial")
    (tmp_path / "a.zip").write_text("done")
    assert w.poll() == []                                   # first sight: maybe still growing
    assert w.poll() == [str(tmp_path / "a.zip")]
    assert w.poll() == []


def test_sounds_are_real_wav(tmp_path):
    for name, spec in features.SOUND_SPECS.items():
        p = tmp_path / f"{name}.wav"
        features.make_sound(str(p), spec)
        with wave.open(str(p)) as w:
            assert w.getnframes() > 500 and w.getframerate() == 22050


def test_theme_code_round_trip():
    class Isl:
        layout = dict(options.DEFAULTS, style="notch", bg="#112233", pages=["music"])
        cfg = {}

        def set_layout(self, L):
            self.layout = L
            return L
    f = features.Features.__new__(features.Features)
    f.i = Isl()
    code = f.theme_code()
    assert code.startswith("hop1.")
    f.i.layout = dict(options.DEFAULTS)
    L = f.theme_apply(code)
    assert L["bg"] == "#112233" and L["style"] == "notch"
    assert f.theme_apply("not a code") is None


@pytest.mark.slow
def test_trim_is_exact(tmp_path):
    src = tmp_path / "clip (6s).mp4"
    subprocess.run([extras.FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=6", "-f", "lavfi", "-i", "sine=d=6",
                    "-c:v", "libx264", "-g", "60", "-c:a", "aac", "-shortest", str(src)], check=True)
    f = features.Features.__new__(features.Features)
    out = f.trim(str(src), 1.3, 4.0)
    assert out["name"] == "clip (6s) (trimmed).mp4"
    probe = extras.FFMPEG.replace("ffmpeg.exe", "ffprobe.exe")
    dur = float(subprocess.run([probe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out["path"]],
                               capture_output=True, text=True).stdout)
    assert abs(dur - 2.7) < 0.1
    assert f.trim(str(src), 1.3, 4.0)["name"] == "clip (6s) (trimmed 2).mp4"
    assert f.trim(str(src), 2.0, 2.1) is None


def _reply(monkeypatch, payload):
    class R(io.BytesIO):
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(features.urllib.request, "urlopen", lambda *a, **k: R(json.dumps(payload).encode()))


def test_scores_pick_your_teams(monkeypatch):
    team = lambda n, s, ha: {"homeAway": ha, "score": s, "team": {"displayName": n, "shortDisplayName": n, "abbreviation": n[:3].upper()}}
    _reply(monkeypatch, {"leagues": [{"abbreviation": "EPL"}], "events": [
        {"id": "1", "competitions": [{"competitors": [team("Arsenal", "2", "home"), team("Chelsea", "1", "away")],
                                      "status": {"type": {"state": "in", "shortDetail": "67'"}}}]},
        {"id": "2", "competitions": [{"competitors": [team("Everton", "0", "home"), team("Fulham", "0", "away")],
                                      "status": {"type": {"state": "pre", "shortDetail": "3:00 PM"}}}]}]})
    ms = features.scores([{"league": "epl", "team": "arsenal"}])
    assert ms == [{"id": "1", "league": "EPL", "home": "Arsenal", "away": "Chelsea", "hs": "2", "as": "1", "state": "in", "live": True, "status": "67'"}]


@pytest.mark.parametrize("mm,expected", [([0, 0, 0.4, 1], {"mins": 30, "mm": 1.4}), ([0.5, 1, 1, 1], None), ([0, 0, 0, 0], None)])
def test_rain_soon(monkeypatch, mm, expected):
    _reply(monkeypatch, {"minutely_15": {"precipitation": mm}})
    assert features.rain_soon(43.9, -78.9) == expected


def test_lastfm_signature(monkeypatch):
    sent = {}

    class R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(req, timeout=0):
        sent["data"] = dict(features.urllib.parse.parse_qsl(req.data.decode()))
        return R(b'{"ok": 1}')
    monkeypatch.setattr(features.urllib.request, "urlopen", fake)
    features.lastfm_call({"key": "K", "secret": "S", "session": "SK"}, "track.scrobble", {"artist": "M83", "track": "Wait"})
    d = sent["data"]
    import hashlib
    want = hashlib.md5(("api_keyK" + "artistM83" + "methodtrack.scrobble" + "skSK" + "trackWait" + "S").encode()).hexdigest()
    assert d["api_sig"] == want and d["format"] == "json"
