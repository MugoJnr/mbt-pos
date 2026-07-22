@echo off
setlocal EnableDelayedExpansion
title MBT POS - Build Web Dashboard
cd /d "%~dp0"

set "UI_DIR=%~dp0web\dashboard-ui"
set "PLATFORM_DIR=%~dp0web\mugobyte-platform"

if /I "%MBT_SKIP_WEB_REBUILD%"=="1" (
  if exist "%PLATFORM_DIR%\dist\index.html" (
    echo  [OK] Skipping web rebuild (MBT_SKIP_WEB_REBUILD=1^)
    exit /b 0
  )
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

:: Primary: MugoByte Platform SPA
if exist "%PLATFORM_DIR%\package.json" (
  echo  [1/2] Building mugobyte-platform...
  cd /d "%PLATFORM_DIR%"
  if exist "package-lock.json" (
    call npm ci
    if errorlevel 1 call npm install
  ) else (
    call npm install
  )
  if errorlevel 1 exit /b 1
  call npm run build
  if errorlevel 1 (
    echo  [ERROR] mugobyte-platform Vite build failed.
    exit /b 1
  )
  if not exist "dist\index.html" (
    echo  [ERROR] mugobyte-platform dist\index.html missing.
    exit /b 1
  )
  echo  [OK] Platform SPA: "!PLATFORM_DIR!\dist"
)

:: Legacy dashboard-ui (optional fallback)
if exist "%UI_DIR%\package.json" (
  echo  [2/2] Building dashboard-ui ^(legacy fallback^)...
  cd /d "%UI_DIR%"
  if exist "package-lock.json" (
    call npm ci
    if errorlevel 1 call npm install
  ) else (
    call npm install
  )
  if errorlevel 1 (
    echo  [!] dashboard-ui deps failed - continuing with platform SPA only.
  ) else (
    call npm run build
    if errorlevel 1 (
      echo  [!] dashboard-ui build failed - continuing with platform SPA only.
    ) else (
      echo  [OK] Legacy SPA: "!UI_DIR!\dist"
    )
  )
)

if not exist "%PLATFORM_DIR%\dist\index.html" if not exist "%UI_DIR%\dist\index.html" (
  echo  [ERROR] No web dist produced.
  exit /b 1
)

echo.
echo  [OK] Web dashboard ready for Flask / portal.mugobyte.com
echo.
exit /b 0
