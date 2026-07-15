@echo off
title silence.remove

if not exist venv (
    echo Virtual environment not found.
    echo Please run install.bat first.
    pause
    exit /b 1
)

call venv\Scripts\activate.bat

:: Make local FFmpeg available
if exist ffmpeg_bin (
    set "PATH=%cd%\ffmpeg_bin;%PATH%"
)

:menu
cls
echo ========================================
echo          silence.remove
echo ========================================
echo.
echo   1. Windows Desktop App (Recommended)
echo   2. Gradio Web App
echo   3. Exit
echo.

set /p choice=Select an option [Default: 1]: 

:: Default to Windows app if user just presses Enter
if "%choice%"=="" set choice=1

if "%choice%"=="1" (
    python windows.py
    goto :eof
)

if "%choice%"=="2" (
    python app.py
    goto :eof
)

if "%choice%"=="3" (
    exit
)

echo.
echo Invalid selection.
pause
goto menu
