@echo off
setlocal EnableDelayedExpansion
title MBT POS - Build Web Dashboard
cd /d "%~dp0"

set "UI_DIR=%~dp0web\dashboard-ui"

if /I "%MBT_SKIP_WEB_REBUILD%"=="1" (
  if exist "%UI_DIR%\dist\index.html" (
    echo  [OK] Skipping web rebuild (MBT_SKIP_WEB_REBUILD=1^)
    exit /b 0
  )
)

echo.
echo  ============================================================
echo    MBT POS - Web Dashboard Build
echo  ============================================================
echo.

where npm >nul 2>&1
if errorlevel 1 (
  echo  [ERROR] npm not found. Install Node.js LTS, then retry.
  exit /b 1
)

if not exist "%UI_DIR%\package.json" (
  echo  [ERROR] Missing %UI_DIR%\package.json
  exit /b 1
)

cd /d "%UI_DIR%"

if exist "package-lock.json" (
  echo  [1/2] npm ci...
  call npm ci
  if errorlevel 1 (
    echo  [!] npm ci failed — falling back to npm install...
    call npm install
    if errorlevel 1 exit /b 1
  )
) else (
  echo  [1/2] npm install...
  call npm install
  if errorlevel 1 exit /b 1
)

echo  [2/2] npm run build...
call npm run build
if errorlevel 1 (
  echo  [ERROR] Vite build failed.
  exit /b 1
)

if not exist "dist\index.html" (
  echo  [ERROR] dist\index.html was not produced.
  exit /b 1
)

echo.
echo  [OK] Web dashboard built:
echo       %UI_DIR%\dist
echo  Flask serves it at http://127.0.0.1:5050/
echo.
exit /b 0
