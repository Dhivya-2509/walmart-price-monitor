@echo off
set PYTHON=%USERPROFILE%\.code-puppy-venv\Scripts\python.exe
set SCRIPT_DIR=%~dp0

if not exist "%PYTHON%" (
    echo [ERROR] Python venv not found. Run install.bat first.
    pause
    exit /b 1
)

cd /d "%SCRIPT_DIR%"
echo Running Walmart Price Monitor...
echo Logs will appear below and in the logs\ folder.
echo.
"%PYTHON%" monitor.py
echo.
echo Done. Check logs\ folder for full output.
pause
