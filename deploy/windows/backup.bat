@echo off
REM Double-click to run backup.ps1 (PowerShell scripts are blocked from double-click by default).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0backup.ps1" %*
echo.
pause
