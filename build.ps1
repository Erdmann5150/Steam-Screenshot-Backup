<#
.SYNOPSIS
    Builds Steam Screenshot Backup release artifacts.

.DESCRIPTION
    Produces:
      dist\portable\SteamScreenshotBackup.exe          zero-install, self-contained exe
      dist\installer\SteamScreenshotBackup-Setup-<v>.exe   Inno Setup installer

    A copy of both is also placed in a "safe" folder OUTSIDE the repository
    (Documents\SteamBackup Releases\v<version>) so cleanup or uninstall testing can
    never destroy the only copy.

.NOTES
    Requires the .NET 8 SDK and Inno Setup 6 (winget install JRSoftware.InnoSetup).
#>
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

# Check if the process is running
$running = Get-Process SteamScreenshotBackup -ErrorAction SilentlyContinue
if ($running) { throw "Stop any running SteamScreenshotBackup instance first" }

# Version comes from the csproj so it only lives in one place.
$csproj = Join-Path $root 'app\SteamScreenshotBackup.csproj'
$version = ([xml](Get-Content $csproj)).Project.PropertyGroup.Version
if (-not $version) { throw "Version not found in $csproj" }

# Validate version matches setup.iss (must be bumped in both places)
$iss = Join-Path $root 'installer\setup.iss'
$issContent = Get-Content $iss -Raw
if ($issContent -match '#define AppVersion\s+"([^"]+)"') {
    $issVersion = $matches[1]
    if ($issVersion -ne $version) {
        throw "Version mismatch: csproj has $version, setup.iss has $issVersion. Both must be updated together."
    }
}

Write-Host "Building Steam Screenshot Backup $version" -ForegroundColor Cyan

# --- 1. Publish the self-contained single-file exe (also the portable build) ---
dotnet publish $csproj -c Release -r win-x64 --self-contained -p:PublishSingleFile=true --nologo
if ($LASTEXITCODE -ne 0) { throw "dotnet publish failed" }
$publishDir = Join-Path $root 'app\bin\Release\net8.0-windows\win-x64\publish'

$distPortable = Join-Path $root 'dist\portable'
New-Item $distPortable -ItemType Directory -Force | Out-Null
Copy-Item (Join-Path $publishDir 'SteamScreenshotBackup.exe') $distPortable -Force
Write-Host "Portable exe -> $distPortable"

# --- 2. Compile the installer ---
$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
          "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 not found. Install with: winget install JRSoftware.InnoSetup" }

$distInstaller = Join-Path $root 'dist\installer'
New-Item $distInstaller -ItemType Directory -Force | Out-Null
& $iscc (Join-Path $root 'installer\setup.iss') "/DAppVersion=$version" "/DPublishDir=$publishDir" "/O$distInstaller" | Select-Object -Last 3
if ($LASTEXITCODE -ne 0) { throw "ISCC failed" }
Write-Host "Installer -> $distInstaller"

# --- 3. Safe copies outside the repository ---
$safe = Join-Path ([Environment]::GetFolderPath('MyDocuments')) "SteamBackup Releases\v$version"
New-Item $safe -ItemType Directory -Force | Out-Null
Copy-Item (Join-Path $distPortable 'SteamScreenshotBackup.exe') $safe -Force

$installerFile = Join-Path $distInstaller "SteamScreenshotBackup-Setup-$version.exe"
if (-not (Test-Path $installerFile)) { throw "Installer not found at $installerFile" }
Copy-Item $installerFile $safe -Force
Write-Host "Safe copies -> $safe" -ForegroundColor Green

Write-Host "Done." -ForegroundColor Green
