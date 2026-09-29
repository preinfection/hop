"""Prayer times, the Today page and PC stats, against the REAL services and this
PC's real hardware. Cities are well-known public places, never the tester's."""
import datetime
import os
import re

import pytest

import extras
import prayer

CITIES = {"Makkah": (21.4225, 39.8262), "London": (51.5072, -0.1276), "Toronto": (43.6532, -79.3832),
          "Jakarta": (-6.2088, 106.8456), "Istanbul": (41.0082, 28.9784), "Cairo": (30.0444, 31.2357)}
METHODS = [1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 12, 13, 15, 16]
HM = re.compile(r"^\d{2}:\d{2}$")


def minutes(hm):
    h, m = map(int, hm.split(":"))
    return h * 60 + m


# ---- no city: nothing, quietly
def test_no_city_no_times():
    prayer.configure(None, None)
    prayer.refresh()
    d = prayer.today_and_tomorrow()
    assert d["today"] is None and d["tomorrow"] is None


def test_no_city_no_weather():
    prayer.configure(None, None)
    assert extras._weather() is None


# ---- real times for real cities, every method
@pytest.mark.network
@pytest.mark.parametrize("city", list(CITIES))
@pytest.mark.parametrize("method", METHODS)
def test_real_prayer_times(city, method, record_property):
    lat, lon = CITIES[city]
    prayer.configure(lat, lon, method, 0)
    prayer.refresh(force=True)
    d = prayer.today_and_tomorrow()
    t = d["today"]
    assert t is not None, "the API gave no times"
    assert set(t) == set(prayer.NAMES)
    assert all(HM.match(v) for v in t.values())
    # the day's order: Fajr < Sunrise < Dhuhr < Asr < Maghrib (Isha can pass midnight far north)
    seq = [minutes(t[n]) for n in ("Fajr", "Sunrise", "Dhuhr", "Asr", "Maghrib")]
    assert seq == sorted(seq)
    assert d["tomorrow"] is not None
    record_property("times", " ".join(f"{n} {t[n]}" for n in prayer.NAMES))


@pytest.mark.network
@pytest.mark.parametrize("school", [0, 1])
def test_hanafi_asr_is_later(school):
    prayer.configure(*CITIES["Cairo"], 5, 0)
    prayer.refresh(force=True)
    standard = minutes(prayer.today_and_tomorrow()["today"]["Asr"])
    prayer.configure(*CITIES["Cairo"], 5, 1)
    prayer.refresh(force=True)
    hanafi = minutes(prayer.today_and_tomorrow()["today"]["Asr"])
    assert hanafi > standard


@pytest.mark.network
def test_times_cached_offline(monkeypatch):
    prayer.configure(*CITIES["London"], 3, 0)
    prayer.refresh(force=True)
    first = prayer.today_and_tomorrow()

    def offline(*a, **k):
        raise OSError("offline")
    monkeypatch.setattr(prayer.urllib.request, "urlopen", offline)
    prayer.refresh(force=True)                      # fails quietly
    assert prayer.today_and_tomorrow() == first     # the saved copy is used


@pytest.mark.parametrize("a,b", [(("London", 3), ("London", 2)), (("London", 3), ("Cairo", 3))])
def test_cache_is_per_place_and_method(a, b):
    prayer.configure(*CITIES[a[0]], a[1], 0)
    p1 = prayer._path(2026, 1)
    prayer.configure(*CITIES[b[0]], b[1], 0)
    assert prayer._path(2026, 1) != p1


# ---- weather + Hijri
@pytest.mark.network
@pytest.mark.parametrize("city", list(CITIES))
def test_real_weather(city, record_property):
    prayer.configure(*CITIES[city])
    w = extras._weather()
    assert w and -60 < w["temp"] < 60 and w["low"] <= w["high"] and isinstance(w["code"], int)
    record_property("weather", f"{w['temp']}° (feels {w['feels']}°), low {w['low']}°, high {w['high']}°")


@pytest.mark.network
def test_real_hijri(record_property):
    h = extras._hijri()
    assert int(h["year"]) > 1440 and h["month"] and 1 <= int(h["day"]) <= 30
    names = [e["name"] for e in h["events"]]
    assert set(names) <= {"Ramadan", "Eid al-Fitr", "Eid al-Adha"} and names
    for e in h["events"]:
        assert datetime.date.fromisoformat(e["date"]) >= datetime.date.today()
    record_property("hijri", f"{h['day']} {h['month']} {h['year']}; next: " + ", ".join(f"{e['name']} {e['date']}" for e in h["events"]))


@pytest.mark.network
def test_today_page_whole():
    prayer.configure(*CITIES["Istanbul"], 13, 0)
    prayer.refresh(force=True)
    extras.forget_weather()
    t = extras.today()
    assert t.get("weather") and t.get("hijri")


def test_forget_weather_without_cache():
    extras.forget_weather()                         # no file yet: nothing happens


# ---- this PC, for real
def test_real_sys_stats(record_property):
    s = extras.sys_stats()
    assert 0 <= s["cpu"] <= 100
    assert s["gpu"] is None or 0 <= s["gpu"] <= 100
    assert 0 < s["ram"]["used"] <= s["ram"]["total"]
    assert "C" in s["disks"]
    for slot, d in s["disks"].items():
        assert slot in ("C", "E") and 0 <= d["free"] <= d["total"] and len(d["letter"]) == 1
    record_property("pc", f"CPU {s['cpu']:.0f}%, GPU {s['gpu'] if s['gpu'] is None else round(s['gpu'])}%, "
                          f"RAM {s['ram']['used'] / 2**30:.1f}/{s['ram']['total'] / 2**30:.1f} GB, "
                          + ", ".join(f"{d['letter']}: {d['free'] / 2**30:.0f} GB free" for d in s["disks"].values()))


def test_system_drive_first():
    s = extras.sys_stats()
    assert s["disks"]["C"]["letter"] == os.environ.get("SystemDrive", "C:")[0].upper()


@pytest.mark.parametrize("i", range(5))
def test_sys_stats_repeated(i):
    """Called again and again (the PC page polls it): always valid."""
    s = extras.sys_stats()
    assert 0 <= s["cpu"] <= 100


def test_power_reading():
    on_ac, pct = extras.power()
    assert on_ac in (True, False, None)
    assert pct is None or 0 <= pct <= 100


@pytest.mark.network
def test_real_ping(record_property):
    ms = extras.ping()
    assert ms is None or 0 <= ms < 5000
    record_property("ping", f"{ms} ms")


def test_ffmpeg_found_for_thumbnails():
    assert os.path.exists(extras.FFMPEG)


# ---- damaged files on disk never crash anything
@pytest.mark.parametrize("raw", ["", "{", "[]", "null", "42", '"x"', '{"days": []}'])
def test_damaged_prayer_cache(raw):
    prayer.configure(*CITIES["London"], 3, 0)
    today = datetime.date.today()
    p = prayer._path(today.year, today.month)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").write(raw)
    prayer.today_and_tomorrow()                     # no exception


@pytest.mark.parametrize("raw", ["", "{", "[]", "null", "7"])
def test_damaged_today_cache(raw, monkeypatch):
    os.makedirs(os.path.dirname(extras.TODAY_CACHE), exist_ok=True)
    open(extras.TODAY_CACHE, "w").write(raw)
    prayer.configure(None, None)
    monkeypatch.setattr(extras, "_hijri", lambda: {"day": "1", "month": "Muharram", "year": "1448", "events": []})
    extras.today()                                  # no exception
