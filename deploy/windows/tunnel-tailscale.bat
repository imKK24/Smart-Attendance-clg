@echo off
REM Double-click to run tunnel-tailscale.ps1 (PowerShell scripts are blocked from double-click by default).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tunnel-tailscale.ps1" %*
echo.
pause
