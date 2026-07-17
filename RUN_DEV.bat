@echo off
title MBT POS - Dev Run (no installer)
cd /d "%~dp0"
set "PY=C:\MBT_Build\_python311\python.exe"
if not exist "%PY%" (
  echo Python 3.11 not found at %PY%
  pause
  exit /b 1
)
echo.
echo  Running from SOURCE — no PyInstaller wait.
echo  Same shop DB as installed app (AppData).
echo  Close this window to quit.
echo.
"%PY%" launcher.py
if errorlevel 1 pause
