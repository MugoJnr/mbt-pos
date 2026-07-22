#Requires -Version 5.1
<#
Register the on-demand elevated MBT POS update helper task.
Called by the NSIS installer (already elevated) — no always-running service.
#>
$ErrorActionPreference = 'Stop'
$Helper = Join-Path $PSScriptRoot 'MBT_UpdateHelper.ps1'
$TaskName = 'MBT_POS_UpdateHelper'

if (-not (Test-Path -LiteralPath $Helper)) {
    Write-Host "Helper script missing: $Helper"
    exit 1
}

$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Helper`""
$prin = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $TaskName -Action $action -Principal $prin -Settings $set -Force | Out-Null
Write-Host "Registered scheduled task $TaskName"
exit 0
