<#
.SYNOPSIS
    Uploads release artifacts to VirusTotal and reports scan results.

.DESCRIPTION
    Scans dist\portable\SteamScreenshotBackup.exe,
    dist\portable-offline\SteamScreenshotBackup-Offline.exe, and
    dist\installer\SteamScreenshotBackup-Setup-<v>.exe (run build.ps1 first).

    For each file: computes its SHA256 and checks VirusTotal by hash first
    (avoids burning an upload/day quota on a build that's already been
    scanned). If VirusTotal has never seen the hash, uploads it and polls
    until the scan completes. Prints a detection ratio and the
    /gui/file/<hash>/summary link for each, ready to paste into README.md.

.NOTES
    Requires a VirusTotal API key in the VT_API_KEY environment variable.
    Get one free at https://www.virustotal.com/gui/my-apikey (sign up, then
    the key is on your profile page). Set it for the current session with:
        $env:VT_API_KEY = 'your-key-here'
    or persist it across sessions (once, in an elevated or normal prompt):
        [Environment]::SetEnvironmentVariable('VT_API_KEY', 'your-key-here', 'User')
    Never commit the key or put it in a script file.

    Free-tier API limits: 4 requests/minute, 500/day. This script sleeps
    between calls to stay under that.
#>
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

$apiKey = $env:VT_API_KEY
if (-not $apiKey) {
    # Falls back to the persisted User-level value directly, in case this
    # process was already running when the variable was set (a new session
    # would normally pick it up automatically).
    $apiKey = [Environment]::GetEnvironmentVariable('VT_API_KEY', 'User')
}
if (-not $apiKey) {
    throw "VT_API_KEY environment variable not set. Run:`n  `$env:VT_API_KEY = 'your-key-here'`nGet a free key at https://www.virustotal.com/gui/my-apikey"
}

$csproj = Join-Path $root 'app\SteamScreenshotBackup.csproj'
$version = ([xml](Get-Content $csproj)).Project.PropertyGroup.Version
if (-not $version) { throw "Version not found in $csproj" }

$files = @(
    (Join-Path $root 'dist\portable\SteamScreenshotBackup.exe'),
    (Join-Path $root 'dist\portable-offline\SteamScreenshotBackup-Offline.exe'),
    (Join-Path $root "dist\installer\SteamScreenshotBackup-Setup-$version.exe")
)
foreach ($f in $files) {
    if (-not (Test-Path $f)) { throw "Missing $f -- run build.ps1 first" }
}

$headers = @{ 'x-apikey' = $apiKey }

function Get-VTReportByHash {
    param([string]$Sha256)
    try {
        $resp = Invoke-RestMethod -Uri "https://www.virustotal.com/api/v3/files/$Sha256" -Headers $headers -Method Get
        return $resp
    } catch {
        if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 404) { return $null }
        throw
    }
}

function Submit-VTFile {
    param([string]$Path)
    $size = (Get-Item $Path).Length
    if ($size -gt 32MB) {
        $uploadUrlResp = Invoke-RestMethod -Uri 'https://www.virustotal.com/api/v3/files/upload_url' -Headers $headers -Method Get
        $uploadUri = $uploadUrlResp.data
    } else {
        $uploadUri = 'https://www.virustotal.com/api/v3/files'
    }

    # Shells out to curl.exe (built into Windows 10/11) for the multipart
    # upload rather than Invoke-RestMethod -Form (PowerShell 6+ only) or
    # hand-rolled HttpClient (VirusTotal rejected its multipart body under
    # Windows PowerShell 5.1) -- this works the same under either shell.
    $body = & curl.exe -s -X POST $uploadUri -H "x-apikey: $apiKey" -F "file=@$Path"
    if ($LASTEXITCODE -ne 0) { throw "curl.exe upload failed with exit code $LASTEXITCODE" }
    $json = $body | ConvertFrom-Json
    if (-not $json.data.id) { throw "VirusTotal upload failed: $body" }
    return $json.data.id   # analysis id
}

function Wait-VTAnalysis {
    param([string]$AnalysisId)
    while ($true) {
        $resp = Invoke-RestMethod -Uri "https://www.virustotal.com/api/v3/analyses/$AnalysisId" -Headers $headers -Method Get
        if ($resp.data.attributes.status -eq 'completed') { return $resp }
        Write-Host "  ...still scanning, waiting 20s" -ForegroundColor DarkGray
        Start-Sleep -Seconds 20
    }
}

$results = @()

foreach ($f in $files) {
    $name = Split-Path $f -Leaf
    Write-Host "Hashing $name" -ForegroundColor Cyan
    $sha256 = (Get-FileHash -Path $f -Algorithm SHA256).Hash.ToLower()

    Write-Host "Checking VirusTotal for existing report ($sha256)"
    $report = Get-VTReportByHash -Sha256 $sha256

    if (-not $report) {
        Write-Host "Not on VirusTotal yet -- uploading $name" -ForegroundColor Yellow
        $analysisId = Submit-VTFile -Path $f
        Start-Sleep -Seconds 15
        $analysis = Wait-VTAnalysis -AnalysisId $analysisId
        Start-Sleep -Seconds 15   # stay under 4 req/min before the next file
        $report = Get-VTReportByHash -Sha256 $sha256
    } else {
        Write-Host "Already scanned -- reusing existing report" -ForegroundColor Green
    }

    $stats = $report.data.attributes.last_analysis_stats
    $malicious = $stats.malicious
    $suspicious = $stats.suspicious
    $total = ($stats.malicious + $stats.suspicious + $stats.undetected + $stats.harmless + $stats.timeout)
    $flagged = $malicious + $suspicious

    $results += [PSCustomObject]@{
        File      = $name
        Sha256    = $sha256
        Detection = "$flagged/$total"
        Link      = "https://www.virustotal.com/gui/file/$sha256/summary"
    }

    Start-Sleep -Seconds 15   # stay under 4 req/min before the next file
}

Write-Host "`nResults:" -ForegroundColor Cyan
$results | Format-Table File, Detection, Link -AutoSize

Write-Host "`nMarkdown for README:" -ForegroundColor Cyan
foreach ($r in $results) {
    Write-Host "[$($r.File)]($($r.Link)) ($($r.Detection))"
}
