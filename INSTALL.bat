@echo off
setlocal EnableDelayedExpansion
title MBT POS - Setup
cd /d "%~dp0"
color 0A
cls

echo.
echo  ============================================================
echo    MBT POS - First Time Setup
echo    MugoByte Technologies  ^|  mugobyte.com
echo  ============================================================
echo.

set "PY_DIR=C:\MBT_Build\_python311"
set "PY_EXE=%PY_DIR%\python.exe"
set "PY_URL=https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
set "PY_INST=C:\MBT_Build\py311_setup.exe"

if not exist "C:\MBT_Build" mkdir "C:\MBT_Build"

:: ════════════════════════════════════════════════════════════════
:: Python 3.11
:: ════════════════════════════════════════════════════════════════
if exist "%PY_EXE%" (
    for /f "tokens=2" %%v in ('"%PY_EXE%" --version 2^>^&1') do echo  [OK] Python %%v ready.
    goto :install_deps
)

echo  [!] Downloading Python 3.11 (~27 MB, one time only^)...

powershell -NoProfile -NonInteractive -Command ^
  "(New-Object Net.WebClient).DownloadFile('%PY_URL%', '%PY_INST%')"

if not exist "%PY_INST%" ( curl -L -o "%PY_INST%" "%PY_URL%" )

if not exist "%PY_INST%" (
    echo  [ERROR] Download failed. Check internet and try again.
    echo  Support: +254 112 863 252  ^|  admin@mugobyte.com
    pause & exit /b 1
)

echo  [OK] Installing Python 3.11 - a progress window will appear...
echo       Wait for it to complete, then this will continue automatically.
echo.

start /wait "" "%PY_INST%" /passive ^
    TargetDir="%PY_DIR%" ^
    Include_launcher=0 ^
    AssociateFiles=0 ^
    PrependPath=0 ^
    Shortcuts=0 ^
    Include_test=0 ^
    Include_doc=0 ^
    Include_pip=1

del "%PY_INST%" >nul 2>&1

if not exist "%PY_EXE%" (
    echo  [ERROR] Python installation failed.
    echo  Try right-clicking INSTALL.bat and choosing Run as Administrator.
    pause & exit /b 1
)

for /f "tokens=2" %%v in ('"%PY_EXE%" --version 2^>^&1') do echo  [OK] Python %%v installed.
echo.

:install_deps
echo  Installing MBT POS components (2-4 minutes first time^)...
echo.

"%PY_EXE%" -m pip install --upgrade pip --quiet 2>nul
"%PY_EXE%" -m pip install ^
    "PyQt5>=5.15" ^
    "PyQt5-sip>=12.11" ^
    "pyjwt>=2.8" ^
    "bcrypt>=4.0" ^
    "requests>=2.31" ^
    "openpyxl>=3.1" ^
    "pyserial>=3.5" ^
    "werkzeug>=2.3" ^
    "flask>=2.3" ^
    "flask-cors>=4.0" ^
    "click>=8.1" ^
    "cffi>=1.15" ^
    "certifi" ^
    "urllib3>=2.0" ^
    "charset-normalizer>=3.0" ^
    --quiet

if errorlevel 1 (
    echo  [ERROR] Installation failed. Check internet and try again.
    echo  Support: +254 112 863 252  ^|  admin@mugobyte.com
    pause & exit /b 1
)

echo.
echo  ============================================================
echo   [OK] Setup complete!
echo.
echo   To start MBT POS every day:
echo     Double-click  "RUN ME.bat"
echo  ============================================================
echo.
pause
