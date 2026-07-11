<#
.SYNOPSIS
    Fails if any .cs/.ps1 file contains a non-ASCII byte.

.DESCRIPTION
    Enforces the pure-ASCII rule documented in CLAUDE.md (this project has a
    history of mojibake bugs from UTF-8 written / ANSI read back). Used both
    as a build.ps1 preflight step and as a git pre-commit hook, so a stray
    smart quote or em dash gets caught immediately instead of at build time.

.PARAMETER Path
    Specific files to check.

.PARAMETER PathList
    A single semicolon-separated string of files to check (used by the git
    pre-commit hook, which can't easily pass a PowerShell array from sh).

    With neither -Path nor -PathList, checks every *.cs/*.ps1 file in the
    repo (excluding bin/obj/dist).
#>
param(
    [string[]]$Path,
    [string]$PathList
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent

if ($PathList) {
    $Path = $PathList -split ';' | Where-Object { $_ -ne '' }
}

if (-not $Path) {
    $Path = Get-ChildItem $root -Recurse -Include *.cs, *.ps1 |
        Where-Object { $_.FullName -notmatch '\\(bin|obj|dist)\\' } |
        Select-Object -ExpandProperty FullName
}

$bad = foreach ($file in $Path) {
    $full = if ([System.IO.Path]::IsPathRooted($file)) { $file } else { Join-Path $root $file }
    if (-not (Test-Path $full)) { continue }
    $bytes = [System.IO.File]::ReadAllBytes($full)
    $start = 0
    if ($bytes.Length -gt 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) { $start = 3 }
    $hasNonAscii = $false
    for ($i = $start; $i -lt $bytes.Length; $i++) {
        if ($bytes[$i] -gt 127) { $hasNonAscii = $true; break }
    }
    if ($hasNonAscii) { $file }
}

if ($bad) {
    Write-Host "Non-ASCII bytes found in:" -ForegroundColor Red
    $bad | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    Write-Host "Replace with \uXXXX escapes (see CLAUDE.md)." -ForegroundColor Yellow
    exit 1
}

Write-Host "ASCII check passed ($($Path.Count) file(s))." -ForegroundColor Green
exit 0
