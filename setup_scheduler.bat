@echo off
:: ============================================================
::  Walmart Price Monitor - Windows Task Scheduler Setup
::  Double-click to run (no admin needed).
:: ============================================================
echo.
echo ============================================================
echo  Setting up Windows Task Scheduler (hourly price checks)
echo ============================================================
echo.

set PYTHON=%USERPROFILE%\.code-puppy-venv\Scripts\python.exe
set SCRIPT_DIR=%~dp0
set MONITOR_SCRIPT=%SCRIPT_DIR%monitor.py

if not exist "%PYTHON%" (
    echo [ERROR] Python venv not found at %PYTHON%
    echo Run install.bat first.
    pause
    exit /b 1
)

echo Python  : %PYTHON%
echo Script  : %MONITOR_SCRIPT%
echo Schedule: Every 1 hour
echo.

:: Remove old task if exists
schtasks /delete /tn "WalmartCompetitivePriceMonitor" /f >nul 2>&1

:: Create hourly task running as current user (no admin needed)
schtasks /create ^
  /tn "WalmartCompetitivePriceMonitor" ^
  /tr "\"%PYTHON%\" \"%MONITOR_SCRIPT%\"" ^
  /sc HOURLY /mo 1 ^
  /ru "%USERDOMAIN%\%USERNAME%" ^
  /f

if %ERRORLEVEL% EQU 0 (
    echo.
    echo [SUCCESS] Task registered!
    echo   Name    : WalmartCompetitivePriceMonitor
    echo   Trigger : Every hour
    echo   Runs as : %USERDOMAIN%\%USERNAME%
    echo.
    echo View in Task Scheduler: taskschd.msc
    echo Run once now to test:
    schtasks /run /tn "WalmartCompetitivePriceMonitor"
    echo.
) else (
    echo.
    echo [ERROR] Could not create scheduled task.
    echo Instead: just keep start_web.bat running — it auto-checks every hour.
)

echo.
pause
