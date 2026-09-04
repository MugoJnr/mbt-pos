#Requires -Version 5.1
<# Remove the retired SYSTEM update helper task. #>
$ErrorActionPreference = 'Stop'
$TaskName = 'MBT_POS_UpdateHelper'
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Write-Host "Retired scheduled task $TaskName is not registered"
exit 0
