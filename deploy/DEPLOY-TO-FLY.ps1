#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
$AppRoot = Split-Path $PSScriptRoot -Parent
Set-Location $AppRoot

$fly = Get-Command flyctl -ErrorAction SilentlyContinue
if (-not $fly) { $fly = Get-Command fly -ErrorAction SilentlyContinue }
if (-not $fly) {
    foreach ($c in @(
        "$env:USERPROFILE\.fly\bin\flyctl.exe",
        "$env:USERPROFILE\.fly\bin\fly.exe",
        "$env:LOCALAPPDATA\Microsoft\WinGet\Links\fly.exe"
    )) {
        if (Test-Path $c) { $fly = Get-Command $c; break }
    }
}
if (-not $fly) {
    Write-Host 'Installing flyctl...'
    winget install Fly-io.flyctl -e --accept-source-agreements --accept-package-agreements | Out-Null
    $env:Path = [System.Environment]::GetEnvironmentVariable('Path','Machine') + ';' +
                [System.Environment]::GetEnvironmentVariable('Path','User')
    $fly = Get-Command fly -ErrorAction SilentlyContinue
}
if (-not $fly) { throw 'flyctl not found' }

Write-Host '=== MBT POS Fly.io cloud deploy ==='

$AppDataDb = Join-Path $env:LOCALAPPDATA 'MugoByte\MBT POS\data\mbt_pos.db'
$DestDb = Join-Path $AppRoot 'data\mbt_pos.db'
if (Test-Path $AppDataDb) { Copy-Item -Force $AppDataDb $DestDb }

& $fly auth whoami 2>&1 | Out-Host
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Fly.io login (browser)...'
    & $fly auth login
}
if ($LASTEXITCODE -ne 0) { throw 'Fly.io login failed' }

if (-not (Test-Path 'fly.toml')) { throw 'fly.toml missing' }

$AppName = 'mbt-portal'
$apps = (& $fly apps list 2>&1) -join "`n"
if ($apps -notmatch [regex]::Escape($AppName)) {
    & $fly apps create $AppName --org personal 2>&1 | Out-Host
}

$vols = (& $fly volumes list -a $AppName 2>&1) -join "`n"
if ($vols -notmatch 'mbt_data') {
    & $fly volumes create mbt_data -a $AppName --region jnb --size 1 -y 2>&1 | Out-Host
}

Write-Host 'Deploying...'
& $fly deploy --app $AppName --ha=$false 2>&1 | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'fly deploy failed' }

$flyUrl = 'https://portal.mugobyte.com'
try {
    $h = Invoke-WebRequest -Uri "$flyUrl/api/health" -UseBasicParsing -TimeoutSec 45
    Write-Host "Portal health: $($h.StatusCode) $($h.Content)"
} catch {
    Write-Host 'Portal health pending (app may still be starting)'
}

Write-Host "Done: $flyUrl"
