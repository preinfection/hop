"""Every customisable thing about the island beyond the original switches:
its shape, colours, motion, what the closed pill shows, which pop-ups appear
and for how long, quiet hours, gestures, and the newer pages' options.

Each option has a type and a range, and `clean()` turns whatever was stored
or sent by the settings app into valid values (junk falls back to the
default, numbers are clamped), so a hand-edited or old config can never
break the island. host.clean_layout() merges these into the layout."""
import re

# pages added after 0.1.2: they start hidden, so an existing island looks the
# same until the user switches them on in the settings app
NEW_PAGES = ["agents", "timer", "calendar", "alerts", "shelf", "notes", "sports", "prompter", "battery"]

SLOTS = ("art", "clock", "bars", "timer", "agents", "net", "battery", "weather", "date", "rec", "none")
POPUPS = ("notif", "agent", "download", "snip", "calendar", "timer", "bt", "wifi", "caps", "focus",
          "sports", "rain", "reminder", "clip", "update", "upload", "game")
POPUP_SOUNDS = ("none", "tick", "pop", "chime", "bell")
LIVE = ("rec", "prayer", "timer", "agent", "focus", "mic")      # what may take over the closed pill
PRAYERS = ("Fajr", "Dhuhr", "Asr", "Maghrib", "Isha")

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EXE = re.compile(r"^[\w .()+-]{1,80}\.exe$", re.I)


def _bool(d):
    return ("bool", d)


def _enum(d, *choices):
    return ("enum", d, choices)


def _int(d, lo, hi):
    return ("int", d, lo, hi)


SPEC = {
    # ---- shape (-1 = the style's own value)
    "pillW": _int(126, 96, 280), "pillH": _int(37, 26, 52),
    "notchW": _int(200, 140, 340), "notchH": _int(32, 22, 48),
    "openW": _int(360, 320, 460), "openH": _int(150, 140, 210),
    "radiusClosed": _int(-1, -1, 26), "radiusOpen": _int(-1, -1, 56),
    "topGap": _int(-1, -1, 80),
    # ---- colour
    "bg": ("color", "#000000"), "bgOpacity": _int(100, 35, 100),
    "bgStyle": _enum("solid", "solid", "gradient", "tint"),
    "border": _bool(False), "borderColor": ("color", "#ffffff"), "borderOpacity": _int(18, 0, 100),
    "glow": _bool(False),
    "accentMode": _enum("album", "album", "custom"), "accentColor": ("color", "#0a84ff"),
    "font": _enum("inter", "inter", "segoe", "outfit", "mono", "system"),
    "clock24": _enum("auto", "auto", "12", "24"), "clockSeconds": _bool(False),
    "customCss": ("str", "", 20000),
    # ---- motion
    "anim": _enum("full", "full", "subtle", "reduced"),
    "bounce": _int(60, 0, 100), "speed": _int(100, 50, 200),
    # ---- how it opens and what gestures do
    "openOn": _enum("hover", "hover", "click"),
    "hoverDelay": _int(250, 0, 1500), "closeDelay": _int(0, 0, 2000),
    "swipeUp": _enum("dismiss", "dismiss", "nothing"),
    "dblClick": _enum("none", "none", "playpause", "settings", "record", "snap", "timer"),
    "middleClick": _enum("none", "none", "playpause", "mute", "next"),
    "wheel": _enum("pages", "pages", "volume", "none"),
    # ---- closed pill: three slots, and what may take it over (in order)
    "slotLeft": _enum("art", *SLOTS), "slotCenter": _enum("clock", *SLOTS), "slotRight": _enum("bars", *SLOTS),
    "priority": ("order", list(LIVE), LIVE),
    "idleHide": _bool(False), "idleAfter": _int(20, 5, 300), "idleStyle": _enum("line", "line", "fade"),
    "micCamDot": _bool(True), "clipDot": _bool(False),
    # ---- pop-ups: on/off, how long (ms) and the sound, per kind
    "popups": ("popups", None),
    "quiet": _bool(False), "quietFrom": ("time", "23:00"), "quietTo": ("time", "07:00"),
    "quietInFocus": _bool(True), "gameMode": _bool(True),
    "hideApps": ("exes", []),
    # ---- where it is
    "monitor": _enum("primary", "primary", "cursor", "fixed"), "monitorIndex": _int(0, 0, 8),
    "hotkey": _bool(True), "hotkeyKey": _enum("ctrl+alt+space", "ctrl+alt+space", "ctrl+shift+space", "alt+`", "win+alt+h"),
    "power": _enum("normal", "normal", "smart", "low"),
    # ---- player
    "shuffleRepeat": _bool(True),
    # ---- prayer
    "alarmPrayers": ("subset", list(PRAYERS), PRAYERS),
    "jumuah": _bool(True), "jumuahMins": _int(45, 10, 120),
    "alarmSound": _enum("chime", "chime", "bell", "soft", "none"),
    "ramadan": _bool(True),
    # ---- Today page extras
    "rainAlert": _bool(True), "countdowns": ("countdowns", []),
    "reminders": ("reminders", []),
    "capsPop": _bool(True), "wifiPop": _bool(True),
    # ---- AI agents
    "agentsOn": _bool(True), "agentSound": _bool(True), "agentSuppress": _bool(True),
    "agentApprove": _bool(True), "usagePill": _bool(False),
    # ---- clips
    "clipTrim": _bool(True), "clipUpload": _bool(True),
    "dropAction": _enum("ask", "ask", "upload", "shelf"),
    # ---- sports / teleprompter / last.fm
    "teams": ("teams", []),
    "prompterSpeed": _int(40, 10, 160),
    "scrobble": _bool(False),
    # ---- extensions switched on (folder names)
    "extensions": ("names", []),
}

