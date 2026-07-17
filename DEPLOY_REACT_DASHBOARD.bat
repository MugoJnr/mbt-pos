@echo off
:: Deploy React into installed POS even when PyInstaller PYZ still has legacy web_routes.
:: Strategy: replace templates/dashboard.html + web/static (served by frozen routes).
:: Also copies React dist + updated web_routes/app.py for when a rebuild lands.
title MBT POS - Deploy React Dashboard
cd /d "%~dp0"
set "SRC=%~dp0"
set "DST=C:\Program Files\MugoByte\MBT POS\_internal"
rem Purge accidental node_modules (never needed in Program Files)
if exist "%DST%\web\dashboard-ui\node_modules" rmdir /S /Q "%DST%\web\dashboard-ui\node_modules" >nul 2>&1

echo.
echo  Deploy React dashboard into Program Files (Admin required)
echo.

net session >nul 2>&1
if errorlevel 1 (
  echo  Requesting Administrator ??? click Yes on UAC...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

taskkill /F /IM MBT_POS.exe >nul 2>&1
ping -n 3 127.0.0.1 >nul

:: 1) Proper React package (for rebuilt / filesystem-loading installs)
copy /Y "%SRC%backend\app.py" "%DST%\backend\app.py" >nul
copy /Y "%SRC%web\web_routes.py" "%DST%\web\web_routes.py" >nul
if not exist "%DST%\web\dashboard-ui\dist" mkdir "%DST%\web\dashboard-ui\dist"
xcopy /E /I /Y "%SRC%web\dashboard-ui\dist\*" "%DST%\web\dashboard-ui\dist\" >nul

:: 2) Frozen-compatible shim: legacy / serves templates/dashboard.html
:: Prefer /assets/ paths (matches React dist + web_routes). Also copy into web/static
:: and backend/static for older Flask default-static layouts.
if not exist "%DST%\web\static" mkdir "%DST%\web\static"
if not exist "%DST%\backend\static" mkdir "%DST%\backend\static"
if not exist "%DST%\web\templates" mkdir "%DST%\web\templates"
copy /Y "%SRC%web\dashboard-ui\dist\assets\*" "%DST%\web\static\" >nul
copy /Y "%SRC%web\dashboard-ui\dist\assets\*" "%DST%\backend\static\" >nul
if not exist "%DST%\web\dashboard-ui\dist\assets" mkdir "%DST%\web\dashboard-ui\dist\assets"
copy /Y "%SRC%web\dashboard-ui\dist\assets\*" "%DST%\web\dashboard-ui\dist\assets\" >nul
copy /Y "%SRC%web\dashboard-ui\dist\index.html" "%DST%\web\templates\dashboard.html" >nul

if exist "%DST%\backend\__pycache__" rd /s /q "%DST%\backend\__pycache__"
if exist "%DST%\web\__pycache__" rd /s /q "%DST%\web\__pycache__"

findstr /C:"id=\"root\"" "%DST%\web\templates\dashboard.html" >nul
if errorlevel 1 (echo  [FAIL] dashboard.html shim missing #root) else (echo  [OK] templates/dashboard.html is React shell)
if exist "%DST%\web\static\index-BT0Z8ols.js" (echo  [OK] web/static React assets) else (echo  [WARN] expected JS asset name missing ??? check dist/assets)
if exist "%DST%\web\dashboard-ui\dist\index.html" (echo  [OK] dashboard-ui/dist present) else (echo  [WARN] dist missing)

echo  Starting MBT POS...
start "" "C:\Program Files\MugoByte\MBT POS\MBT_POS.exe"
echo  Done. Verify http://127.0.0.1:5050/ shows React (#root).
ping -n 2 127.0.0.1 >nul
