<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/brand/hop-island-dark.png">
    <img src="assets/brand/hop-island-light.png" alt="Hop Island" height="44">
  </picture>
  &nbsp;&nbsp;&nbsp;&nbsp;
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/brand/hop-clipper-dark.png">
    <img src="assets/brand/hop-clipper-light.png" alt="Hop Clipper" height="44">
  </picture>
</p>

<p align="center">An iPhone-style island and a lightweight clipper for Windows, in one install.</p>

<p align="center"><a href="https://github.com/preinfection/hop/releases/latest"><b>Download the installer</b></a></p>

---

> **Early development.** Hop works day to day, but expect bugs and rough edges in performance.
> Please [open an issue](https://github.com/preinfection/hop/issues) when something breaks.

## Hop Island

A pill at the top of your screen that opens when you hover it.

- **Music.** Spotify (or any media app) with play / skip / seek, the album cover, music bars in the album's colours, a synced lyric line, and the app's own volume.
- **Pages.** Scroll for Today (Hijri date, Ramadan / Eid countdown, weather, prayer times), your newest clips, and PC stats (CPU, GPU, RAM, drives, ping and a speed test).
- **Prayer times** for your city, with a gentle alarm and chime. Pick your calculation method and Asr time.
- **Pop-ups** on the pill for charging, low battery and Bluetooth headphones.
- **Drop a file** on the island to upload it; the link is copied for you.
- **Settings app** (the gear on the last page): reorder, hide and customise every page, resize and move the island, with a live preview. Undo and reset are always there.

## Hop Clipper

- **F8** saves the last 15 s, 30 s or 1 min. Saving is instant, with no re-encoding.
- Records the whole screen at up to **1080p 120 fps**, fullscreen games included, with system audio.
- Full recordings from the island's record button.
- Light on the GPU, so games keep their frame rate.
- Settings (fps, quality, clip length, folder, watermark, what shows in clips) live in Hop Island's settings app.

## Install

1. Download `HopSetup-x.y.z.exe` from [Releases](https://github.com/preinfection/hop/releases/latest).
2. Pick **Hop Island**, **Hop Clipper**, or both.
3. Keep the recommended settings, or choose **Customize now** to set your city, clip length, fps and more right away.

Windows 10 (1809+) or 11, 64-bit. Hop Island needs the Microsoft Edge WebView2 Runtime, which Windows 11 already has.
No admin rights needed: Hop installs for your user only.

## Build from source

```powershell
pip install -r requirements.txt
powershell -File installer\build.ps1     # both apps, ffmpeg, and build\installer\HopSetup-*.exe
```

Needs Python 3.11, 7-Zip and Inno Setup 6. To run from source instead, put an ffmpeg build in `ffmpeg\` and start `island\host.py` / `clipper\clipper.py` with `pythonw`.

## Credits

Hop Island began as a port of [DynamicIslandWindows](https://github.com/garvrao80/DynamicIslandWindows) by Garv Rao (MIT).
Hop Clipper records with [FFmpeg](https://ffmpeg.org). See [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) for everything else.

MIT License.
