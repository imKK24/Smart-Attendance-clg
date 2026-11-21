@echo off
REM Double-click to run stop-attendai.ps1 (PowerShell scripts are blocked from double-click by default).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-attendai.ps1" %*
echo.
pause
