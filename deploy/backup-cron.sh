#!/usr/bin/env bash
# Sauvegarde ControlDOne pour la production. Deux modes :
#
#   deploy/backup-cron.sh [--si-absente] (dans le conteneur, appelé chaque jour par deploy/scheduler.sh ;
#                                        --si-absente : rien si l'archive du jour existe déjà)
#       -> scripts/backup.sh --destination "$BACKUP_DIR" : archive chiffrée (clé dérivée de
#          CONTROLDONE_MASTER_KEY) de la base SQLite (copie en ligne) et du coffre, puis rotation 7 j / 4 sem.
#
#   deploy/backup-cron.sh --hors-site   (sur l'hôte, crontab root, après la sauvegarde du jour)
#       -> rclone copy "$BACKUP_HOST_DIR" "$BACKUP_RCLONE_REMOTE" : copie hors machine vers un stockage objet
#          situé dans l'UE (ex. Scaleway Object Storage fr-par, Hetzner Object Storage fsn1, OVHcloud gra).
#          Les archives sont déjà chiffrées : le stockage objet ne voit jamais de données en clair.
#          Exemple de crontab hôte :
#            45 2 * * * BACKUP_RCLONE_REMOTE=objeu:controldone-sauvegardes /srv/controldone/app/deploy/backup-cron.sh --hors-site >> /var/log/controldone-backup.log 2>&1
#
# Restauration : docs/DEPLOIEMENT.md (§ Test de restauration) et docs/EXPLOITATION.md § 3.2.
set -euo pipefail
umask 077
ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RACINE="$(cd "$ICI/.." && pwd)"
horodatage() { date -u +%Y-%m-%dT%H:%M:%SZ; }

if [ "${1:-}" = "--hors-site" ]; then
  SOURCE="${BACKUP_HOST_DIR:-/srv/controldone/backups}"
  : "${BACKUP_RCLONE_REMOTE:?définir BACKUP_RCLONE_REMOTE (ex. objeu:controldone-sauvegardes), voir docs/DEPLOIEMENT.md}"
  command -v rclone >/dev/null || { echo "rclone absent : apt install rclone" >&2; exit 2; }
  echo "$(horodatage) copie hors site : $SOURCE -> $BACKUP_RCLONE_REMOTE"
  # copy (et non sync) : une suppression locale (rotation) n'efface rien à distance ; la durée de conservation
  # distante est réglée par une règle de cycle de vie du compartiment (ex. 35 jours).
  rclone copy "$SOURCE" "$BACKUP_RCLONE_REMOTE" --include 'controldone-*.tar.gz.enc' --immutable --checksum
  echo "$(horodatage) copie hors site terminée"
  exit 0
fi

DEST="${BACKUP_DIR:-$RACINE/var/sauvegardes}"
mkdir -p "$DEST"
# --si-absente (planificateur) : rien à faire si l'archive du jour (UTC) existe déjà (rattrapage au redémarrage)
if [ "${1:-}" = "--si-absente" ]; then
  if compgen -G "$DEST/controldone-$(date -u +%Y%m%d)T*.tar.gz.enc" >/dev/null; then
    echo "$(horodatage) sauvegarde du jour déjà présente : rien à faire"
    exit 0
  fi
  shift
fi
echo "$(horodatage) sauvegarde -> $DEST"
"$RACINE/scripts/backup.sh" --destination "$DEST"
echo "$(horodatage) sauvegarde terminée"
