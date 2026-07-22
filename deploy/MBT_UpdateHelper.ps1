#Requires -Version 5.1
<#
.SYNOPSIS
  Least-privilege elevated helper for MBT POS unattended updates.

.DESCRIPTION
  Registered once by the NSIS installer as scheduled task "MBT_POS_UpdateHelper"
  (SYSTEM / Highest). The unprivileged POS app writes a job file, then runs:
    schtasks /Run /TN "MBT_POS_UpdateHelper"

  This script ONLY executes a verified MBT_POS_Setup*.exe with /S.
  It never runs arbitrary commands from the job file.
#>
$ErrorActionPreference = 'Stop'
$TaskName = 'MBT_POS_UpdateHelper'
$BrandRoot = Join-Path $env:LOCALAPPDATA 'MugoByte\MBT POS'
$JobPath = Join-Path $BrandRoot 'update_job.json'
$ResultPath = Join-Path $BrandRoot 'update_job_result.json'
$LogPath = Join-Path $env:TEMP 'mbt_update.log'

function Write-MbtLog([string]$Message) {
    $line = '{0}  helper: {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    try { Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8 } catch {}
}

function Write-Result([hashtable]$Payload) {
    New-Item -ItemType Directory -Force -Path $BrandRoot | Out-Null
    ($Payload | ConvertTo-Json -Compress) | Set-Content -LiteralPath $ResultPath -Encoding UTF8
}

function Test-AllowedInstallerPath([string]$Path) {
    if (-not $Path) { return $false }
    $full = [System.IO.Path]::GetFullPath($Path)
    $name = [System.IO.Path]::GetFileName($full)
    if ($name -notmatch '^(?i)MBT_POS_Setup(_v[\d.]+)?\.exe$') { return $false }
    if ($full -match '[;&|<>`]') { return $false }

    $allowedRoots = @(
        [System.IO.Path]::GetFullPath($env:TEMP),
        [System.IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'MugoByte\MBT POS\updates')),
        [System.IO.Path]::GetFullPath((Join-Path $env:ProgramData 'MugoByte\MBT POS\updates'))
    )
    foreach ($root in $allowedRoots) {
        if ($full.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }
    return $false
}

function Get-FileSha256([string]$Path) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $fs = [System.IO.File]::OpenRead($Path)
        try {
            $hash = $sha.ComputeHash($fs)
            return ([System.BitConverter]::ToString($hash) -replace '-', '').ToLowerInvariant()
        } finally { $fs.Dispose() }
    } finally { $sha.Dispose() }
}

Write-MbtLog 'started'
if (-not (Test-Path -LiteralPath $JobPath)) {
    Write-MbtLog 'no job file'
    Write-Result @{ ok = $false; exit_code = 2; error = 'missing_job'; request_id = '' }
    exit 2
}

try {
    $job = Get-Content -LiteralPath $JobPath -Raw -Encoding UTF8 | ConvertFrom-Json
} catch {
    Write-MbtLog "invalid job json: $_"
    Write-Result @{ ok = $false; exit_code = 3; error = 'invalid_job'; request_id = '' }
    exit 3
}

$requestId = [string]($job.request_id)
$installer = [string]($job.installer_path)
$expected = ([string]($job.sha256)).Trim().ToLowerInvariant() -replace '^sha256:', '' -replace '\s', ''
$version = [string]($job.version)

if (-not $expected -or $expected.Length -ne 64 -or $expected -notmatch '^[0-9a-f]{64}$') {
    Write-MbtLog 'missing or invalid checksum in job'
    Write-Result @{ ok = $false; exit_code = 4; error = 'missing_checksum'; request_id = $requestId; version = $version }
    exit 4
}

if (-not (Test-AllowedInstallerPath $installer)) {
    Write-MbtLog "refused path: $installer"
    Write-Result @{ ok = $false; exit_code = 5; error = 'path_refused'; request_id = $requestId; version = $version }
    exit 5
}

if (-not (Test-Path -LiteralPath $installer)) {
    Write-MbtLog "installer missing: $installer"
    Write-Result @{ ok = $false; exit_code = 6; error = 'installer_missing'; request_id = $requestId; version = $version }
    exit 6
}

try {
    Unblock-File -LiteralPath $installer -ErrorAction SilentlyContinue
    $zone = "${installer}:Zone.Identifier"
    if (Test-Path -LiteralPath $zone) {
        Remove-Item -LiteralPath $zone -Force -ErrorAction SilentlyContinue
    }
} catch {}

$actual = Get-FileSha256 $installer
if ($actual -ne $expected) {
    Write-MbtLog "checksum mismatch expected=$expected actual=$actual"
    Write-Result @{
        ok = $false; exit_code = 7; error = 'checksum_mismatch'
        request_id = $requestId; version = $version
        expected = $expected; actual = $actual
    }
    exit 7
}

Write-MbtLog "running silent install v$version path=$installer"
try {
    $p = Start-Process -FilePath $installer -ArgumentList '/S' -Wait -PassThru
    $code = [int]$p.ExitCode
} catch {
    Write-MbtLog "Start-Process failed: $_"
    Write-Result @{ ok = $false; exit_code = 1; error = "$_"; request_id = $requestId; version = $version }
    exit 1
}

$ok = ($code -eq 0)
Write-MbtLog "installer exit=$code ok=$ok"
Write-Result @{
    ok = $ok
    exit_code = $code
    error = $(if ($ok) { '' } else { "installer_exit_$code" })
    request_id = $requestId
    version = $version
}

try { Remove-Item -LiteralPath $JobPath -Force -ErrorAction SilentlyContinue } catch {}
if ($ok) { exit 0 } else { exit $code }
