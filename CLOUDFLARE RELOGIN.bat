@echo off
title MBT POS — Cloudflare Re-Login
cd /d "%~dp0"
echo.
echo  Removes stale cert.pem and opens fresh Cloudflare login.
echo  Use the MugoByte account that owns mugobyte.com
echo.
call "SETUP CLOUDFLARE.bat" --relogin
