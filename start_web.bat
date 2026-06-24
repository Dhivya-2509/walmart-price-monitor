@echo off
set PYTHON=%USERPROFILE%\.code-puppy-venv\Scripts\python.exe
set SCRIPT_DIR=%~dp0

if not exist "%PYTHON%" (
    echo [ERROR] Python venv not found. Run install.bat first.
    pause
    exit /b 1
)

cd /d "%SCRIPT_DIR%"
echo ============================================================
echo  Walmart Price Monitor - Web Dashboard
echo  Open in browser: http://localhost:5050
echo  Press Ctrl+C to stop
echo ============================================================
echo.
start "" "http://localhost:5050"
"%PYTHON%" webapp.py
