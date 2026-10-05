"""A pretend music player on the session bus (MPRIS), for testing Hop on
Linux without Spotify: it "plays" one song and answers play / pause / next."""
import time

from gi.repository import Gio, GLib

XML = """<node>
 <interface name="org.mpris.MediaPlayer2">
  <property name="Identity" type="s" access="read"/>
  <property name="DesktopEntry" type="s" access="read"/>
 </interface>
 <interface name="org.mpris.MediaPlayer2.Player">
  <method name="PlayPause"/><method name="Play"/><method name="Pause"/><method name="Next"/><method name="Previous"/>
  <method name="SetPosition"><arg type="o" direction="in"/><arg type="x" direction="in"/></method>
  <property name="PlaybackStatus" type="s" access="read"/>
  <property name="Metadata" type="a{sv}" access="read"/>
  <property name="Position" type="x" access="read"/>
  <property name="Volume" type="d" access="readwrite"/>
  <property name="CanControl" type="b" access="read"/>
  <property name="CanPlay" type="b" access="read"/><property name="CanPause" type="b" access="read"/>
  <property name="CanGoNext" type="b" access="read"/><property name="CanGoPrevious" type="b" access="read"/>
  <property name="CanSeek" type="b" access="read"/>
 </interface>
</node>"""
SONGS = [("Midnight City", "M83", "Hurry Up, We're Dreaming", 243), ("Nights", "Frank Ocean", "Blonde", 307)]
st = {"song": 0, "playing": True, "t0": time.time() - 61, "vol": 0.62}


def pos_us():
    return int((time.time() - st["t0"]) * 1e6) if st["playing"] else int(st.get("paused_at", 0) * 1e6)


def meta():
    t, a, al, d = SONGS[st["song"]]
    return {"mpris:trackid": GLib.Variant("o", f"/hop/track/{st['song']}"), "xesam:title": GLib.Variant("s", t),
            "xesam:artist": GLib.Variant("as", [a]), "xesam:album": GLib.Variant("s", al), "mpris:length": GLib.Variant("x", d * 1000000)}


def get_prop(conn, sender, path, iface, name):
    return {"Identity": GLib.Variant("s", "Spotify"), "DesktopEntry": GLib.Variant("s", "spotify"),
            "PlaybackStatus": GLib.Variant("s", "Playing" if st["playing"] else "Paused"), "Metadata": GLib.Variant("a{sv}", meta()),
            "Position": GLib.Variant("x", pos_us()), "Volume": GLib.Variant("d", st["vol"]), "CanSeek": GLib.Variant("b", True)}.get(
        name, GLib.Variant("b", True))


def set_prop(conn, sender, path, iface, name, value):
    if name == "Volume":
        st["vol"] = value.unpack()
    return True


def call(conn, sender, path, iface, method, params, inv):
    if method in ("PlayPause", "Play", "Pause"):
        if st["playing"]:
            st["paused_at"] = time.time() - st["t0"]
        else:
            st["t0"] = time.time() - st.get("paused_at", 0)
        st["playing"] = not st["playing"] if method == "PlayPause" else method == "Play"
    elif method in ("Next", "Previous"):
        st["song"] = (st["song"] + 1) % len(SONGS)
        st["t0"] = time.time()
    inv.return_value(None)


def acquired(conn, name):
    node = Gio.DBusNodeInfo.new_for_xml(XML)
    for i in node.interfaces:
        conn.register_object("/org/mpris/MediaPlayer2", i, call, get_prop, set_prop)


Gio.bus_own_name(Gio.BusType.SESSION, "org.mpris.MediaPlayer2.spotify", Gio.BusNameOwnerFlags.NONE, acquired, None, None)
GLib.MainLoop().run()
