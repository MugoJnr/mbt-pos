@echo off
REM eugenemugo@gmail.com profile via CDP-safe user-data-dir (Chrome blocks debugging on main User Data)
set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
set "UD=%LOCALAPPDATA%\MugoByte\chrome-eugene-cdp"
start "" "%CHROME%" --remote-debugging-port=9222 --remote-allow-origins=* --user-data-dir="%UD%" --profile-directory=Default --no-first-run --no-default-browser-check %*
