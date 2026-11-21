# ============================================================
#  LATER, when you buy a domain: move AttendAI from Tailscale to Cloudflare.
#  Example:  tunnel-cloudflare.bat -Token eyJhIjoi... -Url https://attendance.yourcollege.in
#  Get the token in the Cloudflare dashboard (README-DEPLOY.md, part F).
#  Run as Administrator (right-click -> Run as administrator): it installs a Windows service.
# ============================================================
param(
    [Parameter(Mandatory = $true)][string]$Token,
    [Parameter(Mandatory = $true)][string]$Url
)
$ErrorActionPreference = "Continue"
. "$PSScriptRoot\common.ps1"

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
         [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { Fail "Run this as Administrator (right-click the .bat file -> Run as administrator)." }
if ($Url -notmatch "^https://[a-z0-9.-]+$") { Fail "Url must look like https://attendance.yourcollege.in (no / at the end)." }

Step "1/4  Installing cloudflared"
$cf = Get-Command cloudflared -ErrorAction SilentlyContinue
if (-not $cf) {
    winget install --id Cloudflare.cloudflared -e --accept-source-agreements --accept-package-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
    $cf = Get-Command cloudflared -ErrorAction SilentlyContinue
    if (-not $cf) { Fail "cloudflared didn't install. Download it from https://github.com/cloudflare/cloudflared/releases and run this again." }
}

Step "2/4  Connecting this PC to your Cloudflare tunnel (starts with Windows)"
& $cf.Source service install $Token
if ($LASTEXITCODE -ne 0) { Say "If it says the service already exists, that's fine." "Yellow" }

Step "3/4  Switching off the Tailscale public address"
$ts = Find-Tailscale
if ($ts) { & $ts funnel reset 2>&1 | Out-Null; Say "Tailscale Funnel switched off (Tailscale itself can stay installed)." }

Step "4/4  Saving the new address and restarting AttendAI"
Set-EnvValue "PUBLIC_URL" $Url
Set-EnvValue "BEHIND_TUNNEL" "1"
Request-Restart
Start-Sleep -Seconds 8
if (Wait-Healthy 90) {
    Say "Done. AttendAI is now at $Url  (check $Url/api/health from a phone on mobile data)." "Green"
    Say "Tell teachers and parents the new address; the old ts.net one no longer works." "Green"
} else { Fail "The server didn't come back. Look at logs\backend.err.log" }
