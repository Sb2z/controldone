@echo off
setlocal

cd /d "%~dp0"
set "APP_URL=http://127.0.0.1:8765"
set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"
set "TESSERACT_DIR="

echo.
echo ==========================================
echo  ControlDOne - demarrage local Windows
echo ==========================================
echo.

if not exist "%PYTHON_EXE%" (
  echo Creation de l'environnement Python local...
  where py >nul 2>nul && ( py -3 -m venv .venv ) || ( python -m venv .venv )
  if errorlevel 1 (
    echo.
    echo ERREUR: Python 3 n'est pas detecte.
    echo Installe Python depuis https://www.python.org/downloads/ puis relance ce fichier.
    pause
    exit /b 1
  )
)

"%PYTHON_EXE%" -c "import flask, cv2, numpy, controldone.webapp" >nul 2>nul
if errorlevel 1 (
  echo Installation / mise a jour des dependances...
  "%PYTHON_EXE%" -m pip install --upgrade pip
  "%PYTHON_EXE%" -m pip install -r requirements.txt
  "%PYTHON_EXE%" -m pip install -e .
  if errorlevel 1 (
    echo.
    echo ERREUR: installation des dependances impossible.
    pause
    exit /b 1
  )
)

set "PYTHONPATH=%CD%\src;%PYTHONPATH%"

call :detect_tesseract
if not defined CONTROLDONE_TESSERACT_CMD (
  rem L'installateur n'est pas dans le repo GitHub (fichier trop volumineux) :
  rem on le telecharge une seule fois depuis le site officiel UB-Mannheim.
  if not exist "%CD%\setup\tesseract-ocr-w64-setup-*.exe" (
    echo.
    echo Telechargement de l'installateur Tesseract OCR officiel...
    if not exist "%CD%\setup" mkdir "%CD%\setup"
    curl -L --fail -o "%CD%\setup\tesseract-ocr-w64-setup-5.4.0.20240606.exe" "https://github.com/UB-Mannheim/tesseract/releases/download/v5.4.0.20240606/tesseract-ocr-w64-setup-5.4.0.20240606.exe"
    if errorlevel 1 (
      echo curl indisponible ou bloque, tentative via PowerShell...
      powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://github.com/UB-Mannheim/tesseract/releases/download/v5.4.0.20240606/tesseract-ocr-w64-setup-5.4.0.20240606.exe' -OutFile '%CD%\setup\tesseract-ocr-w64-setup-5.4.0.20240606.exe'"
    )
  )
  if exist "%CD%\setup\tesseract-ocr-w64-setup-*.exe" (
    echo.
    echo Tesseract OCR n'est pas installe sur ce PC.
    echo L'installateur fourni va s'ouvrir : laisse les choix par defaut
    echo et clique sur Suivant jusqu'a la fin, puis reviens ici.
    echo.
    pause
    for %%f in ("%CD%\setup\tesseract-ocr-w64-setup-*.exe") do start /wait "" "%%~ff"
    call :detect_tesseract
  )
)
if not defined CONTROLDONE_TESSERACT_CMD (
  echo.
  echo ATTENTION: Tesseract OCR n'est pas detecte.
  echo Les PDF image/scannes seront mal lus ou marques "a controler".
  echo Installe Tesseract avec le fichier du dossier setup\ puis relance,
  echo ou si winget est autorise:
  echo   winget install UB-Mannheim.TesseractOCR
  echo.
)

rem Langues OCR embarquees (francais inclus) : utilisables meme si
rem l'installation Tesseract du PC n'a pas le pack francais.
if exist "%CD%\setup\tessdata\fra.traineddata" (
  set "TESSDATA_PREFIX=%CD%\setup\tessdata"
  echo Langues OCR embarquees: %CD%\setup\tessdata
)
goto :tess_done

:detect_tesseract
where tesseract >nul 2>nul
if not errorlevel 1 (
  for /f "delims=" %%i in ('where tesseract') do (
    set "CONTROLDONE_TESSERACT_CMD=%%i"
    echo Tesseract detecte: %%i
    exit /b 0
  )
)
set "TESSERACT_DIR="
if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" set "TESSERACT_DIR=C:\Program Files\Tesseract-OCR"
if exist "C:\Program Files (x86)\Tesseract-OCR\tesseract.exe" set "TESSERACT_DIR=C:\Program Files (x86)\Tesseract-OCR"
if exist "%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe" set "TESSERACT_DIR=%LOCALAPPDATA%\Programs\Tesseract-OCR"
if defined TESSERACT_DIR (
  set "PATH=%TESSERACT_DIR%;%PATH%"
  set "CONTROLDONE_TESSERACT_CMD=%TESSERACT_DIR%\tesseract.exe"
  echo Tesseract detecte: %TESSERACT_DIR%\tesseract.exe
)
exit /b 0

:tess_done

echo.
echo Serveur local: %APP_URL%
echo Garde cette fenetre ouverte pendant l'utilisation.
echo Pour arreter ControlDOne: CTRL+C puis O.
echo.

"%PYTHON_EXE%" -m controldone.webapp --host 127.0.0.1 --port 8765 --open-browser

echo.
echo ControlDOne est arrete.
pause
