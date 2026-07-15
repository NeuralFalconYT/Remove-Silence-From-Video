@echo off
setlocal enabledelayedexpansion
title silence.remove - Installer

echo ================================================
echo    silence.remove  -  Windows Auto Installer
echo ================================================
echo.
echo This will:
echo   1. Create a private Python virtual environment (venv)
echo   2. Install gradio, auto-editor, pydub,Pillow inside it
echo   3. Install ffmpeg if it is missing
echo   4. Launch the app
echo.
echo Nothing is installed system-wide except ffmpeg (if needed).
echo ================================================
echo.
pause

:: ------------------------------------------------------------------
:: 1. Check Python is installed and reachable
:: ------------------------------------------------------------------
where python >nul 2>&1
if errorlevel 1 (
    echo.
    echo [ERROR] Python was not found on your PATH.
    echo Please install Python 3.10 from:
    echo   https://www.python.org/downloads/release/python-3100/
    echo IMPORTANT: on the install screen, check "Add Python to PATH".
    echo Then run this installer again.
    echo.
    pause
    exit /b 1
)

echo Found:
python --version
echo.

:: ------------------------------------------------------------------
:: 2. Create the virtual environment (only once)
:: ------------------------------------------------------------------
if not exist venv (
    echo Creating virtual environment "venv"...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Could not create the virtual environment.
        pause
        exit /b 1
    )
) else (
    echo Virtual environment already exists, skipping creation.
)

call venv\Scripts\activate.bat

:: ------------------------------------------------------------------
:: 3. Install Python dependencies
:: ------------------------------------------------------------------
echo.
echo Installing Python packages (this may take a minute)...
python -m pip install --upgrade pip
if exist requirements.txt (
    pip install -r requirements.txt
) else (
    pip install gradio==5.50.0 auto-editor==29.3.1 pydub
)
if errorlevel 1 (
    echo [ERROR] pip install failed. Check the messages above.
    pause
    exit /b 1
)

:: ------------------------------------------------------------------
:: 4. Check / install ffmpeg
:: ------------------------------------------------------------------
echo.
echo Checking for ffmpeg...
where ffmpeg >nul 2>&1
if not errorlevel 1 (
    echo ffmpeg is already installed and on PATH. Skipping.
    goto :launch
)

echo ffmpeg not found. Trying to install it automatically...

where winget >nul 2>&1
if not errorlevel 1 (
    echo Installing ffmpeg with winget, please wait...
    winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
    echo.
    echo ffmpeg install finished via winget.
    echo NOTE: if the app says "ffmpeg not found" on first run,
    echo close this window, open a NEW terminal, and run run.bat again
    echo so Windows picks up the updated PATH.
    goto :launch
)

echo winget is not available on this system. Downloading ffmpeg manually...
powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile 'ffmpeg_dl.zip'"
if not exist ffmpeg_dl.zip (
    echo [ERROR] Could not download ffmpeg automatically.
    echo Please download it yourself from https://www.gyan.dev/ffmpeg/builds/
    echo unzip it, and add the "bin" folder inside it to your PATH.
    pause
    goto :launch
)

powershell -NoProfile -Command "Expand-Archive -Path 'ffmpeg_dl.zip' -DestinationPath 'ffmpeg_tmp' -Force"

if not exist ffmpeg_bin mkdir ffmpeg_bin
for /d %%D in (ffmpeg_tmp\ffmpeg-*) do (
    copy "%%D\bin\*.exe" ffmpeg_bin\ >nul
)

del ffmpeg_dl.zip
rmdir /s /q ffmpeg_tmp

echo ffmpeg installed locally into the "ffmpeg_bin" folder of this project.
echo Adding it to PATH for this session...
set "PATH=%cd%\ffmpeg_bin;%PATH%"

echo.
echo For ffmpeg to keep working every time you open a NEW terminal window,
echo add this folder to your Windows PATH permanently:
echo   %cd%\ffmpeg_bin
echo (Search "Edit the system environment variables" in the Start Menu to do this.)
echo Otherwise, just always launch the app using run.bat from this folder,
echo which re-adds it automatically.
echo.

:launch
echo.
echo ================================================
echo   Setup complete. Launching silence.remove ...
echo ================================================
echo.
set "PATH=%cd%\ffmpeg_bin;%PATH%"
python windows.py

pause
