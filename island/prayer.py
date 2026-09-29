"""Prayer times for the user's city (set in settings or the installer).

Fetched from the free Aladhan API (no account) once a day, a whole month per
request, and saved to disk. So the island keeps showing the right times when
the internet is down: weeks of them, not just today's.

    today_and_tomorrow() -> {"date": "2026-09-27", "today": {...}, "tomorrow": {...}}
    times are "HH:MM" in the city's local time (the PC is assumed to be there)
    With no city set, every day is None and the island hides prayer times.
"""
import datetime
import json
import os
import urllib.request

LAT = LON = None                      # set by configure(); None = no city chosen yet
METHOD, SCHOOL = 2, 0                 # Aladhan method id (2 = ISNA) and Asr school (0 = standard, 1 = Hanafi)
NAMES = ["Fajr", "Sunrise", "Dhuhr", "Asr", "Maghrib", "Isha"]
CACHE = os.path.join(os.environ["APPDATA"], "LyricsIslandLite", "prayer")


def configure(lat, lon, method=2, school=0):
    global LAT, LON, METHOD, SCHOOL
    LAT, LON = (float(lat), float(lon)) if lat is not None and lon is not None else (None, None)
    METHOD, SCHOOL = int(method), int(school)


def _path(year, month):
    # one cache per place and method, so changing either never shows stale times
    where = f"{LAT:.3f},{LON:.3f}-m{METHOD}s{SCHOOL}"
    return os.path.join(CACHE, where, f"{year}-{month:02d}.json")


def _fetch_month(year, month):
    url = (f"https://api.aladhan.com/v1/calendar/{year}/{month}"
           f"?latitude={LAT}&longitude={LON}&method={METHOD}&school={SCHOOL}")
    req = urllib.request.Request(url, headers={"User-Agent": "hop-island"})
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read().decode("utf-8"))["data"]
    days = {}
    for d in data:
        dd, mm, yyyy = d["date"]["gregorian"]["date"].split("-")
        days[f"{yyyy}-{mm}-{dd}"] = {n: d["timings"][n].split(" ")[0] for n in NAMES}
    os.makedirs(os.path.dirname(_path(year, month)), exist_ok=True)
    with open(_path(year, month), "w", encoding="utf-8") as fh:
        json.dump({"fetched": datetime.date.today().isoformat(), "days": days}, fh)
    return days


def _load_month(year, month):
    try:
        with open(_path(year, month), encoding="utf-8") as fh:
            got = json.load(fh)
        return got if isinstance(got, dict) else None       # a damaged file: fetch again
    except (OSError, ValueError):
        return None


def refresh(force=False):
    """Fetch this month (and next month near the end) unless already fetched
    today. Network errors are fine: the saved copy is used."""
    if LAT is None:
        return
    today = datetime.date.today()
    months = {(today.year, today.month)}
    soon = today + datetime.timedelta(days=3)
    months.add((soon.year, soon.month))
    for y, m in months:
        cached = _load_month(y, m)
        if not force and cached and cached.get("fetched") == today.isoformat():
            continue
        try:
            _fetch_month(y, m)
        except Exception:
            pass


def _day(date):
    if LAT is None:
        return None
    cached = _load_month(date.year, date.month)
    return (cached or {}).get("days", {}).get(date.isoformat())


def today_and_tomorrow():
    today = datetime.date.today()
    tomorrow = today + datetime.timedelta(days=1)
    return {"date": today.isoformat(), "today": _day(today), "tomorrow": _day(tomorrow)}


if __name__ == "__main__":
    refresh(force=True)
    print(json.dumps(today_and_tomorrow(), indent=2))
