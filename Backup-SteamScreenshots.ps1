<#
.SYNOPSIS
    Backs up Steam screenshots into per-game folders with readable, chronologically sortable filenames.

.DESCRIPTION
    Script counterpart of the Steam Screenshot Backup tray app; both produce the same
    layout and share the same game-name cache, so they can be mixed freely.

    Sources:
      - Standard screenshots: Steam's compressed library copies under
        userdata\<id>\760\remote\<appid>\screenshots
      - High-resolution screenshots: the folder(s) configured by Steam's
        "Save an external copy of my screenshots" option (read from localconfig.vdf)

    Layout:  <Destination>\<Standard|High Resolution>\<template>\<file>
    Names are converted from Steam's raw formats to "YYYY-MM-DD HH.MM.SS" so sorting
    by name equals sorting by capture time. Runs are incremental; files already
    backed up are skipped.

.PARAMETER Destination
    Root folder for the backup. Created if it doesn't exist.
    Default: %USERPROFILE%\Pictures\Steam Screenshots

.PARAMETER Types
    Which screenshot types to back up: Standard, HighRes, or Both. Default: Both.

.PARAMETER FolderTemplate
    Folder layout inside each type folder. Tokens: {game} {yyyy} {MM} {dd}
    Default: {game}

.EXAMPLE
    .\Backup-SteamScreenshots.ps1 -Destination "D:\Backups\Steam Screenshots" -Types Both

.NOTES
    Requires Windows PowerShell 5.1+ (ships with Windows 10/11). No external dependencies.
#>
param(
    [string]$Destination = (Join-Path $env:USERPROFILE 'Pictures\Steam Screenshots'),
    [ValidateSet('Standard', 'HighRes', 'Both')]
    [string]$Types = 'Both',
    [string]$FolderTemplate = '{game}'
)

$ErrorActionPreference = 'Stop'
$StandardFolder = 'Standard'
$HighResFolder  = 'High Resolution'

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
    foreach ($m in [regex]::Matches([System.IO.File]::ReadAllText($vdf), '"path"\s+"([^"]+)"')) {
        $p = Join-Path ($m.Groups[1].Value -replace '\\\\', '\') 'steamapps'
        if ((Test-Path $p) -and ($libraries -notcontains $p)) { $libraries += $p }
    }
}
foreach ($lib in $libraries) {
    foreach ($acf in Get-ChildItem $lib -Filter 'appmanifest_*.acf' -ErrorAction SilentlyContinue) {
        $raw  = [System.IO.File]::ReadAllText($acf.FullName)   # Steam files are UTF-8
        $id   = [regex]::Match($raw, '"appid"\s+"(\d+)"').Groups[1].Value
        $name = [regex]::Match($raw, '"name"\s+"([^"]+)"').Groups[1].Value
        if ($id -and $name) { $appNames[$id] = $name }
    }
}

# --- Persistent name cache, shared with the tray app ---
$cacheDir      = Join-Path $env:LOCALAPPDATA 'SteamScreenshotBackup'
$nameCacheFile = Join-Path $cacheDir 'appnames.json'
$script:nameCache = @{}
$script:failedLookups = @{}
if (Test-Path $nameCacheFile) {
    try {
        # The cache is UTF-8 (shared with the tray app); never read it with the ANSI default.
        ([System.IO.File]::ReadAllText($nameCacheFile) | ConvertFrom-Json).PSObject.Properties |
            ForEach-Object {
                if ($_.Value -notmatch [string][char]0xFFFD) { $script:nameCache[$_.Name] = $_.Value }
            }
    } catch { }
}

# --- Non-Steam shortcut names from each account's binary shortcuts.vdf ---
$script:shortcutNames = @{}
foreach ($sv in Get-ChildItem (Join-Path $steamPath 'userdata') -Recurse -Filter 'shortcuts.vdf' -ErrorAction SilentlyContinue) {
    try {
        $bytes = [System.IO.File]::ReadAllBytes($sv.FullName)
        $text  = [System.Text.Encoding]::GetEncoding(28591).GetString($bytes)   # byte-preserving
        $appidKey = [string][char]2 + 'appid' + [string][char]0
        $nameKey  = [string][char]1 + 'appname' + [string][char]0
        $pos = 0
        while (($pos = $text.IndexOf($appidKey, $pos)) -ge 0) {
            $idOff = $pos + $appidKey.Length
            if ($idOff + 4 -gt $bytes.Length) { break }
            $appid = [BitConverter]::ToUInt32($bytes, $idOff)
            $npos = $text.IndexOf($nameKey, $idOff)
            if ($npos -ge 0) {
                $start = $npos + $nameKey.Length
                $end = $text.IndexOf([string][char]0, $start)
                if ($end -gt $start) {
                    $nameBytes = $bytes[$start..($end - 1)]
                    $script:shortcutNames["$appid"] = [System.Text.Encoding]::UTF8.GetString($nameBytes)
                }
            }
            $pos = $idOff
        }
    } catch { }
}

