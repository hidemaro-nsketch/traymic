# traymic

A lightweight Windows system tray app that displays your microphone input volume in real time.

The tray icon shows the current volume as a number with a color-coded bar graph.

## Features

- Displays mic input volume (0–100) on the system tray icon
- Color-coded bar graph indicator (green → yellow → red)
- Real-time updates via Windows audio change callbacks
- Fallback polling for cases callbacks can't catch (e.g. device switching)
- Right-click menu to quit

## Supported Operating Systems

- Windows 10
- Windows 11

## Install

### Standalone exe

Download `MicVolumeTray.exe` from [Releases](https://github.com/hidemaro-nsketch/traymic/releases) and run it.

### From source

```
git clone https://github.com/hidemaro-nsketch/traymic.git
cd traymic
uv sync
uv run python mic_volume_tray.py
```

## Build

Build a standalone exe with PyInstaller:

```
uv run pyinstaller --onefile --noconsole --name MicVolumeTray mic_volume_tray.py
```

Output: `dist/MicVolumeTray.exe`

## Dependencies

- [pycaw](https://github.com/AndreMiras/pycaw) — Python wrapper for Windows Core Audio API
- [comtypes](https://github.com/enthought/comtypes) — COM interface access
- [pystray](https://github.com/moses-palmer/pystray) — System tray icon
- [Pillow](https://github.com/python-pillow/Pillow) — Dynamic icon image generation

## License

MIT
