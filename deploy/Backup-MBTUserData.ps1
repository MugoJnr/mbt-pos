#Requires -Version 5.1
param([Parameter(Mandatory = $true)][string]$Version)

$ErrorActionPreference = 'Stop'
$profilesRoot = Join-Path $env:SystemDrive 'Users'

foreach ($profile in Get-ChildItem -LiteralPath $profilesRoot -Directory -Force) {
    $local = Join-Path $profile.FullName 'AppData\Local'
    $roaming = Join-Path $profile.FullName 'AppData\Roaming'
    $root = Join-Path $local 'MugoByte\MBT POS'
    $db = Join-Path $root 'data\mbt_pos.db'
    if (-not (Test-Path -LiteralPath $db)) {
        continue
    }

    $dest = Join-Path $root "backups\pre_upgrade\$Version"
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    foreach ($suffix in @('', '-wal', '-shm')) {
        $source = "$db$suffix"
        if (Test-Path -LiteralPath $source) {
            Copy-Item -LiteralPath $source -Destination (
                Join-Path $dest "mbt_pos.db$suffix") -Force
        }
    }

    $config = Join-Path $root 'config'
    if (Test-Path -LiteralPath $config) {
        Copy-Item -LiteralPath $config -Destination (
            Join-Path $dest 'config') -Recurse -Force
    }

    $licenseDest = Join-Path $dest 'license'
    New-Item -ItemType Directory -Force -Path $licenseDest | Out-Null
    $legacyLocal = Join-Path $local 'MugoByte\.mbt_lic\lc.db'
    $legacyRoaming = Join-Path $roaming 'MugoByte\.mbt_lic\lc.db'
    if (Test-Path -LiteralPath $legacyLocal) {
        Copy-Item -LiteralPath $legacyLocal -Destination (
            Join-Path $licenseDest 'lc.db.local') -Force
    }
    if (Test-Path -LiteralPath $legacyRoaming) {
        Copy-Item -LiteralPath $legacyRoaming -Destination (
            Join-Path $licenseDest 'lc.db.roaming') -Force
    }
}

$machineRoot = Join-Path $env:ProgramData 'MugoByte\MBT POS'
$machineLicense = Join-Path $machineRoot 'license\lc.db'
if (Test-Path -LiteralPath $machineLicense) {
    $machineDest = Join-Path $machineRoot "backups\pre_upgrade\$Version\license"
    New-Item -ItemType Directory -Force -Path $machineDest | Out-Null
    Copy-Item -LiteralPath $machineLicense -Destination (
        Join-Path $machineDest 'lc.db.machine') -Force
}
