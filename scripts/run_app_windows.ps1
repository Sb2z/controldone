$ErrorActionPreference = "Stop"

$RootDir = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RootDir

$Python = Join-Path $RootDir ".venv\Scripts\python.exe"
if (!(Test-Path $Python)) {
    Write-Host "Environnement .venv introuvable. Lance d'abord scripts\setup_windows.ps1"
    exit 1
}

$env:PYTHONPATH = "$RootDir\src;$env:PYTHONPATH"
& $Python -m controldone.webapp @args
