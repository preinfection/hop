#!/bin/bash
# Runs Hop Island from this repo on a virtual screen (Xvfb + xfwm4 with its
# compositor), takes a screenshot after a few seconds, and prints the logs.
# Usage (WSL / any Linux): bash tools/linux/try-island.sh [seconds] [python]
set -u
SECS=${1:-15}
PY=${2:-python3}
HOP="$(cd "$(dirname "$0")/../.." && pwd)"
OUT=${HOP_TRY_OUT:-/tmp/hop-try}
mkdir -p "$OUT"
export DISPLAY=:99
unset WAYLAND_DISPLAY
Xvfb :99 -screen 0 1600x900x24 +extension Composite >/dev/null 2>&1 &
XV=$!
sleep 1
dbus-run-session -- bash -c "
  xsetroot -solid '#3a3f4b' 2>/dev/null
  xfwm4 --compositor=on >/dev/null 2>&1 &
  WM=\$!
  sleep 1
  python3 -c \"import tkinter as t; r=t.Tk(); r.geometry('1600x900+0+0'); r.configure(bg='#2f6f9f'); r.mainloop()\" &
  BG=\$!
  python3 '$HOP/tools/linux/fake-mpris.py' &
  MP=\$!
  sleep 1
  if [ -n \"\${HOP_CMD:-}\" ]; then timeout $SECS \$HOP_CMD > '$OUT/island.out' 2>&1 & else cd '$HOP/island' && timeout $SECS '$PY' host.py > '$OUT/island.out' 2>&1 & fi
  IS=\$!
  sleep $((SECS - 8))
  import -window root '$OUT/screen.png'
  xdotool mousemove 800 20
  sleep 3
  import -window root '$OUT/open.png'
  xdotool mousemove 800 700
  sleep 2
  xwininfo -root -tree 2>/dev/null | grep -i 'hop' > '$OUT/windows.txt'
  for w in \$(xwininfo -root -tree | grep -i 'Hop Island' | awk '{print \$1}'); do xwininfo -id \$w | grep -E 'Absolute|Width|Height|Map State' >> '$OUT/windows.txt'; xprop -id \$w _NET_WM_WINDOW_TYPE _NET_WM_STATE >> '$OUT/windows.txt'; done
  wait \$IS
  kill \$WM \$BG \$MP 2>/dev/null
"
kill $XV 2>/dev/null
echo "---- island stdout/stderr"; tail -40 "$OUT/island.out"
echo "---- Hop Island log"; tail -20 "${LOCALAPPDATA:-$HOME/.local/share}/Hop Island/"*.log 2>/dev/null || ls -la "$HOME/.local/share" 
echo "---- windows"; cat "$OUT/windows.txt"
echo "screenshot: $OUT/screen.png"
