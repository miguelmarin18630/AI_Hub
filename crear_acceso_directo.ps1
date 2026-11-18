# Crea un acceso directo "AI Hub" en el escritorio, con su icono.
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $pythonw) {
    $pythonw = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
}
if (-not $pythonw) {
    Write-Host "No encuentro Python en el PATH. Instala Python 3.10 o superior." -ForegroundColor Red
    exit 1
}

$script = Join-Path $root "AIHub.pyw"
$icon = Join-Path $root "assets\AIHub.ico"
$desktop = [Environment]::GetFolderPath("Desktop")
$lnkPath = Join-Path $desktop "AI Hub.lnk"

$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($lnkPath)
$lnk.TargetPath = $pythonw
$lnk.Arguments = '"' + $script + '"'
$lnk.WorkingDirectory = $root
$lnk.Description = "AI Hub: modelos gratuitos y de pago"
$lnk.WindowStyle = 1
if (Test-Path $icon) {
    $lnk.IconLocation = $icon + ",0"
}
$lnk.Save()

Write-Host "Acceso directo creado:" $lnkPath -ForegroundColor Green
