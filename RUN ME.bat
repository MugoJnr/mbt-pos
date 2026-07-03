@echo off
setlocal EnableDelayedExpansion
title MBT POS
cd /d "%~dp0"

set "PY_EXE=C:\MBT_Build\_python311\python.exe"

if not exist "%PY_EXE%" (
    echo  First run - setting up MBT POS...
    echo.
    call "%~dp0INSTALL.bat"
)

if not exist "%PY_EXE%" (
    echo  Setup did not complete. Run INSTALL.bat manually.
    pause
    exit /b 1
)

start "" "%PY_EXE%" "%~dp0launcher.py"
