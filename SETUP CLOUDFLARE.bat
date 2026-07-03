@echo off
title MBT POS — Cloudflare Setup (mugobyte.com)
cls
echo.
echo  MBT POS — Cloudflare Tunnel Setup
echo  ==================================
echo.
echo  Creates: https://yourshop.mugobyte.com
echo.
echo  Options:
echo    SETUP CLOUDFLARE.bat --shop "Shop Name"
echo    SETUP CLOUDFLARE.bat --relogin     (fix auth error 10000)
echo    SETUP CLOUDFLARE.bat --diagnose
echo.
echo  Log: logs\cloudflare_setup.log
echo.

cd /d "%~dp0"
set "PY=C:\MBT_Build\_python311\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" -c "import sys; sys.path.insert(0,r'%~dp0.'); from backend.cloudflare_setup import cli_main; cli_main()" %*

if errorlevel 1 (
    echo.
    echo  ============================================================
    echo  SETUP FAILED
    echo  ============================================================
    echo.
    echo  Auth error 10000?  Run:  SETUP CLOUDFLARE.bat --relogin
    echo  In browser: log into MugoByte account, authorize mugobyte.com
    echo.
    echo  Or add API token to config\deploy.local.json
    echo  (see config\deploy.local.json.example)
    echo.
    echo  Diagnostics:  DIAGNOSE CLOUDFLARE.bat
    echo  ============================================================
    echo.
    pause
    exit /b 1
)

echo  Done.
echo.
echo  Remote URL:  see web_config.json tunnel_domain
echo  Local URL:   http://localhost:5050
echo.
echo  If remote URL is not live yet, wait 2-5 minutes for DNS,
echo  then run DIAGNOSE CLOUDFLARE.bat
echo.
echo  Keep MBT POS running (tunnel starts with the app).
echo.
pause
