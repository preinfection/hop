"""Hop Island on Linux: start-up and the parts of host.Island that ask the
system something (music, volume, the window). The island's logic (hover,
pages, pop-ups, settings) is host.py's, unchanged; hop_linux answers its few
Windows calls and linux_backends supplies the information."""
import fcntl
import json
import os
import signal
import sys
import threading
import time
import urllib.parse

import hop_linux  # noqa: F401  (first: stands in for Windows)
import linux_backends as lx

import webview

import extras
import features
import host
import watch

LOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "hop-island.lock")


# ---------------------------------------------------------------- Linux answers for the shared modules
def _patch_modules():
    watch.foreground_exe = lx.foreground_exe
    watch.NotifWatcher = lx.NotifWatcher
    watch.privacy_in_use = lambda: {"mic": [], "cam": []}
    features.game_running = lx.fullscreen_app
    features.focus_on = lx.focus_on
    features.wifi_ssid = lx.wifi_ssid
    features.monitors = lambda: [{"index": i, "name": m["name"], "primary": m["primary"], "work": m["work"], "handle": i + 1}
                                 for i, m in enumerate(hop_linux.Win.monitors())]
    extras.power = lx.power
    extras.copy_text = lx.copy_text
    extras.default_output = lx.default_output
    extras.bt_output = lambda name: None
    extras.Clipboard = lx.Clipboard
    host.set_startup = lambda on: lx.set_autostart("Hop Island", _command(), on)
    host.remove_old_startup = lambda: None
    # pywebview serves the page from a small local web server on Linux: the
    # clips and extensions folders are linked into its folder (see _link_folders)
    host.clip_url = lambda path: "/_clips/" + "/".join(urllib.parse.quote(p) for p in os.path.relpath(path, host.clips_dir()).split(os.sep))
    features.EXT_BASE = "/_ext/"


def _link_folders():
    for name, target in (("_clips", host.clips_dir()), ("_ext", features.EXT_DIR)):
        os.makedirs(target, exist_ok=True)
        link = os.path.join(host.WEB, name)
        try:
            if os.path.islink(link) or os.path.exists(link):
                os.remove(link)
            os.symlink(target, link)
        except OSError as e:
            host.dbg("link", name, repr(e))


def _command():
    if host.FROZEN:
        return sys.executable
    return f"{sys.executable} {os.path.abspath(host.__file__)}"


class LinuxIsland(host.Island):
    """host.Island with Linux music (MPRIS), volume and restart."""

    player = None

    def media_loop(self):
        while True:
            try:
                self._mpris_tick()
            except Exception as e:
                host.dbg("mpris", repr(e))
            time.sleep(1.0)

    def _mpris_tick(self):
        p = lx.pick_player()
        self.player = p
        np = lx.now_playing(p) if p else None
        if not np or not np["track"]:
            if self.playback is None or not self.playback.get("empty"):
                self.playback = {"empty": True, "isPlaying": False, "progressMs": 0, "durationMs": 0, "track": "", "artist": "",
                                 "album": "", "artworkUrl": "", "uri": "", "app": p or "", "_sampled": time.time()}
                self.status = "Nothing playing"
                self.push()
            return
        key = f"{np['app']}|{np['track']}|{np['artist']}"
        art = np["art"]
        if art.startswith("file://"):
            art = "file://" + urllib.parse.quote(urllib.parse.unquote(art[7:]))
        new_track = key != self.track_key
        self.playback = {"empty": False, "isPlaying": np["isPlaying"], "progressMs": np["progressMs"], "durationMs": np["durationMs"],
                         "track": np["track"], "artist": np["artist"], "album": np["album"], "artworkUrl": art, "uri": key,
                         "shuffle": np["shuffle"], "repeat": np["repeat"], "app": np["app"], "_sampled": time.time()}
        self.status = "Linux media"
        if new_track:
            self.track_key = key
            threading.Thread(target=self._lyrics_for, daemon=True,
                             args=(key, np["track"], np["artist"], np["album"], np["durationMs"] / 1000)).start()
        self.push()

    def playback_action(self, action):
        if self.player:
            lx.control(self.player, action)
            threading.Timer(0.3, self._mpris_tick).start()
        return self.state()

    def seek(self, position_ms):
        if self.player:
            lx.seek(self.player, int(position_ms))
        return self.state()

    def get_volume(self):
        np = lx.now_playing(self.player) if self.player else None
        if not np or np["volume"] is None:
            return None
        return {"level": round(np["volume"], 3), "muted": np["volume"] == 0}

    def set_volume(self, level=None, muted=None):
        if self.player:
            if muted:
                self._unmute = (self.get_volume() or {}).get("level", 0.5)
                lx.set_volume(self.player, 0)
            elif level is not None:
                lx.set_volume(self.player, float(level))
            elif muted is False:
                lx.set_volume(self.player, getattr(self, "_unmute", 0.5))
        return self.get_volume()

    def restart_app(self):
        os.execv(sys.executable, [sys.executable] + ([] if host.FROZEN else [os.path.abspath(host.__file__)]))

    def open_clips_folder(self):
        os.makedirs(host.clips_dir(), exist_ok=True)
        os.startfile(host.clips_dir())
        return True

    def delete_clip(self, path):
        root = os.path.abspath(host.clips_dir())
        p = os.path.abspath(str(path or ""))
        if not p.startswith(root + os.sep) or not p.endswith(".mp4") or not os.path.isfile(p):
            return False
        try:
            import subprocess
            subprocess.run(["gio", "trash", p], timeout=10, check=True)            # to the Trash, undoable
        except Exception:
            os.remove(p)
        return not os.path.exists(p)

    def apply_capture_affinity(self):
        return None

    def _dress_settings(self):
        return None


