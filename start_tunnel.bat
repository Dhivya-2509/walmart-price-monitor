@echo off
:: ============================================================
::  Walmart Price Monitor - Cloudflare Tunnel
::  Creates a permanent public URL for your team
::  Run this ALONGSIDE start_web.bat
:: ============================================================
set TUNNEL_EXE=%USERPROFILE%\cloudflared.exe
set DOWNLOAD_URL=https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe

echo.
echo ============================================================
echo  Walmart Price Monitor - Public URL Setup
echo ============================================================
echo.

:: Download cloudflared if not present
if not exist "%TUNNEL_EXE%" (
    echo Downloading Cloudflare Tunnel tool...
    powershell -Command "Invoke-WebRequest -Uri '%DOWNLOAD_URL%' -OutFile '%TUNNEL_EXE%'"
    if not exist "%TUNNEL_EXE%" (
        echo [ERROR] Download failed. Check your internet connection.
        pause
        exit /b 1
    )
    echo Download complete.
    echo.
)

echo Starting tunnel to http://localhost:5050 ...
echo.
echo ============================================================
echo  YOUR PUBLIC URL will appear below in a moment.
echo  Look for a line like:
echo    https://xxxxxxxx.trycloudflare.com
echo
echo  Share that URL with your team!
echo  They can open it from ANY device, anywhere.
echo.
echo  NOTE: Keep this window + start_web.bat BOTH open.
echo  Press Ctrl+C to stop sharing.
echo ============================================================
echo.

"%TUNNEL_EXE%" tunnel --url http://localhost:5050
pause
