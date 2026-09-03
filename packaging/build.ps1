# Build a standalone Ambaar for Windows.
#
#   .\packaging\build.ps1
#
# Output lands in dist\. Run from the repository root.

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not (Test-Path ".venv")) {
    Write-Host "No .venv found. Create one on Python 3.9+ first:" -ForegroundColor Yellow
    Write-Host "    py -3.12 -m venv .venv"
    exit 1
}
& .\.venv\Scripts\Activate.ps1

$pyv = python -c "import sys;print('%d.%d' % sys.version_info[:2])"
Write-Host "Python $pyv"
python -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3,9) else 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Python 3.9+ required. yt-dlp will not install correctly below that." -ForegroundColor Red
    exit 1
}

Write-Host "Installing build dependencies"
pip install -q -U -r requirements.txt
pip install -q -U pyinstaller pillow

$pyi = python -c "import PyInstaller;print(PyInstaller.__version__)"
$qt  = python -c "from PySide6 import QtCore;print(QtCore.qVersion())"
Write-Host "PyInstaller $pyi  /  Qt $qt"
Write-Host "If the build runs but the .exe fails on QtCore, rebuild fat:" -ForegroundColor DarkGray
Write-Host "    $env:AMBAAR_LEAN=0; pyinstaller packaging\ambaar.spec --noconfirm --clean" -ForegroundColor DarkGray

Write-Host "Generating icons"
python packaging\make_icons.py

Write-Host "Building"
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
pyinstaller packaging\ambaar.spec --noconfirm --clean

Write-Host ""
Write-Host "Built:" -ForegroundColor Green
Get-ChildItem dist
Write-Host ""
Write-Host "Package it for release:"
Write-Host "    Compress-Archive -Path dist\ambaar\* -DestinationPath ambaar-windows.zip"
