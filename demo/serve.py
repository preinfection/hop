r"""Hop's browser demo: the REAL island and settings pages (island\ui) on
localhost, driven by a simulated host (demo\host.js) instead of Windows.
Nothing here touches the installed Hop, its settings, or your clips.

    python demo\serve.py            -> http://localhost:8765/demo/

Each island / settings page gets demo\fake.js injected before its own
scripts; that gives it window.pywebview.api, answered by demo\host.js in
the demo page around it. The page's bridge.js and config.js (which the real
host writes at start) are served from here."""
import http.server
import json
import os
import socketserver
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "island"))
import options                                     # noqa: E402  (the same option list the host uses)

PORT = int(os.environ.get("HOP_DEMO_PORT", "8765"))


def demo_layout():
    """The island's full default layout, with every page switched on so the
    demo shows everything."""
    core = ["music", "today", "clips", "pc"]
    L = {"pages": core + options.NEW_PAGES, "hidden": [], "musicLeft": "rec", "musicRight": "prayer",
         "appTheme": "system", "style": "notch", "scale": 1.0}
    for k in ("lyricLine", "progress", "controls", "volume", "snap", "pillArt", "pillClock", "pillBars",
              "todayHijri", "todayEvents", "todayWeather", "todayPrayers", "gCpu", "gGpu", "gRam", "gDiskC",
              "gDiskE", "gPing", "actCharge", "actLow", "actBt", "prayCountdown", "clipCard", "prayerAlarm",
              "prayerChime", "marquee", "artColor"):
        L[k] = True
    L.update(options.DEFAULTS)
    L.update({"countdowns": [{"name": "Hop 0.2", "date": "2026-12-01"}],
              "reminders": [{"text": "Stretch", "every": 45, "from": "09:00", "to": "22:00", "on": True}],
              "teams": [{"league": "epl", "team": "Arsenal"}], "extensions": ["world-clock"]})
    return L


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)

    def log_message(self, *a):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _send(self, body, ctype):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/demo"):
            self.send_response(302)
            self.send_header("Location", "/demo/")
            self.end_headers()
            return
        if path == "/island/ui/bridge.js":
            return self._send(open(os.path.join(ROOT, "island", "bridge.js"), encoding="utf-8").read(), "text/javascript")
        if path == "/island/ui/config.js":
            return self._send("window.__layout = " + json.dumps(demo_layout()) + ";\n", "text/javascript")
        if path == "/demo/layout.json":
            return self._send(json.dumps({"layout": demo_layout(), "spec": {k: list(v) if isinstance(v, tuple) else v
                                                                            for k, v in options.SPEC.items()},
                                          "popupDefaults": options.POPUP_DEFAULTS}), "application/json")
        if path in ("/island/ui/index.html", "/island/ui/settings.html"):
            html = open(os.path.join(ROOT, path.lstrip("/")), encoding="utf-8").read()
            html = html.replace("<head>", '<head>\n    <script src="/demo/fake.js"></script>', 1)
            return self._send(html, "text/html; charset=utf-8")
        if path.startswith("/ext/"):                   # extensions, as the real host maps ext.island
            self.path = "/island/extensions/" + self.path[len("/ext/"):]
        return super().do_GET()


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    with Server(("127.0.0.1", PORT), Handler) as httpd:
        print(f"Hop demo: http://localhost:{PORT}/demo/")
        httpd.serve_forever()
