@echo off
:: Hot-apply Python UI + backend fixes into Program Files and restart ? seconds, not a full build.
:: Never copies web/dashboard-ui/node_modules (dist assets only). Purges leftover node_modules under Program Files.
title MBT POS - Hot Apply
cd /d "%~dp0"
set "SRC=%~dp0"
set "DST=C:\Program Files\MugoByte\MBT POS\_internal"

echo.
echo  Hot-applying source into installed app...
echo  (Use full BUILD.bat only for customer Setup.exe / GitHub release)
echo.

taskkill /F /IM MBT_POS.exe >nul 2>&1
ping -n 3 127.0.0.1 >nul

powershell -NoProfile -Command "Start-Process powershell -Verb RunAs -Wait -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File','%~dp0_hot_apply_elev.ps1','-Src','%SRC%','-Dst','%DST%')"

if not exist "%DST%\desktop\tabs\sales_tab.py" (
  echo  [ERROR] Hot apply failed ? UAC cancelled or path missing.
  pause
  exit /b 1
)

if exist "%DST%\web\dashboard-ui\node_modules" (
  echo  [WARN] node_modules still present under Program Files ? should have been purged.
) else (
  echo  [OK] No dashboard-ui/node_modules in install ^(production-safe^).
)

findstr /C:"Access POS through web dashboard" "%DST%\desktop\main.py" >nul
if errorlevel 1 (
  echo  [WARN] Web dashboard access button not found after copy.
) else (
  echo  [OK] Access POS through web dashboard button present.
)

findstr /C:"provision_shop_tunnel_via_api" "%DST%\backend\cloudflare_setup.py" >nul
if errorlevel 1 (
  echo  [WARN] Cloudflare API auto-provision not found after copy.
) else (
  echo  [OK] Cloudflare API auto-provision present.
)

findstr /C:"sync_cloudflared_state" "%DST%\backend\cloudflare_setup.py" >nul
if errorlevel 1 (
  echo  [WARN] Cloudflare persistence fix not found after copy.
) else (
  echo  [OK] Cloudflare AppData persistence present.
)

findstr /C:"Vendor recovery" "%DST%\desktop\tabs\settings_tab.py" >nul
if errorlevel 1 (
  echo  [WARN] Settings Vendor recovery label not found after copy.
) else (
  echo  [OK] Settings demotes browser Re-login to Vendor recovery.
)

findstr /C:"_sales_theme_heavy" "%DST%\desktop\main.py" >nul
if errorlevel 1 (
  echo  [WARN] Expected deferred theme heavy path not found after copy.
) else (
  echo  [OK] Deferred sales theme heavy work present.
)
findstr /C:"_retint_prod_grid" "%DST%\desktop\tabs\sales_tab.py" >nul
if errorlevel 1 (
  echo  [WARN] Expected in-place product retint not found after copy.
) else (
  echo  [OK] In-place product card retint present.
)
findstr /C:"style_cat_combo" "%DST%\desktop\utils\pos_light_theme.py" >nul
if errorlevel 1 (
  echo  [WARN] Expected style_cat_combo not found after copy.
) else (
  echo  [OK] Category dark/light style helper present.
)

findstr /C:"dashboard-ui" "%DST%\web\web_routes.py" >nul
if errorlevel 1 (
  echo  [WARN] React SPA web_routes.py not found after copy.
) else (
  echo  [OK] web_routes.py serves React dashboard-ui/dist.
)
if exist "%DST%\web\dashboard-ui\dist\index.html" (
  echo  [OK] React dashboard-ui/dist present.
) else (
  echo  [WARN] React dashboard-ui/dist missing ? / will fall back to legacy dashboard.html.
)
findstr /C:"id=\"root\"" "%DST%\web\templates\dashboard.html" >nul
if errorlevel 1 (
  echo  [WARN] Frozen shim templates/dashboard.html is not React shell.
) else (
  echo  [OK] Frozen-compatible React shim in templates/dashboard.html.
)
if exist "%DST%\web\static\index-BT0Z8ols.js" (
  echo  [OK] React assets under web/static for frozen /static/ route.
) else (
  echo  [WARN] web/static React JS missing ? frozen install may still show legacy UI.
)

echo  Starting MBT POS...
start "" "C:\Program Files\MugoByte\MBT POS\MBT_POS.exe"
echo  Done ? Cloudflare backend + UI + React dashboard hot-applied.
ping -n 2 127.0.0.1 >nul
