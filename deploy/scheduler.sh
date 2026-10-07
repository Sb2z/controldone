#!/usr/bin/env bash
# Planificateur « façon cron » du conteneur scheduler (docker-compose.yml) : une seule boucle, pas de démon cron.
#
#   toutes les 5 min    python -m controldone.connecteurs.releve        (dossier surveillé, IMAP, PA)
#   toutes les 15 min   python -m controldone.agents.planificateur      (met en file les jobs d'agents)
#   toutes les 5 min    controldone alertes notifier                     (notifications poussées, D-3502 :
#                       sans effet si aucun canal n'est configuré ; une par type d'alerte et par jour)
#   deux fois par jour  sauvegarde chiffrée vérifiée (deploy/backup-cron.sh) aux heures de SCHED_BACKUP_HHMM (défaut
#                       « 0215 1415 » : RPO 12 h, D-4105), puis mise en file de purger_retention (une fois par jour)
#   chaque mois         mise en file de referentiel_recalculer, à partir du 2 (clé d'idempotence mensuelle :
#                       rattrapé si le conteneur était arrêté le 2, jamais deux fois dans le mois)
#   premier dimanche    exercice mensuel sur la dernière vraie archive (controldone sauvegarde exercice-mensuel,
#   du mois             D-4702) à SCHED_EXERCICE_HHMM (défaut 0445 UTC, après la sauvegarde de 02:15) :
#                       DÉSACTIVÉ PAR DÉFAUT (SCHED_EXERCICE_MENSUEL=1 pour l'activer ; demande l'espace disque
#                       d'une copie des données dans BACKUP_DIR). Une fois par mois : rien si un compte rendu du
#                       mois existe déjà dans <data_dir>/exercices (redémarrage du conteneur).
#
# Les tâches ne font que mettre en file (clés d'idempotence par période) : c'est le worker qui exécute.
# Un échec est journalisé et n'arrête jamais la boucle. SIGTERM / SIGINT : arrêt propre.
# Créneau de sauvegarde = la plus récente des heures de SCHED_BACKUP_HHMM déjà passée aujourd'hui. Au démarrage
# (ou après un arrêt), la sauvegarde du créneau en cours est faite aussitôt (rattrapage) **si elle n'existe pas
# déjà** (backup-cron.sh --si-absente-depuis HHMM : un redémarrage du conteneur ne la refait pas).
# Heures UTC. Réglages : SCHED_BACKUP_HHMM (une ou plusieurs heures HHMM séparées par des espaces ou des virgules,
# défaut « 0215,1415 »), SCHED_TICK_S (défaut 60).
set -uo pipefail

