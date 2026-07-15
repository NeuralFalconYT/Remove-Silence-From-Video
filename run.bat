@echo off
title silence.remove

if not exist venv (
    echo Virtual environment not found. Run install.bat first.
    pause
    exit /b 1
)

call venv\Scripts\activate.bat

:: make the locally-downloaded ffmpeg available too, if it exists
if exist ffmpeg_bin (
    set "PATH=%cd%\ffmpeg_bin;%PATH%"
)

python app.py
pause
