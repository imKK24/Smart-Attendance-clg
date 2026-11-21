# ============================================================
#  Called by GitHub (the self-hosted runner) after all tests pass:
#  copies the new code into the AttendAI folder, installs packages,
#  rebuilds the app and restarts the server. Student data, .env, photos,
#  backups and the WhatsApp login are never touched.
#  By hand:  powershell -ExecutionPolicy Bypass -File deploy\windows\update.ps1 -Source C:\path\to\new\code
# ============================================================
param([Parameter(Mandatory = $true)][string]$Source)
$ErrorActionPreference = "Continue"
. "$PSScriptRoot\common.ps1"

# The live install (set by setup.ps1), not the runner's work folder.
$home_ = [Environment]::GetEnvironmentVariable("ATTENDAI_HOME", "User")
if (-not $home_) { $home_ = $env:ATTENDAI_HOME }
if (-not $home_ -or -not (Test-Path (Join-Path $home_ "backend\serve.py"))) { Fail "ATTENDAI_HOME isn't set. Run setup.bat on this PC first." }
$Source = (Resolve-Path $Source).Path
Say "Updating $home_ from $Source"

Step "1/4  Copying the new code"
# /E = all folders. No /MIR: nothing in the install is ever deleted.
& robocopy $Source $home_ /E /R:2 /W:2 /NFL /NDL /NJH /NP `
    /XD .git .github node_modules venv .venv dist __pycache__ .pytest_cache `
    /XF .env restart.flag
if ($LASTEXITCODE -ge 8) { Fail "Copying failed (robocopy code $LASTEXITCODE)." }

$py = Join-Path $home_ "backend\venv\Scripts\python.exe"
Step "2/4  Python packages"
& $py -m pip install -r (Join-Path $home_ "backend\requirements.txt") --quiet --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { Fail "pip install failed." }

Step "3/4  Rebuilding the app screens"
Push-Location (Join-Path $home_ "frontend")
npm ci --no-audit --no-fund --loglevel=error
if ($LASTEXITCODE -ne 0) { Pop-Location; Fail "npm ci failed (frontend)." }
npm run build
if ($LASTEXITCODE -ne 0) { Pop-Location; Fail "Frontend build failed." }
Pop-Location
Push-Location (Join-Path $home_ "whatsapp-bridge")
npm ci --omit=dev --no-audit --no-fund --loglevel=error
Pop-Location

Step "4/4  Restarting AttendAI"
Set-Content -Path (Join-Path $home_ "restart.flag") -Value (Get-Date -Format s)
Start-Sleep -Seconds 10
if (Wait-Healthy 120) { Say "Update finished. AttendAI is running the new version." "Green" }
else { Fail "AttendAI didn't come back after the update. Check logs\backend.err.log on the PC." }