BACKUP_HHMM="${SCHED_BACKUP_HHMM:-0215,1415}"
CRENEAUX=()
for h in ${BACKUP_HHMM//,/ }; do
  if [[ "$h" =~ ^([01][0-9]|2[0-3])[0-5][0-9]$ ]]; then CRENEAUX+=("$h"); else echo "SCHED_BACKUP_HHMM : « $h » ignoré (HHMM attendu)" >&2; fi
done
[ "${#CRENEAUX[@]}" -gt 0 ] || CRENEAUX=(0215 1415)
mapfile -t CRENEAUX < <(printf '%s\n' "${CRENEAUX[@]}" | sort -u)

creneau_courant() {  # creneau_courant <hhmm> : plus récente heure de sauvegarde déjà passée aujourd'hui (ou vide)
  local c dernier=""
  for c in "${CRENEAUX[@]}"; do [[ ! "$1" < "$c" ]] && dernier="$c"; done
  printf '%s' "$dernier"
}
TICK="${SCHED_TICK_S:-60}"
EXERCICE_MENSUEL="${SCHED_EXERCICE_MENSUEL:-0}"
EXERCICE_HHMM="${SCHED_EXERCICE_HHMM:-0445}"
[[ "$EXERCICE_HHMM" =~ ^([01][0-9]|2[0-3])[0-5][0-9]$ ]] || EXERCICE_HHMM=0445
RAPPORTS_EXERCICE="${CONTROLDONE_DATA_DIR:-/app/var}/exercices"
ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${CONTROLDONE_PYTHON:-python}"

log() { printf '{"ts":"%s","evenement":"%s","detail":"%s"}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "${2:-}"; }

tache() {  # tache <nom> <commande…>
  local nom="$1"; shift
  if "$@" >/tmp/sched_"$nom".log 2>&1; then
    log "tache_ok" "$nom"
  else
    log "tache_echec" "$nom (code $?)"
    tail -n 5 /tmp/sched_"$nom".log | sed 's/^/  /' >&2 || true
  fi
}

arret=0
# (jamais « kill 0 » : sans attente en cours, aucun processus à réveiller — kill 0 viserait tout le groupe)
trap 'arret=1; log "arret_demande"; [ -n "${dormeur:-}" ] && kill "$dormeur" 2>/dev/null; true' TERM INT

log "demarrage" "sauvegardes a ${CRENEAUX[*]} UTC"
[ "$EXERCICE_MENSUEL" = "1" ] && log "exercice_mensuel" "premier dimanche du mois a ${EXERCICE_HHMM} UTC"
dernier_releve="" ; dernier_plan="" ; dernier_creneau="" ; dernier_mois="" ; dernier_exercice=""

while [ "$arret" -eq 0 ]; do
  minute=$(date -u +%M); hhmm=$(date -u +%H%M); jour=$(date -u +%Y-%m-%d); mois=$(date -u +%Y-%m); jdm=$(date -u +%d)
  cle5="${jour}T${hhmm:0:2}-$(( 10#$minute / 5 ))"
  cle15="${jour}T${hhmm:0:2}-$(( 10#$minute / 15 ))"

  if [ "$cle5" != "$dernier_releve" ]; then
    dernier_releve="$cle5"
    tache releve "$PY" -m controldone.connecteurs.releve
    tache notifications "$PY" -m controldone.cli alertes notifier
  fi
  if [ "$cle15" != "$dernier_plan" ]; then
    dernier_plan="$cle15"
    tache planificateur "$PY" -m controldone.agents.planificateur
  fi
  creneau="$(creneau_courant "$hhmm")"
  if [[ -n "$creneau" && "${jour}-${creneau}" != "$dernier_creneau" ]]; then
    dernier_creneau="${jour}-${creneau}"
    # sauvegarde d'abord, purge ensuite : la purge (exécutée par le worker) ne retire pas du coffre, pendant la
    # copie, un contenu que l'instantané de la base référence encore (D-3306). Une purge lancée à la main pendant
    # la copie est reportée par le verrou de maintenance partagé (D-3504).
    tache sauvegarde "$ICI/backup-cron.sh" --si-absente-depuis "$creneau"
    tache notifications "$PY" -m controldone.cli alertes notifier   # échec de sauvegarde : notifié aussitôt
    tache purge "$PY" -c "from datetime import date; from controldone.jobs import enqueue; enqueue('purger_retention', {}, f'purger_retention:{date.today()}')"
  fi
  if [[ "$mois" != "$dernier_mois" ]] && { (( 10#$jdm > 2 )) || [[ "$jdm" == "02" && ! "$hhmm" < "0300" ]]; }; then
    dernier_mois="$mois"
    tache referentiel "$PY" -c "from controldone.jobs import enqueue; enqueue('referentiel_recalculer', {}, 'referentiel:${mois}')"
  fi
  # premier dimanche du mois (jour 1 à 7, %u = 7), à partir de EXERCICE_HHMM ; une fois par mois (D-4702)
  if [[ "$EXERCICE_MENSUEL" == "1" && "$mois" != "$dernier_exercice" && "$(date -u +%u)" == "7" ]] \
     && (( 10#$jdm <= 7 )) && [[ ! "$hhmm" < "$EXERCICE_HHMM" ]]; then
    dernier_exercice="$mois"
    if ! compgen -G "$RAPPORTS_EXERCICE/exercice-mensuel-${mois//-/}*.json" >/dev/null; then
      tache exercice_mensuel "$PY" -m controldone.cli sauvegarde exercice-mensuel --source "${BACKUP_DIR:-/backups}" \
        --rapports "$RAPPORTS_EXERCICE"
      tache notifications "$PY" -m controldone.cli alertes notifier   # exercice en échec : notifié aussitôt
    fi
  fi

  [ "$arret" -eq 0 ] || break   # arrêt demandé pendant une tâche : ne pas repartir pour une attente complète
  sleep "$TICK" & dormeur=$!
  wait "$dormeur" 2>/dev/null || true
done
log "arret"
