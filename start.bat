@echo off
cd /d "%~dp0"

rem if a MultiSpan server is already listening, just open the page
netstat -an | findstr ":8765" | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 (
    start "" http://127.0.0.1:8765
    exit /b 0
)

where python >nul 2>nul
if errorlevel 1 (
    py app.py
) else (
    python app.py
)
if errorlevel 1 (
    echo.
    echo [MultiSpan] Server exited with an error. Take a screenshot if you need help.
    pause
)
