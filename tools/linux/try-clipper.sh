#!/bin/bash
# Runs Hop Clipper from this repo on a virtual screen, saves a clip the way F8
# does (`clipper.py --save`), and checks the clip with ffprobe.
# Usage: bash tools/linux/try-clipper.sh [python]
set -u
PY=${1:-python3}
HOP="$(cd "$(dirname "$0")/../.." && pwd)"
OUT=${HOP_TRY_OUT:-/tmp/hop-try}
mkdir -p "$OUT"
export DISPLAY=:98
unset WAYLAND_DISPLAY
CLIPS="$HOME/Videos/Hop Clips"
rm -rf "$CLIPS"
Xvfb :98 -screen 0 1280x720x24 >/dev/null 2>&1 &
XV=$!
sleep 1
dbus-run-session -- bash -c "
  xfwm4 --compositor=on >/dev/null 2>&1 &
  WM=\$!
  # something that changes on screen: a window cycling colours with a counter
  python3 -c \"
import tkinter as t
r=t.Tk(); r.geometry('1280x720+0+0'); l=t.Label(r,font=('Sans',80)); l.pack(expand=1,fill='both'); n=[0]
def f():
    n[0]+=1; l.configure(text=str(n[0]), bg=['#c0392b','#2980b9','#27ae60','#8e44ad'][n[0]%4]); r.after(100,f)
f(); r.mainloop()\" &
  BG=\$!
  sleep 1
  RUN=\${CLIP_CMD:-\"'$PY' '$HOP/clipper/clipper.py'\"}
  eval \$RUN > '$OUT/clipper.out' 2>&1 &
  CP=\$!
  sleep 14
  eval \$RUN --save; echo \"save sent: \$?\"
  sleep 2
  import -window root '$OUT/toast.png'
  sleep 6
  eval \$RUN --quit; echo \"quit sent: \$?\"
  sleep 3
  kill \$CP \$WM \$BG 2>/dev/null
"
kill $XV 2>/dev/null
echo "---- clipper stdout/stderr"; tail -25 "$OUT/clipper.out"
echo "---- clipper log"; tail -15 "${LOCALAPPDATA:-$HOME/.local/share}/clipper/clipper.log" 2>/dev/null
echo "---- ffmpeg log"; tail -8 "${LOCALAPPDATA:-$HOME/.local/share}/clipper/ffmpeg.log" 2>/dev/null
echo "---- clips"; find "$CLIPS" -name '*.mp4' -exec ls -la {} \; 2>/dev/null
for f in "$CLIPS"/*.mp4 "$CLIPS"/*/*.mp4; do [ -f "$f" ] && ffprobe -v error -show_entries format=duration:stream=codec_type,width,height -of compact "$f"; done
