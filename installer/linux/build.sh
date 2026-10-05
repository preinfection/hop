#!/bin/bash
# Builds Hop's Linux packages from this checkout: a .deb (Ubuntu, Debian, Mint),
# an .rpm (Fedora) and an AppImage (everything else), into build/linux/.
#
# Hop on Linux is Python: the packages hold Hop's code plus the few pure-Python
# libraries distros don't ship (pywebview, SoundCard, pynput and theirs), and use
# the distro's Python, GTK, WebKit, Pillow, numpy and FFmpeg.
#
# Needs: python3 + pip, fpm (gem install fpm), rpmbuild, appimagetool in
# /opt/tools or $APPIMAGETOOL. Run on Linux (or WSL): bash installer/linux/build.sh
set -euo pipefail
HOP="$(cd "$(dirname "$0")/../.." && pwd)"
VER="$(tr -d '[:space:]' < "$HOP/VERSION")"
OUT="$HOP/build/linux"
STAGE="$OUT/stage"
LIB="$STAGE/usr/lib/hop"
rm -rf "$OUT"
mkdir -p "$LIB" "$STAGE/usr/bin" "$STAGE/usr/share/applications" "$STAGE/etc/xdg/autostart" \
         "$STAGE/usr/share/icons/hicolor/256x256/apps" "$STAGE/usr/share/doc/hop"

# ---- Hop's own files
for d in island clipper assets; do
  cp -r "$HOP/$d" "$LIB/"
done
cp "$HOP/VERSION" "$HOP/LICENSE" "$HOP/TERMS.txt" "$HOP/THIRD-PARTY-NOTICES.md" "$LIB/"
find "$LIB" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$LIB" -name '*.ico' -delete
find "$LIB" -type f \( -name '*.py' -o -name '*.js' -o -name '*.css' -o -name '*.html' -o -name '*.json' -o -name '*.md' -o -name '*.txt' \) -exec sed -i 's/\r$//' {} +
cp "$HOP/LICENSE" "$HOP/TERMS.txt" "$STAGE/usr/share/doc/hop/"

# ---- the pure-Python libraries distros don't ship
python3 -m pip install --quiet --no-deps --no-compile --target "$LIB/vendor" \
  "pywebview>=6.2" bottle proxy_tools typing_extensions "SoundCard>=0.4.3" "pynput>=1.7" python-xlib six
rm -rf "$LIB/vendor/bin"

# ---- launchers
launcher() {  # app script
  cat > "$STAGE/usr/bin/hop-$1" <<SH
#!/bin/sh
# Hop's code in \${HOP_ROOT:-/usr/lib/hop}, run by the system's Python.
ROOT="\${HOP_ROOT:-/usr/lib/hop}"
export PYTHONPATH="\$ROOT/vendor\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 "\$ROOT/$2" "\$@"
SH
  chmod 755 "$STAGE/usr/bin/hop-$1"
}
launcher island island/host.py
launcher clipper clipper/clipper.py
cp "$HOP/assets/hop.png" "$STAGE/usr/share/icons/hicolor/256x256/apps/hop.png"
desktop() {  # file name exec comment
  cat > "$1" <<DT
[Desktop Entry]
Type=Application
Name=$2
GenericName=$4
Comment=$4
Exec=$3
Icon=hop
Terminal=false
Categories=Utility;AudioVideo;
StartupNotify=false
X-GNOME-Autostart-enabled=true
DT
}
desktop "$STAGE/usr/share/applications/hop-island.desktop" "Hop Island" hop-island "An island at the top of your screen"
desktop "$STAGE/usr/share/applications/hop-clipper.desktop" "Hop Clipper" hop-clipper "Save the last moments with F8"
cp "$STAGE/usr/share/applications/hop-island.desktop" "$STAGE/usr/share/applications/hop-clipper.desktop" "$STAGE/etc/xdg/autostart/"

COMMON=(-s dir -n hop -v "$VER" -a all --license MIT --vendor preinfection
        --maintainer "preinfection <278280836+preinfection@users.noreply.github.com>"
        --url https://gethop.lol --description "Hop: an iPhone-style island at the top of your screen and an instant F8 clipper"
        -C "$STAGE" --after-install "$HOP/installer/linux/after-install.sh")

# ---- .deb: Ubuntu, Xubuntu, Mint, Pop!_OS, Debian
fpm "${COMMON[@]}" -t deb -p "$OUT/hop_${VER}_all.deb" \
  -d 'python3 (>= 3.10)' -d python3-gi -d python3-gi-cairo -d gir1.2-gtk-3.0 -d gir1.2-webkit2-4.1 \
  -d python3-tk -d python3-pil -d python3-pil.imagetk -d python3-numpy -d python3-psutil -d python3-cffi \
  -d ffmpeg -d playerctl -d x11-utils -d libpulse0 -d fontconfig \
  --deb-recommends pulseaudio-utils --deb-recommends 'xclip | wl-clipboard' --deb-recommends network-manager \
  usr etc >/dev/null

# ---- .rpm: Fedora
fpm "${COMMON[@]}" -t rpm -p "$OUT/hop-${VER}-1.noarch.rpm" --rpm-os linux \
  -d 'python3 >= 3.10' -d python3-gobject -d gtk3 -d webkit2gtk4.1 -d python3-tkinter -d python3-pillow -d python3-pillow-tk \
  -d python3-numpy -d python3-psutil -d python3-cffi -d '(ffmpeg-free or ffmpeg)' -d playerctl -d xprop -d xdpyinfo \
  -d pulseaudio-libs -d fontconfig \
  usr etc >/dev/null

# ---- AppImage: one file; uses the system's Python, GTK and WebKit
APPDIR="$OUT/Hop.AppDir"
mkdir -p "$APPDIR"
cp -r "$STAGE/usr" "$APPDIR/"
cp "$HOP/assets/hop.png" "$APPDIR/hop.png"
desktop "$APPDIR/hop.desktop" "Hop" hop "An island at the top of your screen and an F8 clipper"
cp "$HOP/installer/linux/AppRun" "$APPDIR/AppRun"
sed -i 's/\r$//' "$APPDIR/AppRun"
chmod 755 "$APPDIR/AppRun"
TOOL="${APPIMAGETOOL:-/opt/tools/appimagetool}"
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$TOOL" --no-appstream "$APPDIR" "$OUT/Hop-${VER}-x86_64.AppImage" >/dev/null 2>&1

cd "$OUT"
sha256sum "hop_${VER}_all.deb" "hop-${VER}-1.noarch.rpm" "Hop-${VER}-x86_64.AppImage" | tee SHA256SUMS-linux.txt
ls -la "$OUT"/*.deb "$OUT"/*.rpm "$OUT"/*.AppImage
