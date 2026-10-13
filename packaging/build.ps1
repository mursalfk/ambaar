# packaging/build.ps1
#
# Build a standalone Ambaar for Windows.
#
#   .\packaging\build.ps1
#   powershell -ExecutionPolicy Bypass -File packaging/build.ps1   # from Git Bash
#
# Output lands in dist\. Run from anywhere; the script locates the repo itself.

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not (Test-Path ".venv")) {
    Write-Host "No .venv found. Create one on Python 3.9+ first:" -ForegroundColor Yellow
    Write-Host "    py -3.12 -m venv .venv"
    exit 1
}
& .\.venv\Scripts\Activate.ps1

# Call the interpreter by absolute path and reach every tool through "-m".
#
# Windows console scripts (pip.exe, pyinstaller.exe) embed the absolute path of
# the interpreter that created them. Move or rename the project folder and every
# one of those shims keeps pointing at the old location, failing with
# "Fatal error in launcher: Unable to create process using ...". python.exe
# itself keeps working, so the failure looks like a missing package rather than
# a moved venv. Going through "-m" sidesteps the shims entirely.
$Py = Join-Path (Get-Location) ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
    Write-Host "No interpreter at $Py -- the venv is incomplete. Recreate it:" -ForegroundColor Red
    Write-Host "    Remove-Item -Recurse -Force .venv; py -3.12 -m venv .venv"
    exit 1
}

$pyv = & $Py -c "import sys;print('%d.%d.%d' % sys.version_info[:3])"
Write-Host "Python $pyv  ($Py)"
& $Py -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3,9) else 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Python 3.9+ required. Below that pip installs an obsolete yt-dlp instead of refusing." -ForegroundColor Red
    exit 1
}

if ($env:CONDA_DEFAULT_ENV) {
    Write-Host "Warning: conda environment '$($env:CONDA_DEFAULT_ENV)' is active." -ForegroundColor Yellow
    Write-Host "         Run 'conda deactivate' first, or PyInstaller may bundle conda's Qt." -ForegroundColor Yellow
}

Write-Host "Installing build dependencies"
& $Py -m pip install -q -U -r requirements.txt
& $Py -m pip install -q -U pyinstaller pillow

$pyi = & $Py -c "import PyInstaller;print(PyInstaller.__version__)"
$qt  = & $Py -c "from PySide6 import QtCore;print(QtCore.qVersion())"
Write-Host "PyInstaller $pyi  /  Qt $qt"

# Single quotes: the literal must survive, not expand. Double quotes here print
# the *value* of $env:AMBAAR_LEAN, which renders the hint as "=0; pyinstaller".
Write-Host 'If the .exe builds but fails on QtCore, rebuild with Qt untouched:' -ForegroundColor DarkGray
Write-Host '    $env:AMBAAR_LEAN=1 is the trimmed build; unset it for the full one.' -ForegroundColor DarkGray

Write-Host "Generating icons"
& $Py packaging\make_icons.py

Write-Host "Building"
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
& $Py -m PyInstaller packaging\ambaar.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) {
    Write-Host "Build failed. Run 'python packaging\doctor.py' for diagnostics." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Built:" -ForegroundColor Green
Get-ChildItem dist
Write-Host ""
Write-Host "Launch it before shipping -- a build that compiles is not evidence that it runs:"
Write-Host "    .\dist\ambaar\ambaar.exe"
Write-Host ""
Write-Host "Package it for release:"
Write-Host "    Compress-Archive -Path dist\ambaar\* -DestinationPath ambaar-windows.zip"