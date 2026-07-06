#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON="${ROOT_DIR}/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  echo "Environnement .venv introuvable. Lance d'abord scripts/setup_mac.sh"
  exit 1
fi

export PYTHONPATH="${ROOT_DIR}/src:${PYTHONPATH:-}"
"$PYTHON" -m controldone.webapp "$@"
