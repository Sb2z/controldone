#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

PYTHON="${ROOT_DIR}/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  echo "Creation de l'environnement Python local..."
  python3 -m venv .venv
  "$PYTHON" -m pip install --upgrade pip
  "$PYTHON" -m pip install -r requirements.txt
  "$PYTHON" -m pip install -e .
fi

if ! "$PYTHON" -c "import flask, cv2, numpy, controldone.webapp" >/dev/null 2>&1; then
  echo "Installation / mise a jour des dependances..."
  "$PYTHON" -m pip install --upgrade pip
  "$PYTHON" -m pip install -r requirements.txt
  "$PYTHON" -m pip install -e .
fi

export PYTHONPATH="${ROOT_DIR}/src:${PYTHONPATH:-}"

echo
echo "Serveur local: http://127.0.0.1:8765"
echo "Garde cette fenetre ouverte pendant l'utilisation."
echo "Pour arreter ControlDOne: CTRL+C"
echo

"$PYTHON" -m controldone.webapp --host 127.0.0.1 --port 8765 --open-browser
