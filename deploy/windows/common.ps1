# Shared helpers for the AttendAI Windows scripts. Not run on its own.
$Root     = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Backend  = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$Bridge   = Join-Path $Root "whatsapp-bridge"
$Logs     = Join-Path $Root "logs"
$EnvFile  = Join-Path $Root ".env"
$Utf8     = New-Object System.Text.UTF8Encoding $false

function Say([string]$Text, [string]$Color = "Gray") { Write-Host $Text -ForegroundColor $Color }
function Step([string]$Text) { Write-Host ""; Write-Host "== $Text" -ForegroundColor Cyan }
function Fail([string]$Text) { Write-Host ""; Write-Host "STOPPED: $Text" -ForegroundColor Red; exit 1 }

function Get-Python {
    foreach ($p in @((Join-Path $Backend "venv\Scripts\python.exe"), (Join-Path $Backend ".venv\Scripts\python.exe"))) {
        if (Test-Path $p) { return $p }
    }
    return $null
}

function Get-EnvValue([string]$Key, [string]$Default = "") {
    if (Test-Path $EnvFile) {
        foreach ($line in [IO.File]::ReadAllLines($EnvFile)) {
            if ($line -match "^\s*$Key\s*=\s*(.*)$") { return $Matches[1].Trim().Trim('"') }
        }
    }
    return $Default
}

function Set-EnvValue([string]$Key, [string]$Value) {
    $lines = New-Object System.Collections.Generic.List[string]
    $found = $false
    if (Test-Path $EnvFile) {
        foreach ($line in [IO.File]::ReadAllLines($EnvFile)) {
            if ($line -match "^\s*$Key\s*=") { $lines.Add("$Key=$Value"); $found = $true }
            else { $lines.Add($line) }
        }
    }
    if (-not $found) { $lines.Add("$Key=$Value") }
    [IO.File]::WriteAllLines($EnvFile, $lines, $Utf8)
}

function Find-PgBin([string]$Exe = "pg_dump.exe") {
    $cmd = Get-Command $Exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $hit = Get-ChildItem "C:\Program Files\PostgreSQL\*\bin\$Exe" -ErrorAction SilentlyContinue |
           Sort-Object FullName -Descending | Select-Object -First 1
    if ($hit) { return $hit.FullName }
    return $null
}

function Find-MysqlBin([string]$Exe = "mysqldump.exe") {
    # XAMPP keeps MySQL (MariaDB) in C:\xampp\mysql\bin
    $cmd = Get-Command $Exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($dir in @("C:\xampp\mysql\bin", "D:\xampp\mysql\bin", "C:\Program Files\MariaDB*\bin", "C:\Program Files\MySQL\MySQL Server*\bin")) {
        $hit = Get-ChildItem (Join-Path $dir $Exe) -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    return $null
}

function Find-Tailscale {
    $cmd = Get-Command tailscale -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($p in @("C:\Program Files\Tailscale\tailscale.exe", "C:\Program Files (x86)\Tailscale\tailscale.exe")) {
        if (Test-Path $p) { return $p }
    }
    return $null
}

function Request-Restart {
    # start-attendai.ps1 sees this file within a few seconds and restarts the server.
    Set-Content -Path (Join-Path $Root "restart.flag") -Value (Get-Date -Format s)
}

function Wait-Healthy([int]$Seconds = 90) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-RestMethod -Uri "http://127.0.0.1:5000/api/health" -TimeoutSec 5
            if ($r.success) { return $true }
        } catch { }
        Start-Sleep -Seconds 3
    }
    return $false
}
