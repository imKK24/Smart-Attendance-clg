# ============================================================
#  AttendAI - one-time setup on the college PC (Windows 10/11)
#  Run:  double-click setup.bat   (or)
#        powershell -ExecutionPolicy Bypass -File deploy\windows\setup.ps1
#  Safe to run again: it only adds what's missing and rebuilds the app.
# ============================================================
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\common.ps1"

Step "1/8  Checking the programs AttendAI needs"
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Fail "Node.js is missing. Install the LTS version from https://nodejs.org and run this again." }
Say ("Node.js " + (node --version))
$py = Get-Python
if (-not $py) {
    $launcher = $null
    foreach ($v in @("3.12", "3.11", "3.13")) {
        try {
            $ErrorActionPreference = "Continue"
            & py "-$v" --version *> $null
            if ($LASTEXITCODE -eq 0) { $launcher = @("py", "-$v") }
        } catch { } finally { $ErrorActionPreference = "Stop" }
        if ($launcher) { break }
    }
    if (-not $launcher -and (Get-Command python -ErrorAction SilentlyContinue)) { $launcher = @("python") }
    if (-not $launcher) { Fail "Python is missing. Install Python 3.12 from https://python.org (tick 'Add to PATH') and run this again." }
    Say "Making the Python environment (backend\venv) ..."
    $exe = $launcher[0]; $rest = @($launcher | Select-Object -Skip 1) + @("-m", "venv", (Join-Path $Backend "venv"))
    & $exe @rest
    $py = Get-Python
    if (-not $py) { Fail "Couldn't make backend\venv." }
}
Say ("Python: " + (& $py --version))
$myDump = Find-MysqlBin
if ($myDump) { Say "MySQL tools: $myDump" } else { Say "mysqldump not found: nightly backups will be skipped until XAMPP's mysql\bin folder is found." "Yellow" }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Say "Git is not installed. Only needed for GitHub updates (https://git-scm.com)." "Yellow" }

Step "2/8  Installing the Python packages (a few minutes the first time)"
& $py -m pip install --upgrade pip --quiet
& $py -m pip install -r (Join-Path $Backend "requirements.txt") --quiet
if ($LASTEXITCODE -ne 0) { Fail "pip couldn't install requirements.txt (see the messages above)." }
& $py -m pip install face_recognition --no-deps --quiet

Step "3/8  Building the app screens (frontend)"
Push-Location $Frontend
try {
    npm ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { Fail "npm ci failed in frontend." }
    npm run build
    if ($LASTEXITCODE -ne 0) { Fail "The frontend build failed." }
} finally { Pop-Location }

Step "4/8  Installing the WhatsApp bridge"
Push-Location $Bridge
try {
    npm ci --omit=dev --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { Fail "npm ci failed in whatsapp-bridge." }
} finally { Pop-Location }

Step "5/8  Settings for going online (.env)"
Set-EnvValue "HOST" "127.0.0.1"          # only the tunnel reaches the server, never the open network
Set-EnvValue "BEHIND_TUNNEL" "1"
Say "HOST=127.0.0.1 and BEHIND_TUNNEL=1 saved in .env"
[Environment]::SetEnvironmentVariable("ATTENDAI_HOME", $Root, "User")

Step "6/8  Checking the database"
Push-Location $Backend
try {
    & $py -c "from models import create_tables; create_tables(); print('Database OK')"
    if ($LASTEXITCODE -ne 0) { Fail "Can't reach the database. Open the XAMPP Control Panel and Start MySQL, and check DATABASE_URL in .env." }
} finally { Pop-Location }

Step "7/8  Starting AttendAI by itself when you log in to Windows"
$psExe = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$start = New-ScheduledTaskAction -Execute $psExe -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$PSScriptRoot\start-attendai.ps1`""
$atLogon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$keepOn = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
          -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "AttendAI" -Action $start -Trigger $atLogon -Settings $keepOn `
    -Description "AttendAI server + WhatsApp bridge (deploy\windows\start-attendai.ps1)" -Force | Out-Null
Say "Task 'AttendAI' added (Task Scheduler)."

$backup = New-ScheduledTaskAction -Execute $psExe -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$PSScriptRoot\backup.ps1`""
$nightly = New-ScheduledTaskTrigger -Daily -At "9:00 PM"
Register-ScheduledTask -TaskName "AttendAI backup" -Action $backup -Trigger $nightly -Settings $keepOn `
    -Description "Nightly copy of the AttendAI database and photos (deploy\windows\backup.ps1)" -Force | Out-Null
Say "Task 'AttendAI backup' added: every day at 9 PM."

try {
    powercfg /change standby-timeout-ac 0 | Out-Null     # never sleep while plugged in
    powercfg /change hibernate-timeout-ac 0 | Out-Null
    Say "Sleep turned off while plugged in (the site goes offline when the PC sleeps)."
} catch { Say "Couldn't change sleep settings. Set 'Sleep: Never' in Settings > System > Power yourself." "Yellow" }

Step "8/8  Starting AttendAI now"
& "$PSScriptRoot\stop-attendai.ps1" -Quiet
Start-ScheduledTask -TaskName "AttendAI"
if (Wait-Healthy 120) {
    Say ""
    Say "AttendAI is running:  http://localhost:5000" "Green"
    Say "Next: put it online with  deploy\windows\tunnel-tailscale.bat" "Green"
} else {
    Fail "AttendAI didn't answer within 2 minutes. Look in the logs folder: logs\backend.err.log"
}
