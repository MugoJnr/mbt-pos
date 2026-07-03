@echo off
title MBT POS — Cloudflare Diagnostics
cd /d "%~dp0"
set "PY=C:\MBT_Build\_python311\python.exe"
if not exist "%PY%" set "PY=python"
echo.
echo  MBT POS — Cloudflare / Web Dashboard Diagnostics
echo  ==================================================
echo.
"%PY%" -c "import sys; sys.path.insert(0,r'%~dp0.'); from backend.cloudflare_setup import cli_main; import sys; sys.argv=['','--diagnose']; cli_main()"
echo.
pause
