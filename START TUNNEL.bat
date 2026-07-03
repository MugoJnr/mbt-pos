@echo off
title MBT POS — Start Cloudflare Tunnel
cd /d "%~dp0"
set "CF=%~dp0cloudflared.exe"
set "CFG=%USERPROFILE%\.cloudflared\config.yml"
if not exist "%CF%" set "CF=%~dp0..\..\cloudflared.exe"
if not exist "%CFG%" (
    echo config.yml not found. Run SETUP CLOUDFLARE.bat first.
    pause & exit /b 1
)
echo Starting tunnel for edmus.mugobyte.com ...
echo Keep this window open OR launch MBT POS (starts tunnel automatically).
echo.
"%CF%" tunnel --config "%CFG%" run
