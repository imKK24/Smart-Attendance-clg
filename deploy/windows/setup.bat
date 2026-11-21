@echo off
REM Double-click to run setup.ps1 (PowerShell scripts are blocked from double-click by default).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
echo.
pause
