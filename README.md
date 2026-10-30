# MultiSpan

[中文说明](README.zh-CN.md) | English

**Equal-scale wallpaper splitter for mixed-resolution multi-monitor setups** — span one wallpaper across multiple monitors of different sizes/resolutions, with seams that actually line up.

Running one image across a 4K + 1080P dual-monitor setup? Windows' built-in "Span" just stretches pixels, and because the monitors have different pixel densities, the image never lines up at the seam. MultiSpan reads the **physical size** of each monitor (via EDID) and computes an equal-scale crop window per screen, so the picture stays geometrically continuous across displays.

## Features

- **Two-step wizard**: auto-detects all monitors (resolution / physical size / arrangement), visual layout boxes with editable dimensions, **drag-to-adjust** alignment, double-click to reset
- **Physical-scale cropping math**: crop windows are computed from pixel-per-cm density, so the image remains continuous even across mixed resolutions
- **Image / GIF / video support**: input format is the default output; static and animated outputs are freely selectable
- **Output files named by position**: `wallpaper_left.png`, `wallpaper_right.png`… no guessing when you set wallpapers
- **Monitor profiles**: save multiple monitor setups, reload anytime
- **Wallpaper Engine support**: drop in a WE wallpaper folder (image/GIF/video); private `.pkg` wallpapers fall back to a screen-recording method
- **Fully local**: no uploads, no accounts, no telemetry

## Download

| Channel | Link |
|---|---|
| GitHub Releases | https://github.com/unable616-hub/MultiSpan/releases/latest |

Single portable exe (~48 MB), **no installation, no dependencies** — ffmpeg is bundled.

## Usage

1. Double-click `MultiSpan.exe` → monitors are detected automatically
2. Verify the layout boxes (fix the numbers if detection is off, drag to fine-tune), save as a profile
3. Next step → drop in your media → Process
4. Open the output folder and set each file as its monitor's wallpaper

> First launch may trigger a SmartScreen / antivirus warning — this is normal for unsigned software. Click "More info → Run anyway".

## Uninstall

**Delete the exe — that's it.** Runtime data lives only in `%LocalAppData%\MultiSpan` (profiles, logs); remove the folder to wipe everything. No registry entries, no services.

## Known Limitations

- Output quality is bounded by the source image — the crop window on the lower-resolution screen uses fewer pixels and will lose detail when scaled (mathematically unavoidable)
- `.pkg` wallpapers are Wallpaper Engine's private format; the recording method reproduces the animation as recorded
- Monitors should be aligned edge-to-edge in a horizontal row; vertical stacking is not supported yet

## Tech Stack

Python stdlib HTTP server + Pillow + ffmpeg (imageio-ffmpeg) + pywebview, packaged with PyInstaller.

> **Disclaimer:** This project was built with AI assistance (code, docs and packaging). It is free, works fully offline, and collects no data.

---

LICENSE: MIT
