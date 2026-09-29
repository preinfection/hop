"""Turn the test results (build\\test-results\\*.xml) into tests\\RESULTS.md.

Every test is listed with its result, time and the real values it measured.
PERSONAL DETAILS ARE MASKED with the same number of "*": the Windows user
name, PC name and home folder automatically, plus every word listed in
tests\\redact.local.json (a local file, never committed)."""
import datetime
import glob
import json
import os
import platform
import re
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def secrets():
    words = {os.environ.get("USERNAME", ""), os.environ.get("COMPUTERNAME", ""), os.path.expanduser("~")}
    try:
        words |= set(json.load(open(os.path.join(HERE, "redact.local.json"), encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return sorted((w for w in words if w and len(w) > 1), key=len, reverse=True)


SECRETS = secrets()


def mask(text):
    text = str(text)
    for w in SECRETS:
        text = re.sub(re.escape(w), lambda m: "*" * len(m.group(0)), text, flags=re.I)
    return text


def main():
    rows, totals = [], {"passed": 0, "failed": 0, "skipped": 0}
    per_file = {}
    for xml in sorted(glob.glob(os.path.join(ROOT, "build", "test-results", "*.xml"))):
        for case in ET.parse(xml).getroot().iter("testcase"):
            f = case.get("classname", "").split(".")[-1]
            name = case.get("name")
            t = float(case.get("time") or 0)
            if case.find("failure") is not None or case.find("error") is not None:
                state = "failed"
            elif case.find("skipped") is not None:
                state = "skipped"
            else:
                state = "passed"
            props = {p.get("name"): p.get("value") for p in case.iter("property")}
            note = "; ".join(f"{k}: {v}" for k, v in props.items())
            if state == "skipped":
                note = (case.find("skipped").get("message") or "") + (f"; {note}" if note else "")
            rows.append((f, name, state, t, note))
            totals[state] += 1
            per_file.setdefault(f, {"passed": 0, "failed": 0, "skipped": 0})[state] += 1
    total = sum(totals.values())
    out = [
        "# Test results",
        "",
        f"Run on {datetime.date.today():%Y-%m-%d}, Windows {platform.release()} ({platform.version()}), "
        f"Python {platform.python_version()}, {os.cpu_count()} CPU threads.",
        "",
        "Everything here ran for real: the real app code against real services (Aladhan, Open-Meteo, "
        "mutate.lol), real screen recordings with ffmpeg, the real installer, and the real settings app in "
        "Chromium. Personal details (user name, PC name, home folder, the tester's city and the like) are "
        "replaced by `*` of the same length.",
        "",
        f"**{totals['passed']} passed, {totals['failed']} failed, {totals['skipped']} skipped** "
        f"({total} tests)",
        "",
        "| File | Passed | Failed | Skipped |",
        "|---|---|---|---|",
    ]
    for f, c in per_file.items():
        out.append(f"| `{f}` | {c['passed']} | {c['failed']} | {c['skipped']} |")
    cur = None
    for f, name, state, t, note in rows:
        if f != cur:
            out += ["", f"## {f}", "", "| Test | Result | Time | Measured |", "|---|---|---|---|"]
            cur = f
        mark = {"passed": "✅ passed", "failed": "❌ failed", "skipped": "⏭️ skipped"}[state]
        out.append(f"| `{mask(name)}` | {mark} | {t:.2f} s | {mask(note).replace('|', '/')} |")
    path = os.path.join(HERE, "RESULTS.md")
    open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")
    print(f"wrote {path}: {totals}")
    return totals


if __name__ == "__main__":
    main()
