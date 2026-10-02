#!/usr/bin/env bash
# Sauvegarde chiffrée de ControlDOne (base SQLite en ligne + coffre), puis rotation (7 jours, 4 semaines).
# Usage : scripts/backup.sh [--destination DIR]
# Restauration : python -m controldone.storage.sauvegarde restaurer <archive> <répertoire_cible>
#                (voir docs/EXPLOITATION.md)
# Variables : CONTROLDONE_MASTER_KEY (obligatoire en prod), CONTROLDONE_DATABASE_URL, CONTROLDONE_DATA_DIR.
set -euo pipefail
RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${CONTROLDONE_PYTHON:-$RACINE/.venv/bin/python}"
cd "$RACINE"
umask 077
exec "$PY" -m controldone.storage.sauvegarde sauvegarder "$@"
