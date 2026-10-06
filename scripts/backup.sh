#!/usr/bin/env bash
# Sauvegarde chiffrée de ControlDOne (base SQLite en ligne ou PostgreSQL par pg_dump + coffre + traces d'envoi,
# manifeste SHA-256),
# relecture complète de l'archive créée, puis rotation (7 jours, 4 semaines).
# Usage : scripts/backup.sh [--destination DIR] [--verification-profonde] [--sans-rotation]
# Vérification : controldone sauvegarde verifier --dernier --destination DIR [--profond]
# Restauration : controldone sauvegarde restaurer <archive> <répertoire_vide> --controler
#                (voir docs/EXPLOITATION.md § 3, deploy/README.md) ; exercice complet : make restauration-test
# Codes de retour : 0 succès, 1 création, 2 configuration, 3 vérification (voir deploy/backup-cron.sh).
# Variables : CONTROLDONE_MASTER_KEY (obligatoire en prod), CONTROLDONE_DATABASE_URL, CONTROLDONE_DATA_DIR.
set -euo pipefail
RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${CONTROLDONE_PYTHON:-$RACINE/.venv/bin/python}"
cd "$RACINE"
umask 077
exec "$PY" -m controldone.storage.sauvegarde sauvegarder "$@"
