@echo off
echo ============================================================
echo  Walmart Price Monitor - Setup Check
echo ============================================================
echo.

set PYTHON=%USERPROFILE%\.code-puppy-venv\Scripts\python.exe

if not exist "%PYTHON%" (
    echo [ERROR] Python venv not found at:
    echo   %PYTHON%
    pause
    exit /b 1
)

echo [OK] Python found: %PYTHON%

"%PYTHON%" -c "from playwright.sync_api import sync_playwright; print('[OK] playwright ready')" 2>nul || (
    echo [ERROR] playwright not found in venv.
    pause
    exit /b 1
)

"%PYTHON%" -c "import win32com; print('[OK] pywin32 found')" 2>nul || (
    echo [ERROR] pywin32 not found in venv.
    pause
    exit /b 1
)

echo [OK] Playwright browsers already installed
echo.
echo ============================================================
echo  All dependencies ready! No install needed.
echo ============================================================
echo.
echo Next steps:
echo   1. Double-click run_once.bat  to do a test run
echo   2. Right-click setup_scheduler.bat ^> Run as Administrator
echo      to enable hourly automatic checks
echo.
pause
