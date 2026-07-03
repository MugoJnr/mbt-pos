@echo off
setlocal EnableDelayedExpansion
title MBT POS - Build
color 0A
cls

echo.
echo  ============================================================
echo    MBT POS - Build System
echo    MugoByte Technologies
echo  ============================================================
echo.

cd /d "%~dp0"
set "SOURCE_DIR=%~dp0"
set "PY_DIR=C:\MBT_Build\_python311"
set "PY_EXE=%PY_DIR%\python.exe"
set "PY_URL=https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
set "PY_INST=C:\MBT_Build\py311_setup.exe"
set "PY_LOG=C:\MBT_Build\py_install.log"

if not exist "C:\MBT_Build" mkdir "C:\MBT_Build"

:: ════════════════════════════════════════════════════════════════
:: STEP 1 — Python 3.11
:: ════════════════════════════════════════════════════════════════
echo  [1/5] Checking for Python 3.11...

if exist "%PY_EXE%" (
    for /f "tokens=2" %%v in ('"%PY_EXE%" --version 2^>^&1') do echo  [OK] Python %%v ready.
    goto :deps
)

:: Delete the target folder if it exists but is incomplete
:: (Python installer fails if folder exists but is empty/broken)
if exist "%PY_DIR%" (
    echo  [!] Removing incomplete _python311 folder...
    rd /s /q "%PY_DIR%"
)

echo  [!] Downloading Python 3.11...

powershell -NoProfile -NonInteractive -Command ^
  "(New-Object Net.WebClient).DownloadFile('%PY_URL%', '%PY_INST%')"

if not exist "%PY_INST%" (
    curl -L -o "%PY_INST%" "%PY_URL%"
)
if not exist "%PY_INST%" (
    echo  [ERROR] Download failed. Check internet.
    pause & exit /b 1
)

echo  [OK] Installing Python 3.11...
echo  (A progress window will appear - wait for it to close)
echo.

:: Run installer and log every detail
start /wait "" "%PY_INST%" /passive ^
    TargetDir="%PY_DIR%" ^
    Include_launcher=0 ^
    AssociateFiles=0 ^
    PrependPath=0 ^
    Shortcuts=0 ^
    Include_test=0 ^
    Include_doc=0 ^
    Include_pip=1 ^
    /log "%PY_LOG%"

set PY_INST_CODE=!errorlevel!
echo  Installer exit code: !PY_INST_CODE!

del "%PY_INST%" >nul 2>&1

if not exist "%PY_EXE%" (
    echo.
    echo  [!] Standard install failed (code !PY_INST_CODE!^).
    echo      Trying alternative method...
    echo.

    :: Alternative: use the embeddable zip instead
    set "PY_ZIP_URL=https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip"
    set "PY_ZIP=C:\MBT_Build\py311_embed.zip"
    set "PIP_URL=https://bootstrap.pypa.io/get-pip.py"
    set "PIP_SCRIPT=C:\MBT_Build\get-pip.py"

    echo  Downloading Python 3.11 embeddable package...
    powershell -NoProfile -NonInteractive -Command ^
      "(New-Object Net.WebClient).DownloadFile('!PY_ZIP_URL!', '!PY_ZIP!')"

    if not exist "!PY_ZIP!" (
        echo  [ERROR] Alternative download also failed. Check internet.
        pause & exit /b 1
    )

    :: Extract the zip
    if not exist "%PY_DIR%" mkdir "%PY_DIR%"
    powershell -NoProfile -NonInteractive -Command ^
      "Expand-Archive -Path '!PY_ZIP!' -DestinationPath '%PY_DIR%' -Force"
    del "!PY_ZIP!" >nul 2>&1

    :: Enable pip for the embeddable build
    :: Edit python311._pth to remove the comment on import site
    powershell -NoProfile -NonInteractive -Command ^
      "(Get-Content '%PY_DIR%\python311._pth') -replace '#import site','import site' | Set-Content '%PY_DIR%\python311._pth'"

    :: Download and run get-pip
    echo  Installing pip...
    powershell -NoProfile -NonInteractive -Command ^
      "(New-Object Net.WebClient).DownloadFile('!PIP_URL!', '!PIP_SCRIPT!')"
    "%PY_EXE%" "!PIP_SCRIPT!" --quiet
    del "!PIP_SCRIPT!" >nul 2>&1
)

if not exist "%PY_EXE%" (
    echo.
    echo  [ERROR] Both install methods failed.
    echo.
    echo  Please install Python 3.11 manually:
    echo  1. Go to: https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe
    echo  2. Run installer, tick "Add Python to PATH"
    echo  3. Come back and run BUILD.bat again
    echo.
    if exist "%PY_LOG%" (
        echo  Install log saved to: %PY_LOG%
        echo  First 20 lines:
        powershell -Command "Get-Content '%PY_LOG%' -TotalCount 20"
    )
    pause & exit /b 1
)

for /f "tokens=2" %%v in ('"%PY_EXE%" --version 2^>^&1') do echo  [OK] Python %%v ready.

:deps
echo.

:: ════════════════════════════════════════════════════════════════
:: STEP 2 — Dependencies
:: ════════════════════════════════════════════════════════════════
echo  [2/5] Installing dependencies (2-5 minutes^)...

