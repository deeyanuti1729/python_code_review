@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    where py >nul 2>nul
    if errorlevel 1 (
        echo Python 3 was not found. Install Python 3.10 or newer and try again.
        pause
        exit /b 1
    )
)

echo Starting Python Code Review with your saved Gemini key.
start "Python Code Review server" powershell.exe -NoProfile -ExecutionPolicy Bypass -NoExit -File "%~dp0start_server.ps1" -UseSavedKey
echo.
echo The server window will open the website when startup succeeds.
echo Local link: http://127.0.0.1:8000/
echo Keep the server window open while using the website.
