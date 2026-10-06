#!/bin/sh
# Lanceur des vérifications avant enregistrement (D-3901) : prend le Python du dépôt (.venv) s'il existe, sinon
# celui du PATH (CI). Aucun accès réseau : toutes les vérifications sont locales (.pre-commit-config.yaml).
set -e
racine=$(cd "$(dirname "$0")/../.." && pwd)
if [ -x "$racine/.venv/bin/python" ]; then py="$racine/.venv/bin/python"; else py=python3; fi
cmd=$1
shift
case "$cmd" in
  ruff) exec "$py" -m ruff check --force-exclude "$@" ;;
  *) exec "$py" "$racine/scripts/precommit/verifs.py" "$cmd" "$@" ;;
esac
