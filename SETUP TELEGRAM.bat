@echo off
title MBT POS - Telegram Setup
color 0A
cd /d "%~dp0"
echo.
echo  Starting Telegram Setup Tool...
echo.
python "SETUP TELEGRAM.py"
if errorlevel 1 (
    echo.
    echo  Error running setup tool.
    pause
)
