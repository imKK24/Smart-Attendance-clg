# ============================================================
#  AttendAI online with Tailscale Funnel: a free fixed https address,
#  like https://attendai-pc.tail1234.ts.net, with no domain to buy.
#  Before this: install Tailscale and sign in (README-DEPLOY.md, part C).
# ============================================================
$ErrorActionPreference = "Continue"
. "$PSScriptRoot\common.ps1"

$ts = Find-Tailscale
if (-not $ts) { Fail "Tailscale isn't installed. Get it from https://tailscale.com/download/windows, sign in, then run this again." }

Step "1/3  Checking the Tailscale sign-in"
$status = (& $ts status --json) | Out-String | ConvertFrom-Json
if (-not $status -or $status.BackendState -ne "Running") {
    Fail "Tailscale isn't signed in. Click the Tailscale icon near the clock, choose 'Log in', then run this again."
}
$name = ($status.Self.DNSName).TrimEnd(".")
$url = "https://$name"
Say "This PC's address will be: $url"

Step "2/3  Opening AttendAI to the internet (port 5000 -> $url)"
Say "The FIRST time, Tailscale shows a link below (https://login.tailscale.com/...)." "Yellow"
Say "Open it (Ctrl+click), approve Funnel / HTTPS for this PC, and this window carries on by itself." "Yellow"
Say ""
# Not captured, so Tailscale's own message and link appear straight away.
& $ts funnel --bg 5000
if ($LASTEXITCODE -ne 0) { Fail "Tailscale couldn't turn on Funnel (see its message above). Approve the link, then run this again." }
& $ts funnel status

Step "3/3  Saving the address and restarting AttendAI"
Set-EnvValue "PUBLIC_URL" $url
Set-EnvValue "BEHIND_TUNNEL" "1"
Request-Restart
Start-Sleep -Seconds 8
if (Wait-Healthy 90) {
    Say ""
    Say "AttendAI is online:  $url" "Green"
    Say "Check it from a PHONE ON MOBILE DATA (not the college Wi-Fi):" "Green"
    Say "  1) open $url   -> the login page should appear" "Green"
    Say "  2) open $url/api/health   -> 'you' must be your phone's internet IP, NOT 127.0.0.1" "Green"
    Say "The address stays the same after restarts. Share it with teachers and parents." "Green"
} else {
    Fail "The server didn't come back. Look at logs\backend.err.log"
}
