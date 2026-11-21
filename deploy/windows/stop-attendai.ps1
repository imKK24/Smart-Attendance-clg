# Stops AttendAI (server, WhatsApp bridge, updater) until the next logon or setup.
param([switch]$Quiet)
$ErrorActionPreference = "Continue"
. "$PSScriptRoot\common.ps1"
Stop-ScheduledTask -TaskName "AttendAI" -ErrorAction SilentlyContinue
$mine = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and (
        $_.CommandLine -like "*start-attendai.ps1*" -or
        ($_.Name -eq "python.exe" -and $_.CommandLine -like "*serve.py*") -or
        ($_.Name -eq "node.exe" -and $_.CommandLine -like "*whatsapp-bridge*index.js*") -or
        ($_.Name -eq "Runner.Listener.exe"))
}
foreach ($p in $mine) {
    if ($p.ProcessId -ne $PID) { & taskkill /PID $p.ProcessId /T /F *> $null }
}
if (-not $Quiet) { Say "AttendAI stopped. Start it again with start-attendai.bat or by logging in again." "Green" }
