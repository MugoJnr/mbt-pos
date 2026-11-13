$ErrorActionPreference = 'Stop'
$src = Join-Path $PSScriptRoot '..\version.json'
$raw = Get-Content -LiteralPath $src -Raw -Encoding UTF8
$targets = @(
  'C:\Program Files\MugoByte\MBT POS\_internal\version.json',
  'C:\Program Files\MugoByte\MBT POS\version.json'
)
foreach ($t in $targets) {
  $dir = Split-Path $t -Parent
  if (-not (Test-Path $dir)) { throw "Missing install dir: $dir" }
  [System.IO.File]::WriteAllText($t, $raw.TrimEnd() + "`n")
  Write-Host "stamped $t"
}
$check = Get-Content 'C:\Program Files\MugoByte\MBT POS\_internal\version.json' -Raw
if ($check -notmatch 'ff44e8f8b5da81b19696f08f385c428422eb8f08dfd26c0ba075ca2c7ea1f106') {
  throw 'checksum not present after stamp'
}
Write-Host 'PF version.json checksum OK'
