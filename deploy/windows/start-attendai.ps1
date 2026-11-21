# ============================================================
#  AttendAI - keeps everything running (started by the "AttendAI" task at logon)
#  Starts: the web server (backend\serve.py), the WhatsApp bridge, and the
#  GitHub updater (if set up). Restarts any of them that stops.
#  Logs: logs\*.log      Stop everything: deploy\windows\stop-attendai.bat
# ============================================================
$ErrorActionPreference = "Continue"
. "$PSScriptRoot\common.ps1"

$mutex = New-Object System.Threading.Mutex($false, "AttendAI-Supervisor")
if (-not $mutex.WaitOne(0)) { exit 0 }      # already running
New-Item -ItemType Directory -Force -Path $Logs | Out-Null
$flag = Join-Path $Root "restart.flag"
Remove-Item $flag -ErrorAction SilentlyContinue

function Note([string]$Text) {
    Add-Content -Path (Join-Path $Logs "supervisor.log") -Value ("{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Text)
}

function Start-Part($part) {
    foreach ($kind in @("log", "err.log")) {      # keep the previous run's log as .old
        $f = Join-Path $Logs "$($part.Name).$kind"
        if (Test-Path $f) { Move-Item $f "$f.old" -Force -ErrorAction SilentlyContinue }
    }
    $p = Start-Process -FilePath $part.Exe -ArgumentList $part.Args -WorkingDirectory $part.Dir -WindowStyle Hidden -PassThru `
         -RedirectStandardOutput (Join-Path $Logs "$($part.Name).log") -RedirectStandardError (Join-Path $Logs "$($part.Name).err.log")
    Note "started $($part.Name) (pid $($p.Id))"
    $part.Proc = $p
    $part.Started = Get-Date
}

function Stop-Part($part) {
    if ($part.Proc -and -not $part.Proc.HasExited) {
        & taskkill /PID $part.Proc.Id /T /F *> $null       # /T: also its child processes
        Note "stopped $($part.Name)"
    }
}

$parts = New-Object System.Collections.ArrayList
$py = Get-Python
if (-not $py) { Note "backend\venv missing: run setup.bat first"; exit 1 }
[void]$parts.Add(@{ Name = "backend"; Exe = $py; Args = "serve.py"; Dir = $Backend; Proc = $null; Restartable = $true })
if (Test-Path (Join-Path $Bridge "node_modules")) {
    $node = (Get-Command node -ErrorAction SilentlyContinue).Source
    if ($node) { [void]$parts.Add(@{ Name = "whatsapp"; Exe = $node; Args = "`"$(Join-Path $Bridge "index.js")`""; Dir = $Bridge; Proc = $null; Restartable = $true }) }
}
# GitHub automatic updates: the runner folder chosen in README-DEPLOY.md, part E.
$runner = [Environment]::GetEnvironmentVariable("ATTENDAI_RUNNER", "User")
if ($runner -and (Test-Path (Join-Path $runner "run.cmd"))) {
    [void]$parts.Add(@{ Name = "github-runner"; Exe = "cmd.exe"; Args = "/c run.cmd"; Dir = $runner; Proc = $null; Restartable = $false })
}

foreach ($part in $parts) { Start-Part $part }
while ($true) {
    Start-Sleep -Seconds 5
    if (Test-Path $flag) {                          # update.ps1 / tunnel scripts asked for a restart
        Remove-Item $flag -ErrorAction SilentlyContinue
        Note "restart requested"
        foreach ($part in $parts) { if ($part.Restartable) { Stop-Part $part; Start-Part $part } }
        continue
    }
    foreach ($part in $parts) {
        if ($part.Proc.HasExited) {
            Note "$($part.Name) stopped (exit code $($part.Proc.ExitCode)); starting it again"
            if (((Get-Date) - $part.Started).TotalSeconds -lt 30) { Start-Sleep -Seconds 20 }   # e.g. MySQL (XAMPP) still starting
            Start-Part $part
        }
    }
}
