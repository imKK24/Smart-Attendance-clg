# ============================================================
#  AttendAI nightly backup (the "AttendAI backup" task runs it at 9 PM).
#  Saves: both databases (college + Aakansha IT Hub) + student photos + course pictures + the secret key (needed to read
#  saved Gmail / camera passwords). Keeps the last 14 nights.
#  Copy the backups folder to a pen drive or another PC now and then:
#  a backup on the same disk doesn't survive a dead disk.
#  Folder: backups\  (or set ATTENDAI_BACKUP_DIR in .env, e.g. D:\AttendAI-backups)
# ============================================================
$ErrorActionPreference = "Continue"
. "$PSScriptRoot\common.ps1"

$dest = Get-EnvValue "ATTENDAI_BACKUP_DIR" (Join-Path $Root "backups")
New-Item -ItemType Directory -Force -Path $dest, $Logs | Out-Null
$stamp = Get-Date -Format "yyyy-MM-dd_HHmm"
$log = Join-Path $Logs "backup.log"
function Note([string]$t) { Add-Content $log ("{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm"), $t); Say $t }

# 1. Databases: the college ("attendai") and Aakansha IT Hub ("attendai_ithub")
$dbUrl = Get-EnvValue "DATABASE_URL" "mysql+pymysql://root:@localhost:3306/attendai"
$hubUrl = Get-EnvValue "ITHUB_DATABASE_URL" ""
$hubDb = $null
if ($dbUrl -match "^mysql(\+\w+)?://([^:/@]+)(:([^@]*))?@([^:/]+)(:(\d+))?/([^?]+)") {
    # MySQL / MariaDB (XAMPP)
    $user = $Matches[2]; $pass = [Uri]::UnescapeDataString($Matches[4]); $dbHost = $Matches[5]
    $port = if ($Matches[7]) { $Matches[7] } else { "3306" }; $db = $Matches[8]
    $hubDb = if ($hubUrl -match "/([^/?]+)(\?.*)?$") { $Matches[1] } else { "$($db)_ithub" }
    $myDump = Find-MysqlBin "mysqldump.exe"
    if ($myDump) {
        if ($pass) { $env:MYSQL_PWD = $pass }
        foreach ($pair in @(@("college", $db), @("ithub", $hubDb))) {
            $file = Join-Path $dest "attendai-$($pair[0])-db-$stamp.sql"
            & $myDump -h $dbHost -P $port -u $user --single-transaction --default-character-set=utf8mb4 "--result-file=$file" $pair[1]
            if ($LASTEXITCODE -eq 0) { Note "$($pair[0]) database saved: $file" }
            else { Note "$($pair[0].ToUpper()) DATABASE BACKUP FAILED (mysqldump exit $LASTEXITCODE)" }
        }
        Remove-Item Env:MYSQL_PWD -ErrorAction SilentlyContinue
    } else { Note "mysqldump.exe not found (XAMPP\mysql\bin): databases not saved" }
    $pgDump = $null
} elseif ($dbUrl -match "^postgresql(\+\w+)?://([^:/@]+)(:([^@]*))?@([^:/]+)(:(\d+))?/([^?]+)") {
    $pgDump = Find-PgBin "pg_dump.exe"
    $user = $Matches[2]; $pass = [Uri]::UnescapeDataString($Matches[4]); $dbHost = $Matches[5]
    $port = if ($Matches[7]) { $Matches[7] } else { "5432" }; $db = $Matches[8]
} else { Note "DATABASE_URL not understood; databases skipped"; $pgDump = $null }
if (-not $hubDb) { $hubDb = if ($hubUrl -match "/([^/?]+)(\?.*)?$") { $Matches[1] } else { "$($db)_ithub" } }
if ($pgDump) {
    $env:PGPASSWORD = $pass
    foreach ($pair in @(@("college", $db), @("ithub", $hubDb))) {
        $file = Join-Path $dest "attendai-$($pair[0])-db-$stamp.dump"
        & $pgDump -h $dbHost -p $port -U $user -F c -f $file $pair[1]
        if ($LASTEXITCODE -eq 0) { Note "$($pair[0]) database saved: $file" }
        else { Note "$($pair[0].ToUpper()) DATABASE BACKUP FAILED (pg_dump exit $LASTEXITCODE)" }
    }
    Remove-Item Env:PGPASSWORD
} elseif ($dbUrl -match "^postgresql") { Note "pg_dump.exe not found: databases not saved" }

# 2. Photos and the secret key
$folders = @("known_faces", "class_photos", "course_images", "data") | ForEach-Object { Join-Path $Backend $_ } | Where-Object { Test-Path $_ }
if ($folders) {
    $zip = Join-Path $dest "attendai-files-$stamp.zip"
    Compress-Archive -Path $folders -DestinationPath $zip -Force
    Note "photos + key saved: $zip"
}

# 3. Keep the newest 14 of each kind
foreach ($pattern in @("attendai-college-db-*.sql", "attendai-ithub-db-*.sql", "attendai-college-db-*.dump", "attendai-ithub-db-*.dump", "attendai-db-*.dump", "attendai-files-*.zip")) {
    Get-ChildItem $dest -Filter $pattern | Sort-Object LastWriteTime -Descending | Select-Object -Skip 14 |
        ForEach-Object { Remove-Item $_.FullName; Note "old backup removed: $($_.Name)" }
}