function Resolve-AppName([string]$appid) {
    if ($appNames.ContainsKey($appid))         { return $appNames[$appid] }
    if ($script:nameCache.ContainsKey($appid)) { return $script:nameCache[$appid] }
    if ($script:failedLookups.ContainsKey($appid)) { return $null }

    # Non-Steam shortcut games: huge synthetic ids; never ask the store API.
    if ([uint64]$appid -gt [int]::MaxValue) {
        $name = $script:shortcutNames[$appid]
        if (-not $name) { $name = $script:shortcutNames["$([uint64]$appid -shr 32)"] }
        if ($name) { $script:nameCache[$appid] = $name; return $name }
        $script:failedLookups[$appid] = $true
        return $null
    }

    $name = $null
    try {
        $r = Invoke-RestMethod "https://store.steampowered.com/api/appdetails?appids=$appid&filters=basic" -UseBasicParsing
        if ($r.$appid.success) { $name = $r.$appid.data.name }
        Start-Sleep -Milliseconds 300   # be polite to the store API
    } catch {
        Write-Warning "Name lookup failed for $appid : $($_.Exception.Message)"
    }
    if ($name) { $script:nameCache[$appid] = $name; return $name }
    $script:failedLookups[$appid] = $true
    return $null
}

function Get-SafeName([string]$name) {
    $clean = ($name -replace ('[\\/:*?"<>|{0}]' -f [char]0xFFFD), '').Trim(' .')
    if ([string]::IsNullOrWhiteSpace($clean)) { return $null }
    return $clean
}

function Get-FolderName([string]$appid) {
    $name   = Resolve-AppName $appid
    $folder = if ($name) { Get-SafeName $name } else { $null }
    if ($folder) { return $folder }
    if ([uint64]$appid -gt [int]::MaxValue) { return "Non-Steam App $appid" }
    return "AppID_$appid"
}

# Expands the folder template for one screenshot.
function Expand-Template([string]$game, [datetime]$ts) {
    $rel = $FolderTemplate.Replace('{game}', $game).
        Replace('{yyyy}', $ts.ToString('yyyy')).
        Replace('{MM}', $ts.ToString('MM')).
        Replace('{dd}', $ts.ToString('dd'))
    $safe = ($rel -split '[\\/]') | ForEach-Object { ($_ -replace '[:*?"<>|]', '').Trim(' .') } | Where-Object { $_ }
    return ($safe -join '\')
}

# Copies one screenshot if it isn't backed up yet. Returns 'copied' or 'skipped'.
# The size check uses -ge because the tray app enlarges copies slightly when it
# injects searchable metadata.
function Copy-Screenshot([System.IO.FileInfo]$file, [string]$appid, [string]$typeFolder,
                         [datetime]$ts, [string]$destName) {
    $game    = Get-FolderName $appid
    $destDir = Join-Path (Join-Path $Destination $typeFolder) (Expand-Template $game $ts)
    $dest    = Join-Path $destDir $destName

    if ((Test-Path $dest) -and ((Get-Item $dest).Length -ge $file.Length)) { return 'skipped' }
    New-Item $destDir -ItemType Directory -Force | Out-Null
    Copy-Item $file.FullName $dest -Force
    return 'copied'
}

# One-time upgrade: move legacy root-level game folders under "Standard\".
if (Test-Path $Destination) {
    $legacy = Get-ChildItem $Destination -Directory -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -ne $StandardFolder -and $_.Name -ne $HighResFolder -and
        (Get-ChildItem $_.FullName -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '^\d{4}-\d{2}-\d{2} \d{2}\.\d{2}\.\d{2}( \(\d+\))?\.\w+$' })
    }
    if ($legacy) {
        $stdRoot = Join-Path $Destination $StandardFolder
        New-Item $stdRoot -ItemType Directory -Force | Out-Null
        foreach ($dir in $legacy) {
            $target = Join-Path $stdRoot $dir.Name
            if (-not (Test-Path $target)) { Move-Item $dir.FullName $target }
        }
        Write-Host "Upgraded backup layout: moved $($legacy.Count) game folders under '$StandardFolder\'."
    }
}