POPUP_DEFAULT = {"on": True, "ms": 5000, "sound": "none"}
POPUP_DEFAULTS = {k: dict(POPUP_DEFAULT) for k in POPUPS}
POPUP_DEFAULTS["agent"]["sound"] = "pop"
POPUP_DEFAULTS["timer"].update(ms=12000, sound="chime")
POPUP_DEFAULTS["calendar"].update(ms=10000, sound="tick")
POPUP_DEFAULTS["caps"]["ms"] = 1500
POPUP_DEFAULTS["clip"]["ms"] = 7000
POPUP_DEFAULTS["update"]["ms"] = 0                     # 0 = stays until answered
POPUP_DEFAULTS["game"]["on"] = False


def default(key):
    spec = SPEC[key]
    if spec[0] == "popups":
        return {k: dict(v) for k, v in POPUP_DEFAULTS.items()}
    v = spec[1]
    return list(v) if isinstance(v, list) else v


DEFAULTS = {k: default(k) for k in SPEC}


def _clean_one(spec, v):
    kind = spec[0]
    if kind == "bool":
        return v if isinstance(v, bool) else None
    if kind == "enum":
        return v if v in spec[2] else None
    if kind == "int":
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            try:
                v = float(str(v))
            except (TypeError, ValueError):
                return None
        if v != v:                                     # NaN
            return None
        return int(round(min(spec[3], max(spec[2], v))))
    if kind == "color":
        return v.lower() if isinstance(v, str) and HEX.match(v) else None
    if kind == "time":
        return v if isinstance(v, str) and HHMM.match(v) else None
    if kind == "str":
        return v[:spec[2]] if isinstance(v, str) else None
    if kind == "order":
        if not isinstance(v, list):
            return None
        got = [x for x in dict.fromkeys(v) if x in spec[2]]
        return got + [x for x in spec[2] if x not in got]
    if kind == "subset":
        if not isinstance(v, list):
            return None
        return [x for x in spec[2] if x in v]
    if kind == "exes":
        if not isinstance(v, list):
            return None
        return [x.strip().lower() for x in dict.fromkeys(v) if isinstance(x, str) and EXE.match(x.strip())][:40]
    if kind == "names":
        if not isinstance(v, list):
            return None
        return [x for x in dict.fromkeys(v) if isinstance(x, str) and re.match(r"^[\w-]{1,40}$", x)][:30]
    if kind == "popups":
        out = {k: dict(d) for k, d in POPUP_DEFAULTS.items()}
        if isinstance(v, dict):
            for k, p in v.items():
                if k in out and isinstance(p, dict):
                    if isinstance(p.get("on"), bool):
                        out[k]["on"] = p["on"]
                    ms = _clean_one(_int(0, 0, 60000), p.get("ms"))
                    if ms is not None:
                        out[k]["ms"] = ms
                    if p.get("sound") in POPUP_SOUNDS:
                        out[k]["sound"] = p["sound"]
        return out
    if kind == "countdowns":
        if not isinstance(v, list):
            return None
        return [{"name": str(x["name"])[:40], "date": x["date"]} for x in v
                if isinstance(x, dict) and isinstance(x.get("name"), str) and x["name"].strip()
                and isinstance(x.get("date"), str) and DATE.match(x["date"])][:12]
    if kind == "reminders":
        if not isinstance(v, list):
            return None
        out = []
        for x in v:
            if not (isinstance(x, dict) and isinstance(x.get("text"), str) and x["text"].strip()):
                continue
            every = _clean_one(_int(60, 5, 1440), x.get("every"))
            out.append({"text": x["text"][:60], "every": every or 60,
                        "from": x["from"] if isinstance(x.get("from"), str) and HHMM.match(x["from"]) else "09:00",
                        "to": x["to"] if isinstance(x.get("to"), str) and HHMM.match(x["to"]) else "21:00",
                        "on": x.get("on") is not False})
        return out[:12]
    if kind == "teams":
        if not isinstance(v, list):
            return None
        return [{"league": x["league"], "team": str(x["team"])[:40]} for x in v
                if isinstance(x, dict) and x.get("league") in LEAGUES and isinstance(x.get("team"), str)
                and x["team"].strip()][:8]
    return None


# ESPN's public scoreboard paths for the sports page
LEAGUES = {
    "epl": "soccer/eng.1", "laliga": "soccer/esp.1", "ucl": "soccer/uefa.champions", "mls": "soccer/usa.1",
    "nba": "basketball/nba", "nfl": "football/nfl", "nhl": "hockey/nhl", "mlb": "baseball/mlb",
}


def clean(raw):
    """Valid values for every option, from a stored / sent dict (or junk)."""
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for k, spec in SPEC.items():
        v = _clean_one(spec, raw[k]) if k in raw else None
        out[k] = v if v is not None else default(k)
    return out


def in_quiet(now_hm, start, end):
    """Is "HH:MM" inside the quiet hours start..end (which may cross midnight)?"""
    if start == end:
        return False
    return start <= now_hm < end if start < end else (now_hm >= start or now_hm < end)
