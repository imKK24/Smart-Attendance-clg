@echo off
REM Double-click to run tunnel-cloudflare.ps1 (PowerShell scripts are blocked from double-click by default).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tunnel-cloudflare.ps1" %*
echo.
pause
