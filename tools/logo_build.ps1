Add-Type -AssemblyName System.Drawing

$root = "C:\Proyectos\AI_HUB"
$srcPath = Join-Path $root "WhatsApp Image 2026-11-20 at 08.18.21.jpeg"
$outStatic = Join-Path $root "aihub\web\static"
$outAssets = Join-Path $root "assets"

# --- 1. cargar origen -------------------------------------------------------
$src = New-Object System.Drawing.Bitmap $srcPath
$w = $src.Width; $h = $src.Height

$rect = New-Object System.Drawing.Rectangle 0, 0, $w, $h
$data = $src.LockBits($rect, [System.Drawing.Imaging.ImageLockMode]::ReadOnly, [System.Drawing.Imaging.PixelFormat]::Format24bppRgb)
$stride = $data.Stride
$bytes = New-Object byte[] ($stride * $h)
[System.Runtime.InteropServices.Marshal]::Copy($data.Scan0, $bytes, 0, $bytes.Length)
$src.UnlockBits($data)

# --- 2. negro -> blanco (antialias suave) ----------------------------------
# a = 0 en negro puro, 1 a partir de luminancia 40. Compone sobre blanco.
$flat = New-Object System.Drawing.Bitmap $w, $h, ([System.Drawing.Imaging.PixelFormat]::Format24bppRgb)
$frect = New-Object System.Drawing.Rectangle 0, 0, $w, $h
$fdata = $flat.LockBits($frect, [System.Drawing.Imaging.ImageLockMode]::WriteOnly, [System.Drawing.Imaging.PixelFormat]::Format24bppRgb)
$fstride = $fdata.Stride
$fb = New-Object byte[] ($fstride * $h)

$lo = 12.0; $hi = 44.0
for ($y = 0; $y -lt $h; $y++) {
  $so = $y * $stride
  $do = $y * $fstride
  for ($x = 0; $x -lt $w; $x++) {
    $i = $so + $x * 3
    $b = $bytes[$i]; $g = $bytes[$i + 1]; $r = $bytes[$i + 2]
    $lum = [Math]::Max($r, [Math]::Max($g, $b))
    if ($lum -le $lo) { $a = 0.0 }
    elseif ($lum -ge $hi) { $a = 1.0 }
    else { $a = ($lum - $lo) / ($hi - $lo) }
    $inv = 1.0 - $a
    $j = $do + $x * 3
    $fb[$j]     = [byte][Math]::Round(255 * $inv + $b * $a)
    $fb[$j + 1] = [byte][Math]::Round(255 * $inv + $g * $a)
    $fb[$j + 2] = [byte][Math]::Round(255 * $inv + $r * $a)
  }
}
[System.Runtime.InteropServices.Marshal]::Copy($fb, 0, $fdata.Scan0, $fb.Length)
$flat.UnlockBits($fdata)
$flat.Save((Join-Path $root "tools\_logo_flat.png"), [System.Drawing.Imaging.ImageFormat]::Png)

# --- 3. medir regiones sobre la imagen ya aplanada -------------------------
function Get-Bounds($bmp, $y0, $y1) {
  $bw = $bmp.Width
  $r = New-Object System.Drawing.Rectangle 0, 0, $bw, $bmp.Height
  $d = $bmp.LockBits($r, [System.Drawing.Imaging.ImageLockMode]::ReadOnly, [System.Drawing.Imaging.PixelFormat]::Format24bppRgb)
  $st = $d.Stride
  $buf = New-Object byte[] ($st * $bmp.Height)
  [System.Runtime.InteropServices.Marshal]::Copy($d.Scan0, $buf, 0, $buf.Length)
  $bmp.UnlockBits($d)
  $minX = $bw; $maxX = -1; $minY = $bmp.Height; $maxY = -1
  for ($y = $y0; $y -le $y1; $y++) {
    $base = $y * $st
    for ($x = 0; $x -lt $bw; $x++) {
      $o = $base + $x * 3
      $lum = [Math]::Min($buf[$o], [Math]::Min($buf[$o + 1], $buf[$o + 2]))
      if ($lum -lt 235) {
        if ($x -lt $minX) { $minX = $x }
        if ($x -gt $maxX) { $maxX = $x }
        if ($y -lt $minY) { $minY = $y }
        if ($y -gt $maxY) { $maxY = $y }
      }
    }
  }
  return @{ X = $minX; Y = $minY; W = ($maxX - $minX + 1); H = ($maxY - $minY + 1) }
}

$markBox = Get-Bounds $flat 230 710
$fullBox = Get-Bounds $flat 230 1060
"mark bbox: x=$($markBox.X) y=$($markBox.Y) w=$($markBox.W) h=$($markBox.H)"
"full bbox: x=$($fullBox.X) y=$($fullBox.Y) w=$($fullBox.W) h=$($fullBox.H)"

# --- 4. recortar + escalar sobre lienzo cuadrado ---------------------------
function New-SquarePng($bmp, $box, $size, $padRatio, $outPath) {
  $target = New-Object System.Drawing.Bitmap $size, $size, ([System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
  $g = [System.Drawing.Graphics]::FromImage($target)
  $g.Clear([System.Drawing.Color]::White)
  $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
  $g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
  $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
  $g.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality

  $max = $size * (1.0 - 2.0 * $padRatio)
  $scale = [Math]::Min($max / $box.W, $max / $box.H)
  $dw = [int][Math]::Round($box.W * $scale)
  $dh = [int][Math]::Round($box.H * $scale)
  $dx = [int][Math]::Round(($size - $dw) / 2.0)
  $dy = [int][Math]::Round(($size - $dh) / 2.0)

  $srcRect = New-Object System.Drawing.Rectangle $box.X, $box.Y, $box.W, $box.H
  $dstRect = New-Object System.Drawing.Rectangle $dx, $dy, $dw, $dh
  $g.DrawImage($bmp, $dstRect, $srcRect, [System.Drawing.GraphicsUnit]::Pixel)
  $g.Dispose()
  $target.Save($outPath, [System.Drawing.Imaging.ImageFormat]::Png)
  $target.Dispose()
  "-> $outPath ($size x $size, contenido ${dw}x${dh})"
}

New-SquarePng $flat $markBox 512 0.08 (Join-Path $outStatic "marin-mark.png")
New-SquarePng $flat $markBox 128 0.06 (Join-Path $outStatic "marin-mark-128.png")
New-SquarePng $flat $fullBox 512 0.04 (Join-Path $outStatic "marin-logo.png")
New-SquarePng $flat $markBox 256 0.08 (Join-Path $outAssets "marin-mark.png")
New-SquarePng $flat $markBox 40 0.06 (Join-Path $outAssets "marin-mark-40.png")

$flat.Dispose()
$src.Dispose()