"%PY_EXE%" -m pip install --upgrade pip --quiet 2>nul
"%PY_EXE%" -m pip install ^
    "pyinstaller>=6.0,<7.0" ^
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
    "flask-sock>=0.7" ^
    "click>=8.1" ^
    "cffi>=1.15" ^
    "certifi" ^
    "urllib3>=2.0" ^
    "charset-normalizer>=3.0" ^
    --quiet

if errorlevel 1 (
    echo  [ERROR] Dependency install failed. Check internet and try again.
    pause & exit /b 1
)
echo  [OK] Dependencies ready.
echo.

:: ════════════════════════════════════════════════════════════════
:: STEP 2b — cloudflared (bundled inside MBT_POS.exe)
:: ════════════════════════════════════════════════════════════════
echo  [2b/5] Bundling cloudflared tunnel client...
if not exist "tools" mkdir "tools"
if not exist "tools\cloudflared.exe" (
    echo        Downloading cloudflared-windows-amd64.exe...
    powershell -NoProfile -NonInteractive -Command ^
      "Invoke-WebRequest -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile 'tools\cloudflared.exe'"
    if not exist "tools\cloudflared.exe" (
        echo  [ERROR] cloudflared download failed. Check internet.
        pause & exit /b 1
    )
)
echo  [OK] tools\cloudflared.exe ready.
echo.

:: ════════════════════════════════════════════════════════════════
:: STEP 2c — Verify Telegram + config ship inside installer
:: ════════════════════════════════════════════════════════════════
echo  [2c/5] Verifying Telegram bot and config folder...
cd /d "%SOURCE_DIR%"
"%PY_EXE%" -c "import sys; sys.path.insert(0,'.'); from config.deploy import verify_installer_bundle; ok,msg=verify_installer_bundle(); print('  [OK] Telegram',msg) if ok else sys.exit(msg)"
if errorlevel 1 (
    echo  [ERROR] Installer bundle check failed.
    echo  Ensure config\deploy.py exists and has telegram_bot_token set.
    pause & exit /b 1
)
echo.

:: ════════════════════════════════════════════════════════════════
:: STEP 3 — PyInstaller
:: ════════════════════════════════════════════════════════════════
echo  [3/5] Building MBT_POS.exe (5-10 minutes^)...
echo        Do not close this window.
echo.

cd /d "%SOURCE_DIR%"
taskkill /F /IM MBT_POS.exe >nul 2>&1
if exist build rd /s /q build
if exist dist  rd /s /q dist

"%PY_EXE%" -m PyInstaller --clean mbt_pos.spec

if errorlevel 1 (
    echo.
    echo  [ERROR] PyInstaller failed. Read the error above.
    pause & exit /b 1
)
if not exist "dist\MBT_POS.exe" (
    echo  [ERROR] dist\MBT_POS.exe not created.
    pause & exit /b 1
)
echo  [OK] dist\MBT_POS.exe ready.
echo.

:: ════════════════════════════════════════════════════════════════
:: STEP 4 — NSIS
:: ════════════════════════════════════════════════════════════════
echo  [4/5] Building installer...
set "NSIS_CMD="
if exist "C:\Program Files (x86)\NSIS\makensis.exe" set "NSIS_CMD=C:\Program Files (x86)\NSIS\makensis.exe"
if exist "C:\Program Files\NSIS\makensis.exe"       set "NSIS_CMD=C:\Program Files\NSIS\makensis.exe"
if "!NSIS_CMD!"=="" ( makensis /VERSION >nul 2>&1 && set "NSIS_CMD=makensis" )

if "!NSIS_CMD!"=="" (
    echo  [!] Downloading NSIS...
    set "NSI_URL=https://downloads.sourceforge.net/project/nsis/NSIS%%203/3.10/nsis-3.10-setup.exe"
    set "NSI_TMP=C:\MBT_Build\nsis_setup.exe"
    powershell -NoProfile -NonInteractive -Command ^
      "(New-Object Net.WebClient).DownloadFile('!NSI_URL!', '!NSI_TMP!')"
    if exist "!NSI_TMP!" (
        start /wait "" "!NSI_TMP!" /S
        del "!NSI_TMP!" >nul 2>&1
        if exist "C:\Program Files (x86)\NSIS\makensis.exe" set "NSIS_CMD=C:\Program Files (x86)\NSIS\makensis.exe"
    )
)

if not "!NSIS_CMD!"=="" (
    "!NSIS_CMD!" installer.nsi
    if not errorlevel 1 ( echo  [OK] dist\MBT_POS_Setup.exe ready.
    ) else ( echo  [!] NSIS failed. Use dist\MBT_POS.exe directly. )
) else (
    echo  [!] NSIS unavailable. Use dist\MBT_POS.exe directly.
)
echo.

:: ════════════════════════════════════════════════════════════════
:: STEP 5 — Done
:: ════════════════════════════════════════════════════════════════
echo  [5/5] Done!
echo.
echo  ============================================================
if exist "dist\MBT_POS_Setup.exe" (
    for %%F in ("dist\MBT_POS_Setup.exe") do (
        set /a MB=%%~zF/1048576
        echo   INSTALLER : dist\MBT_POS_Setup.exe  [!MB! MB]
        echo   Give to customers - they double-click and it installs.
    )
    echo.
)
if exist "dist\MBT_POS.exe" (
    for %%F in ("dist\MBT_POS.exe") do (
        set /a MB=%%~zF/1048576
        echo   RAW EXE   : dist\MBT_POS.exe  [!MB! MB]
        echo   Fully portable - runs on any Windows 10/11 PC.
    )
)
echo  ============================================================
echo.
pause
