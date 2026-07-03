#Requires -Version 5.1
$ErrorActionPreference = 'Continue'
$Base = Split-Path $PSScriptRoot -Parent
$WebVbs = Join-Path $Base 'START WEB.vbs'

try {
    $actionWeb = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument "`"$WebVbs`""
    $triggerBoot = New-ScheduledTaskTrigger -AtStartup
    $triggerLogon = New-ScheduledTaskTrigger -AtLogOn
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    Register-ScheduledTask -TaskName 'MBT_POS_Web' -Action $actionWeb -Trigger @($triggerBoot, $triggerLogon) `
        -Settings $settings -Force | Out-Null
} catch {
    Write-Host 'Scheduled task skipped (use Startup folder fallback)'
}

$startup = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup\MBT_POS_Web.vbs'
Copy-Item -Force $WebVbs $startup

Start-Process wscript.exe -ArgumentList "`"$WebVbs`"" -WindowStyle Hidden
Start-Sleep 4
$cf = Join-Path $Base 'cloudflared.exe'
$cfg = Join-Path $env:USERPROFILE '.cloudflared\config.yml'
Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep 1
Start-Process -FilePath $cf -ArgumentList @('tunnel','--config',$cfg,'run') -WindowStyle Hidden
Write-Host 'OK https://trading.mugobyte.com'
