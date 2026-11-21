@echo off
REM Starts AttendAI now (normally it starts by itself when you log in).
schtasks /Run /TN "AttendAI"
echo AttendAI is starting: open http://localhost:5000 in about 20 seconds.
pause
