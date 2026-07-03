#Requires -Version 5.1
<#
.SYNOPSIS
  Upload MBT POS to an Ubuntu cloud server and install 24/7 web + tunnel services.

.PARAMETER ServerIP
  Public IP of your Oracle Cloud / VPS Ubuntu server.

.PARAMETER SshUser
  SSH login user (default: ubuntu).

.PARAMETER Subdomain
  mugobyte.com subdomain (default: trading).

.EXAMPLE
  .\deploy\DEPLOY-TO-CLOUD.ps1 -ServerIP 203.0.113.50

  First time on the server, create the VM with Ubuntu 22.04 and ensure port 22 is open.
  Your SSH key must be in %USERPROFILE%\.ssh\id_rsa or id_ed25519.
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$ServerIP,
    [string]$SshUser = 'ubuntu',
    [string]$Subdomain = 'trading',
    [string]$ShopName = 'Trading',
    [string]$SshKey = '',
    [switch]$SkipUpload
)

$ErrorActionPreference = 'Stop'
$AppRoot = Split-Path $PSScriptRoot -Parent
if (-not (Test-Path "$AppRoot\backend\app.py")) {
    throw "Cannot find MBT POS at $AppRoot"
}

Write-Host "=============================================="
Write-Host " MBT POS — Deploy to cloud"
Write-Host " App     : $AppRoot"
Write-Host " Server  : ${SshUser}@${ServerIP}"
Write-Host " URL     : https://${Subdomain}.mugobyte.com"
Write-Host "=============================================="
Write-Host ""

# Sync live database from installed app if present
$AppDataDb = Join-Path $env:LOCALAPPDATA 'MugoByte\MBT POS\data\mbt_pos.db'
$DestDb = Join-Path $AppRoot 'data\mbt_pos.db'
if ((Test-Path $AppDataDb) -and ((Get-Item $AppDataDb).Length -gt (Get-Item $DestDb -ErrorAction SilentlyContinue).Length)) {
    Copy-Item -Force $AppDataDb $DestDb
    Write-Host "Copied live database from AppData ($((Get-Item $DestDb).Length) bytes)"
}

if (-not $SshKey) {
    foreach ($k in @('id_ed25519', 'id_rsa')) {
        $p = Join-Path $env:USERPROFILE ".ssh\$k"
        if (Test-Path $p) { $SshKey = $p; break }
    }
}
$sshArgs = @()
if ($SshKey) { $sshArgs += @('-i', $SshKey) }
$target = "${SshUser}@${ServerIP}"
$scpArgs = @('-r') + $sshArgs

$Stage = Join-Path $env:TEMP "mbt-pos-deploy"
if (Test-Path $Stage) { Remove-Item -Recurse -Force $Stage }
New-Item -ItemType Directory -Path $Stage | Out-Null

Write-Host "[1/4] Staging files..."
$exclude = @('venv', '__pycache__', 'build', 'dist', '.git', 'cloudflared.exe')
Get-ChildItem $AppRoot | Where-Object { $exclude -notcontains $_.Name } |
    Copy-Item -Recurse -Destination $Stage

# Include Cloudflare tunnel credentials (already provisioned on Windows)
$cfDir = Join-Path $env:USERPROFILE '.cloudflared'
if (Test-Path $cfDir) {
    Copy-Item -Recurse $cfDir (Join-Path $Stage 'deploy\cloudflared-bundle')
    Write-Host "      Bundled Cloudflare tunnel config"
}

$archive = Join-Path $env:TEMP 'mbt-pos-cloud.tar.gz'
if (Test-Path $archive) { Remove-Item -Force $archive }

# tar via Windows 10+ built-in tar
Push-Location $Stage
tar -czf $archive .
Pop-Location
Write-Host "      Archive: $archive ($([math]::Round((Get-Item $archive).Length / 1MB, 1)) MB)"

if (-not $SkipUpload) {
    Write-Host "[2/4] Testing SSH..."
    & ssh @sshArgs -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 $target "echo connected && uname -a"
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "SSH failed. Ensure:"
        Write-Host "  - Ubuntu VM is running with public IP $ServerIP"
        Write-Host "  - Port 22 open in cloud firewall / security list"
        Write-Host "  - Your public key is in ~/.ssh/authorized_keys on the server"
        exit 1
    }

    Write-Host "[3/4] Uploading..."
    & scp @scpArgs $archive "${target}:~/mbt-pos-cloud.tar.gz"
    if ($LASTEXITCODE -ne 0) { exit 1 }
} else {
    Write-Host "[2/4] Skipped upload (-SkipUpload)"
    Write-Host "[3/4] Skipped upload"
}

$remoteScript = @'
set -euo pipefail
mkdir -p ~/mbt_pos && cd ~/mbt_pos
tar -xzf ~/mbt-pos-cloud.tar.gz
sudo bash deploy/ubuntu-server.sh --subdomain SUBDOMAIN_PLACEHOLDER --shop "SHOP_PLACEHOLDER" --skip-cloudflare
if [ -d deploy/cloudflared-bundle ]; then
  sudo mkdir -p /home/mbt/.cloudflared
  sudo cp deploy/cloudflared-bundle/*.json deploy/cloudflared-bundle/cert.pem /home/mbt/.cloudflared/ 2>/dev/null || true
  TUN_ID=$(basename deploy/cloudflared-bundle/*.json .json | head -1)
  sudo tee /home/mbt/.cloudflared/config.yml >/dev/null <<CFYML
tunnel: ${TUN_ID}
credentials-file: /home/mbt/.cloudflared/${TUN_ID}.json
ingress:
  - hostname: SUBDOMAIN_PLACEHOLDER.mugobyte.com
    service: http://localhost:5050
  - service: http_status:404
CFYML
  sudo chown -R mbt:mbt /home/mbt/.cloudflared
  sudo systemctl enable mbt-pos-tunnel
  sudo systemctl restart mbt-pos-tunnel
fi
sleep 3
curl -s http://127.0.0.1:5050/api/health || true
echo "DONE — open https://SUBDOMAIN_PLACEHOLDER.mugobyte.com"
'@
$remoteScript = $remoteScript.Replace('SUBDOMAIN_PLACEHOLDER', $Subdomain).Replace('SHOP_PLACEHOLDER', $ShopName)

Write-Host "[4/4] Installing on server (may take 3–5 min)..."
$remoteScript | & ssh @sshArgs $target "bash -s"
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host ""
Write-Host "=============================================="
Write-Host " DEPLOY COMPLETE"
Write-Host " https://${Subdomain}.mugobyte.com"
Write-Host "=============================================="
Start-Sleep 3
try {
    $r = Invoke-WebRequest -Uri "https://${Subdomain}.mugobyte.com/api/health" -UseBasicParsing -TimeoutSec 20
    Write-Host "Health check: $($r.StatusCode) $($r.Content)"
} catch {
    Write-Host "Remote health check pending — DNS/tunnel may need 1–2 min after PC tunnel stops."
}