$copied = 0; $skipped = 0; $games = @{}

# --- Standard screenshots ---
if ($Types -in 'Standard', 'Both') {
    foreach ($user in Get-ChildItem (Join-Path $steamPath 'userdata') -Directory -ErrorAction SilentlyContinue) {
        $remote = Join-Path $user.FullName '760\remote'
        if (-not (Test-Path $remote)) { continue }

        foreach ($appDir in Get-ChildItem $remote -Directory) {
            $srcDir = Join-Path $appDir.FullName 'screenshots'
            if (-not (Test-Path $srcDir)) { continue }

            # -File without -Recurse naturally excludes the 'thumbnails' subfolder
            foreach ($f in Get-ChildItem $srcDir -File) {
                $m = [regex]::Match($f.Name, '^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})_(\d+)(\.\w+)$')
                if (-not $m.Success) { continue }
                $ts = Get-Date -Year $m.Groups[1].Value -Month $m.Groups[2].Value -Day $m.Groups[3].Value `
                    -Hour $m.Groups[4].Value -Minute $m.Groups[5].Value -Second $m.Groups[6].Value
                $n = [int]$m.Groups[7].Value
                $suffix = if ($n -gt 1) { " ($n)" } else { '' }
                $destName = '{0:yyyy-MM-dd HH.mm.ss}{1}{2}' -f $ts, $suffix, $m.Groups[8].Value
                switch (Copy-Screenshot $f $appDir.Name $StandardFolder $ts $destName) {
                    'copied'  { $copied++;  $games[$appDir.Name] = $true }
                    'skipped' { $skipped++ }
                }
            }
        }
    }
}

# --- High-resolution (external copy) screenshots ---
if ($Types -in 'HighRes', 'Both') {
    $hrFolders = @()
    foreach ($cfg in Get-ChildItem (Join-Path $steamPath 'userdata') -Recurse -Filter 'localconfig.vdf' -ErrorAction SilentlyContinue) {
        $raw = [System.IO.File]::ReadAllText($cfg.FullName)
        if ($raw -match '"InGameOverlayScreenshotSaveUncompressed"\s+"1"' -and
            $raw -match '"InGameOverlayScreenshotSaveUncompressedPath"\s+"([^"]+)"') {
            $p = $Matches[1] -replace '\\\\', '\'
            if ($p -and ($hrFolders -notcontains $p)) { $hrFolders += $p }
        }
    }

    foreach ($folder in $hrFolders) {
        if (-not (Test-Path $folder)) { continue }
        foreach ($f in Get-ChildItem $folder -File) {
            $m = [regex]::Match($f.Name, '^(\d+)_(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})_(\d+)(\.\w+)$')
            if (-not $m.Success) { continue }
            $appid = $m.Groups[1].Value
            $ts = Get-Date -Year $m.Groups[2].Value -Month $m.Groups[3].Value -Day $m.Groups[4].Value `
                -Hour $m.Groups[5].Value -Minute $m.Groups[6].Value -Second $m.Groups[7].Value
            $n = [int]$m.Groups[8].Value
            $suffix = if ($n -gt 1) { " ($n)" } else { '' }
            $destName = '{0:yyyy-MM-dd HH.mm.ss}{1}{2}' -f $ts, $suffix, $m.Groups[9].Value
            switch (Copy-Screenshot $f $appid $HighResFolder $ts $destName) {
                'copied'  { $copied++;  $games[$appid] = $true }
                'skipped' { $skipped++ }
            }
        }
    }
}

if ($script:nameCache.Count -gt 0) {
    New-Item $cacheDir -ItemType Directory -Force | Out-Null
    # UTF-8 without BOM, matching what the tray app writes; Set-Content would use ANSI on PS 5.1.
    [System.IO.File]::WriteAllText($nameCacheFile, ($script:nameCache | ConvertTo-Json),
        (New-Object System.Text.UTF8Encoding($false)))
}
Write-Host "Done. $copied new screenshots copied across $($games.Count) games | $skipped already backed up."
