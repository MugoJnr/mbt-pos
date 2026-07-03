@echo off
title MBT POS - GitHub Setup
color 0B
cd /d "%~dp0"

echo.
echo  ============================================================
echo    MBT POS - GitHub Setup (one-time)
echo    Repo: mugojnr/mbt-pos
echo  ============================================================
echo.

where gh >nul 2>&1
if errorlevel 1 (
    echo  Installing GitHub CLI...
    winget install --id GitHub.cli -e --accept-package-agreements --accept-source-agreements
)

echo  [1/4] Sign in to GitHub (browser will open)...
gh auth login -h github.com -p https -w
if errorlevel 1 (
    echo  [ERROR] GitHub login failed.
    pause & exit /b 1
)

echo.
echo  [2/4] Creating private repo mugojnr/mbt-pos...
gh repo create mugojnr/mbt-pos --private --source=. --remote=origin --description "MBT POS - MugoByte Technologies" --push
if errorlevel 1 (
    echo  [!] Repo may already exist — trying push only...
    git remote remove origin 2>nul
    git remote add origin https://github.com/mugojnr/mbt-pos.git
    git branch -M main
    git push -u origin main
)

echo.
echo  [3/4] Publishing release v2.2.0 with installer...
if not exist "dist\MBT_POS_Setup.exe" (
    echo  [!] dist\MBT_POS_Setup.exe not found — run BUILD.bat first.
    goto :done
)

gh release create v2.2.0 "dist\MBT_POS_Setup.exe" ^
  --title "MBT POS v2.2.0" ^
  --notes "Auto-update, unified Telegram hub, per-shop Cloudflare, stable licensing."

echo  [OK] Release published.

:done
echo.
echo  [4/4] Done!
echo  Repo:  https://github.com/mugojnr/mbt-pos
echo  Release: https://github.com/mugojnr/mbt-pos/releases/tag/v2.2.0
echo.
pause
