#!/usr/bin/env bash
# Sauvegarde ControlDOne pour la production. Deux modes :
#
#   deploy/backup-cron.sh [--si-absente | --si-absente-depuis HHMM]
#       (dans le conteneur, appelé deux fois par jour par deploy/scheduler.sh, D-4105 ; --si-absente : rien si
#        l'archive du jour existe déjà ; --si-absente-depuis HHMM : rien si une archive du jour date de HHMM ou après)
#       -> scripts/backup.sh --destination "$BACKUP_DIR" : archive chiffrée (clé dérivée de
#          CONTROLDONE_MASTER_KEY) de la base (SQLite : copie en ligne ; PostgreSQL : pg_dump sur instantané),
#          du coffre et des traces d'envoi, avec
#          manifeste (SHA-256 de chaque fichier) et empreinte .sha256 ; relecture complète de l'archive créée ;
#          restauration d'essai complète le jour BACKUP_VERIFICATION_PROFONDE_JOUR (une fois ce jour-là) ; puis
#          rotation : 4 plus récentes, 7 j, 4 sem.
#          Une archive dont la relecture échoue est renommée « .invalide » (le rattrapage la refait).
#
#   deploy/backup-cron.sh --hors-site   (sur l'hôte, crontab root, après la sauvegarde du jour)
#       -> contrôle que la dernière archive locale a moins de BACKUP_AGE_MAX_H heures et que son empreinte
#          .sha256 est conforme (sans la clé), puis rclone copy vers un stockage objet situé dans l'UE
#          (ex. Scaleway Object Storage fr-par, Hetzner Object Storage fsn1, OVHcloud gra) et rclone check.
#          Les archives sont déjà chiffrées : le stockage objet ne voit jamais de données en clair.
#          Exemple de crontab hôte :
#            45 2,14 * * * BACKUP_RCLONE_REMOTE=objeu:controldone-sauvegardes BACKUP_ALERTE_COMPOSE=/srv/controldone/app/deploy/docker-compose.yml /srv/controldone/app/deploy/backup-cron.sh --hors-site >> /var/log/controldone-backup.log 2>&1
#
# Codes de retour (D-3303) : 0 succès ; 1 création en échec ; 2 configuration (clé, pg_dump absent, rclone,
# distant) ; 3 vérification en échec (archive illisible, altérée, empreinte) ; 4 aucune sauvegarde récente ;
# 5 copie hors site en échec ; 6 contrôle de la copie hors site en échec.
#
# Alertes en cas d'échec :
#   - dans l'application : alerte fondateur (/admin/alertes) émise par le module Python (mode conteneur) ou,
#     en mode --hors-site, par « docker compose exec scheduler … alerter » si BACKUP_ALERTE_COMPOSE est défini ;
#   - hors de l'application (recommandé : détecte aussi une sauvegarde qui ne tourne plus du tout) :
#     BACKUP_PING_URL (sonde « homme mort » type Healthchecks, auto-hébergeable) reçoit <url>/0 en cas de
#     succès et <url>/<code> en cas d'échec ; période 12 h, grâce 2 h (deux sauvegardes par jour) : sans signal
#     pendant 14 h, la sonde alerte.
#
# Restauration : docs/DEPLOIEMENT.md (§ Test de restauration), docs/EXPLOITATION.md § 3.2, deploy/README.md.
set -euo pipefail
umask 077
ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RACINE="$(cd "$ICI/.." && pwd)"
horodatage() { date -u +%Y-%m-%dT%H:%M:%SZ; }

signaler() {  # signaler <code> : sonde externe facultative (ne fait jamais échouer le script)
  if [ -n "${BACKUP_PING_URL:-}" ] && command -v curl >/dev/null; then
    curl -fsS -m 10 --retry 3 -o /dev/null "${BACKUP_PING_URL%/}/$1" || echo "$(horodatage) sonde injoignable" >&2
  fi
  return 0
}

