$ErrorActionPreference = "Stop"

$RootDir = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RootDir

py -3 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe -m pip install -e .

$tesseract = Get-Command tesseract.exe -ErrorAction SilentlyContinue
if ($tesseract) {
    Write-Host "Tesseract detecte:" $tesseract.Source
    & tesseract --version | Select-Object -First 1
} else {
    Write-Host "Python est pret, mais Tesseract OCR n'est pas detecte."
    Write-Host "Installe Tesseract pour lire les PDF image-only."
    Write-Host "Option winget:"
    Write-Host "  winget install UB-Mannheim.TesseractOCR"
}
