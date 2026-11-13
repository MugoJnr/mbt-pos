Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$imgPath = $args[0]
if (-not $imgPath) { throw 'usage: clip_image.ps1 <path>' }
$img = [System.Drawing.Image]::FromFile($imgPath)
[System.Windows.Forms.Clipboard]::SetImage($img)
$img.Dispose()
Write-Output 'CLIP_OK'
