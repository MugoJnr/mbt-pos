@echo off
title MBT POS - Re-queue Portal analytics (full)
cd /d "%~dp0"
echo.
echo  Close MBT POS first.
echo  This clears the analytics checkpoint and re-opens the sync queue.
echo  Sales, products, license and identity are not changed.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0requeue_analytics_backfill.ps1"
echo.
pause
