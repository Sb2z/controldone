#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install -e .

if command -v tesseract >/dev/null 2>&1; then
  echo "Tesseract deja installe: $(command -v tesseract)"
  tesseract --version | head -n 1
  exit 0
fi

if command -v brew >/dev/null 2>&1; then
  brew install tesseract tesseract-lang
  exit 0
fi

cat <<'MSG'
Python est pret, mais Tesseract OCR n'est pas installe.

Pour activer l'OCR des PDF image-only, installe Homebrew puis Tesseract :

  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  brew install tesseract tesseract-lang

Ces commandes peuvent demander le mot de passe administrateur du Mac.
MSG