if [ "${1:-}" = "--hors-site" ]; then
  SOURCE="${BACKUP_HOST_DIR:-/srv/controldone/backups}"
  AGE_MAX_H="${BACKUP_AGE_MAX_H:-14}"   # deux sauvegardes par jour (RPO 12 h, D-4105) + 2 h de marge
  echec() {  # echec <code> <message> <kind>
    echo "$(horodatage) ÉCHEC hors site (code $1) : $2" >&2
    if [ -n "${BACKUP_ALERTE_COMPOSE:-}" ]; then
      docker compose -f "$BACKUP_ALERTE_COMPOSE" exec -T scheduler \
        python -m controldone.storage.sauvegarde alerter --kind "$3" --message "$2" >/dev/null 2>&1 \
        || echo "$(horodatage) alerte applicative non enregistrée" >&2
    fi
    signaler "$1"
    exit "$1"
  }
  [ -n "${BACKUP_RCLONE_REMOTE:-}" ] || echec 2 "BACKUP_RCLONE_REMOTE non défini (ex. objeu:controldone-sauvegardes)" sauvegarde_hors_site_echec
  command -v rclone >/dev/null || echec 2 "rclone absent : apt install rclone" sauvegarde_hors_site_echec
  # 1. Fraîcheur de la dernière archive locale : contrôle indépendant du conteneur scheduler.
  DERNIERE="$(find "$SOURCE" -maxdepth 1 -name 'controldone-*.tar.gz.enc' -printf '%f\n' 2>/dev/null | sort | tail -n 1 || true)"
  [ -n "$DERNIERE" ] || echec 4 "aucune sauvegarde locale dans $SOURCE" sauvegarde_absente
  AGE_S=$(( $(date +%s) - $(stat -c %Y "$SOURCE/$DERNIERE") ))
  [ "$AGE_S" -le $(( AGE_MAX_H * 3600 )) ] \
    || echec 4 "dernière sauvegarde locale ($DERNIERE) vieille de $(( AGE_S / 3600 )) h (> $AGE_MAX_H h)" sauvegarde_absente
  # 2. Empreinte de l'archive chiffrée (aucune clé nécessaire).
  if [ -f "$SOURCE/$DERNIERE.sha256" ]; then
    (cd "$SOURCE" && sha256sum -c --status "$DERNIERE.sha256") \
      || echec 3 "empreinte de $DERNIERE non conforme (archive altérée)" sauvegarde_verification_echec
  fi
  # 3. Copie (et non sync) : une suppression locale (rotation) n'efface rien à distance ; la durée de conservation
  #    distante est réglée par une règle de cycle de vie du compartiment (ex. 35 jours).
  echo "$(horodatage) copie hors site : $SOURCE -> $BACKUP_RCLONE_REMOTE"
  FILTRES=(--include 'controldone-*.tar.gz.enc' --include 'controldone-*.tar.gz.enc.sha256')
  rclone copy "$SOURCE" "$BACKUP_RCLONE_REMOTE" "${FILTRES[@]}" --immutable --checksum \
    || echec 5 "rclone copy vers $BACKUP_RCLONE_REMOTE en échec" sauvegarde_hors_site_echec
  # 4. Contrôle : chaque archive locale est présente à distance avec le même contenu.
  rclone check "$SOURCE" "$BACKUP_RCLONE_REMOTE" "${FILTRES[@]}" --one-way \
    || echec 6 "rclone check : copie distante incomplète ou différente" sauvegarde_hors_site_echec
  echo "$(horodatage) copie hors site terminée et contrôlée ($DERNIERE)"
  signaler 0
  exit 0
fi

DEST="${BACKUP_DIR:-$RACINE/var/sauvegardes}"
mkdir -p "$DEST"
# --si-absente (planificateur) : rien à faire si l'archive du jour (UTC) existe déjà (rattrapage au redémarrage).
# --si-absente-depuis HHMM (planificateur, plusieurs sauvegardes par jour, D-4105) : rien à faire si une archive
# a été créée aujourd'hui (UTC) à HHMM ou après (créneau déjà couvert).
if [ "${1:-}" = "--si-absente" ]; then
  if compgen -G "$DEST/controldone-$(date -u +%Y%m%d)T*.tar.gz.enc" >/dev/null; then
    echo "$(horodatage) sauvegarde du jour déjà présente : rien à faire"
    exit 0
  fi
  shift
elif [ "${1:-}" = "--si-absente-depuis" ]; then
  CRENEAU="${2:-}"
  [[ "$CRENEAU" =~ ^[0-2][0-9][0-5][0-9]$ ]] || { echo "--si-absente-depuis HHMM attendu" >&2; exit 2; }
  SEUIL="controldone-$(date -u +%Y%m%d)T${CRENEAU}00Z.tar.gz.enc"
  for archive in "$DEST"/controldone-"$(date -u +%Y%m%d)"T*.tar.gz.enc; do
    [ -e "$archive" ] || continue
    nom="$(basename "$archive")"
    if [[ ! "$nom" < "$SEUIL" ]]; then
      echo "$(horodatage) sauvegarde du créneau ${CRENEAU} déjà présente ($nom) : rien à faire"
      exit 0
    fi
  done
  shift 2
fi
# Restauration d'essai complète un jour par semaine (1 = lundi … 7 = dimanche ; 0 = jamais ; « tous »).
OPTIONS=()
JOUR_PROFOND="${BACKUP_VERIFICATION_PROFONDE_JOUR:-7}"
# (le jour venu, seulement la première sauvegarde du jour : deux sauvegardes par jour, D-4105)
if [ "$JOUR_PROFOND" = "tous" ] || { [ "$JOUR_PROFOND" = "$(date -u +%u)" ] \
     && ! compgen -G "$DEST/controldone-$(date -u +%Y%m%d)T*.tar.gz.enc" >/dev/null; }; then
  OPTIONS+=(--verification-profonde)
fi
echo "$(horodatage) sauvegarde -> $DEST ${OPTIONS[*]:-}"
code=0
"$RACINE/scripts/backup.sh" --destination "$DEST" "${OPTIONS[@]}" || code=$?
if [ "$code" -ne 0 ]; then
  echo "$(horodatage) ÉCHEC de la sauvegarde (code $code) — alerte fondateur émise, voir /admin/alertes" >&2
  signaler "$code"
  exit "$code"
fi
echo "$(horodatage) sauvegarde terminée"
signaler 0
