@echo off
chcp 65001 >nul
echo === MicVolumeTray exe build ===
uv run pyinstaller --onefile --noconsole --name MicVolumeTray mic_volume_tray.py
echo.
echo Done: dist\MicVolumeTray.exe
pause
