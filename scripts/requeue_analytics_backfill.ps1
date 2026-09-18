# Force Portal analytics re-queue on a shop PC. Run with MBT POS CLOSED.
#
# 1. Removes analytics_backfill so historical rows are walked from id 0.
# 2. Re-opens sync_outbox rows for analytics entity types so already-flushed
#    event IDs are sent again (ingest previously failed server-side).
# 3. Does NOT touch sales / products / inventory / license / identity.

$ErrorActionPreference = 'Stop'
$state = "$env:LOCALAPPDATA\MugoByte\MBT POS\config\cloud_backup_state.json"
$db    = "$env:LOCALAPPDATA\MugoByte\MBT POS\data\mbt_pos.db"
$sqlite = Join-Path $PSScriptRoot 'sqlite3.exe'

$pos = Get-Process | Where-Object {
    $_.ProcessName -match '^(MBT POS|MBT_POS|MBT-POS)$'
}
if ($pos) {
    Write-Host "MBT POS is still running (PID $($pos.Id -join ',')). Close it first." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $state)) {
    Write-Host "NOT FOUND: $state" -ForegroundColor Red
    exit 1
}

Copy-Item $state "$state.bak" -Force
Write-Host "State backup: $state.bak"

$json = Get-Content $state -Raw | ConvertFrom-Json
if ($json.PSObject.Properties.Name -contains 'analytics_backfill') {
    Write-Host "Current checkpoint:" -ForegroundColor Cyan
    $bf = $json.analytics_backfill
    foreach ($p in $bf.PSObject.Properties) {
        if ($p.Name -eq 'completed_at') {
            Write-Host ("  completed_at = {0}" -f $p.Value)
        } else {
            Write-Host ("  {0,-16} last_id={1,-8} done={2}" -f $p.Name, $p.Value.last_id, $p.Value.done)
        }
    }
    $json.PSObject.Properties.Remove('analytics_backfill')
    Write-Host "Removed analytics_backfill (full re-walk)." -ForegroundColor Green
} else {
    Write-Host "No analytics_backfill key (already cleared)."
}
$json | ConvertTo-Json -Depth 20 | Set-Content $state -Encoding UTF8

if (Test-Path $sqlite) {
    if (-not (Test-Path $db)) {
        Write-Host "DB not found, skipped outbox reset: $db" -ForegroundColor Yellow
    } else {
        Copy-Item $db "$db.bak-outbox" -Force
        $sql = @"
UPDATE sync_outbox
SET processed_at = NULL,
    available_at = datetime('now','localtime'),
    attempts = 0
WHERE entity_type IN (
  'sale','sale_item','product','customer',
  'debt_invoice','debt_payment','stock_movement'
);
SELECT changes();
"@
        Write-Host "`nRe-opening analytics outbox rows..." -ForegroundColor Cyan
        $changed = & $sqlite $db $sql
        Write-Host "Outbox rows made eligible again: $changed" -ForegroundColor Green
        Write-Host "DB backup: $db.bak-outbox"
    }
} else {
    Write-Host "`nsqlite3.exe missing next to this script - outbox rows were NOT reset." -ForegroundColor Yellow
    Write-Host "Copy sqlite3.exe beside FIX_PORTAL_ANALYTICS.bat and re-run."
}

Write-Host ""
Write-Host "Reopen MBT POS, sign in, and leave it running 10-20 minutes." -ForegroundColor Green
Write-Host "Portal Reports must use Overview (not Saved Reports) and range 9-15 Sep."
