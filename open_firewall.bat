@echo off
echo Opening port 5050 for team access...
netsh advfirewall firewall delete rule name="Walmart Price Monitor 5050" >nul 2>&1
netsh advfirewall firewall add rule name="Walmart Price Monitor 5050" dir=in action=allow protocol=TCP localport=5050
if %ERRORLEVEL% EQU 0 (
    echo.
    echo [SUCCESS] Port 5050 is now open!
    echo Your team can access: http://10.172.42.109:5050
) else (
    echo.
    echo [FAILED] Could not open firewall port.
    echo Ask IT or use the Team link below instead.
)
echo.
pause
