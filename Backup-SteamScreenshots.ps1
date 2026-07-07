<#
.SYNOPSIS
    Backs up Steam screenshots into per-game folders with readable, chronologically sortable filenames.

.DESCRIPTION
    Scans the screenshot store of every Steam account on this machine, resolves appids to real game
    names (local app manifests first, Steam store API as a cached fallback), and copies screenshots
    into a destination folder organized by game. Filenames are converted from Steam's raw
    YYYYMMDDHHMMSS_N format to "YYYY-MM-DD HH.MM.SS - N" so that sorting by name equals sorting by
    capture time. Runs are incremental: files already backed up (matching name and size) are skipped.

.PARAMETER Destination
    Root folder for the backup. Created if it doesn't exist.
    Default: %USERPROFILE%\Pictures\Steam Screenshots

.EXAMPLE
    .\Backup-SteamScreenshots.ps1 -Destination "D:\Backups\Steam Screenshots"

.NOTES
    Requires Windows PowerShell 5.1+ (ships with Windows 10/11). No external dependencies.
#>
param(
    [string]$Destination = (Join-Path $env:USERPROFILE 'Pictures\Steam Screenshots')
)

$ErrorActionPreference = 'Stop'

# --- Locate Steam via registry ---
try {
    $steamPath = (Get-ItemProperty 'HKCU:\Software\Valve\Steam').SteamPath -replace '/', '\'
} catch {
    Write-Error "Steam not found in registry."; exit 1
}

# --- Build appid -> name map from installed games (all library folders) ---
$appNames = @{}
$libraries = @(Join-Path $steamPath 'steamapps')
$vdf = Join-Path $steamPath 'steamapps\libraryfolders.vdf'
if (Test-Path $vdf) {
    foreach ($m in [regex]::Matches((Get-Content $vdf -Raw), '"path"\s+"([^"]+)"')) {
        $p = Join-Path ($m.Groups[1].Value -replace '\\\\', '\') 'steamapps'
        if ((Test-Path $p) -and ($libraries -notcontains $p)) { $libraries += $p }
    }
}
foreach ($lib in $libraries) {
    foreach ($acf in Get-ChildItem $lib -Filter 'appmanifest_*.acf' -ErrorAction SilentlyContinue) {
        $raw  = Get-Content $acf.FullName -Raw
        $id   = [regex]::Match($raw, '"appid"\s+"(\d+)"').Groups[1].Value
        $name = [regex]::Match($raw, '"name"\s+"([^"]+)"').Groups[1].Value
        if ($id -and $name) { $appNames[$id] = $name }
    }
}

# --- Fallback: per-game store lookup for uninstalled games, cached persistently ---
$cacheDir      = Join-Path $env:LOCALAPPDATA 'SteamScreenshotBackup'
$nameCacheFile = Join-Path $cacheDir 'appnames.json'
$script:nameCache = @{}
if (Test-Path $nameCacheFile) {
    try {
        (Get-Content $nameCacheFile -Raw | ConvertFrom-Json).PSObject.Properties |
            ForEach-Object { $script:nameCache[$_.Name] = $_.Value }
    } catch { }
}

function Resolve-AppName([string]$appid) {
    if ($appNames.ContainsKey($appid))         { return $appNames[$appid] }
    if ($script:nameCache.ContainsKey($appid)) { return $script:nameCache[$appid] }
    $name = $null
    try {
        $r = Invoke-RestMethod "https://store.steampowered.com/api/appdetails?appids=$appid&filters=basic" -UseBasicParsing
        if ($r.$appid.success) { $name = $r.$appid.data.name }
        Start-Sleep -Milliseconds 300   # be polite to the store API
    } catch {
        Write-Warning "Name lookup failed for $appid : $($_.Exception.Message)"
    }
    if ($name) { $script:nameCache[$appid] = $name; return $name }
    return $null
}

function Get-SafeName([string]$name) {
    $clean = ($name -replace '[\\/:*?"<>|]', '').Trim(' .')
    if ([string]::IsNullOrWhiteSpace($clean)) { return $null }
    return $clean
}

function Convert-ScreenshotName([string]$fileName) {
    # 20260706210532_1.jpg -> "2026-07-06 21.05.32 - 1.jpg" (name sort = chronological)
    $m = [regex]::Match($fileName, '^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})_(\d+)(\.\w+)$')
    if (-not $m.Success) { return $fileName }   # unknown format -> keep as-is
    return "{0}-{1}-{2} {3}.{4}.{5} - {6}{7}" -f `
        $m.Groups[1].Value, $m.Groups[2].Value, $m.Groups[3].Value,
        $m.Groups[4].Value, $m.Groups[5].Value, $m.Groups[6].Value,
        [int]$m.Groups[7].Value, $m.Groups[8].Value
}

# --- Scan userdata and copy ---
$copied = 0; $skipped = 0; $games = 0
foreach ($user in Get-ChildItem (Join-Path $steamPath 'userdata') -Directory -ErrorAction SilentlyContinue) {
    $remote = Join-Path $user.FullName '760\remote'
    if (-not (Test-Path $remote)) { continue }

    foreach ($appDir in Get-ChildItem $remote -Directory) {
        $srcDir = Join-Path $appDir.FullName 'screenshots'
        if (-not (Test-Path $srcDir)) { continue }

        # -File without -Recurse naturally excludes the 'thumbnails' subfolder
        $files = @(Get-ChildItem $srcDir -File)
        if ($files.Count -eq 0) { continue }

        $name   = Resolve-AppName $appDir.Name
        $folder = if ($name) { Get-SafeName $name } else { $null }
        if (-not $folder) { $folder = "AppID_$($appDir.Name)" }

        $destDir = Join-Path $Destination $folder
        New-Item $destDir -ItemType Directory -Force | Out-Null
        $games++

        foreach ($f in $files) {
            $dest = Join-Path $destDir (Convert-ScreenshotName $f.Name)
            if ((Test-Path $dest) -and ((Get-Item $dest).Length -eq $f.Length)) { $skipped++; continue }
            Copy-Item $f.FullName $dest -Force
            $copied++
        }
    }
}

if ($script:nameCache.Count -gt 0) {
    New-Item $cacheDir -ItemType Directory -Force | Out-Null
    $script:nameCache | ConvertTo-Json | Set-Content $nameCacheFile
}
Write-Host "Done. $games games | $copied new screenshots copied | $skipped already backed up."