# ---------------------------------------------------------------- one island at a time (the newest wins)
def take_over():
    fh = open(LOCK, "a+")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.seek(0)
        try:
            os.kill(int(fh.read().strip() or 0), signal.SIGTERM)
        except (ValueError, OSError):
            pass
        for _ in range(30):
            time.sleep(0.1)
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                continue
        else:
            return None
    fh.seek(0)
    fh.truncate()
    fh.write(str(os.getpid()))
    fh.flush()
    return fh


def main():
    if "--quit" in sys.argv:
        try:
            os.kill(int(open(LOCK).read().strip()), signal.SIGTERM)
        except (OSError, ValueError):
            pass
        return
    lock = take_over()
    if not lock:
        return
    _patch_modules()
    signal.signal(signal.SIGTERM, lambda *a: os._exit(0))
    island = LinuxIsland()
    island.hwnd = 1
    page = host.build_web()
    _link_folders()
    w, h = island.window_size()
    island.window = webview.create_window(
        "Hop Island", page, js_api=host.IslandApi(island), width=w, height=h,
        frameless=True, transparent=True, on_top=True, resizable=False, easy_drag=False, focus=True)

    def started():
        for _ in range(100):
            gw = island.window.native                       # pywebview's GTK backend: the Gtk.Window itself
            if gw is not None:
                break
            time.sleep(0.05)
        hop_linux.Win.gtk = gw

        def dress():
            from gi.repository import Gdk
            gw.set_skip_taskbar_hint(True)
            gw.set_skip_pager_hint(True)
            gw.set_keep_above(True)
            gw.stick()                                     # on every workspace
            # a dock: no title bar, above windows, not in Alt+Tab (the type only takes while unmapped)
            gw.hide()
            gw.set_type_hint(Gdk.WindowTypeHint.DOCK)
            gw.show()
            try:
                from webview.platforms.gtk import BrowserView
                wv = BrowserView.instances[island.window.uid].webview
            except Exception:
                wv = None
            if wv is not None:
                st = wv.get_settings()
                st.set_allow_file_access_from_file_urls(True)     # the clip card plays your clips
                st.set_allow_universal_access_from_file_urls(True)
                st.set_enable_developer_extras(bool(os.environ.get("HOP_DEBUG")))
        hop_linux.Win.call(dress)
        island.place_initial()
        island.set_region(False)
        for loop in (island.media_loop, island.hover_loop, island.rec_loop, island.prayer_loop, island.first_city,
                     island.update_loop, island.extras_loop, island.clip_watch):
            threading.Thread(target=loop, daemon=True).start()
        island.features.start()
        host.extras.log("Hop Island started on Linux:", hop_linux.SESSION, hop_linux.DESKTOP)

    def closing():
        return bool(getattr(island, "quitting", False))
    island.window.events.closing += closing
    webview.start(started, gui="gtk")


if __name__ == "__main__":
    main()
