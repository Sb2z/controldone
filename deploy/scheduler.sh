#!/usr/bin/env bash
# Planificateur « façon cron » du conteneur scheduler (docker-compose.yml) : une seule boucle, pas de démon cron.
#
#   toutes les 5 min    python -m controldone.connecteurs.releve        (dossier surveillé, IMAP, PA)
#   toutes les 15 min   python -m controldone.agents.planificateur      (met en file les jobs d'agents)
#   chaque jour         mise en file de purger_retention + sauvegarde chiffrée (deploy/backup-cron.sh)
#   chaque mois         mise en file de referentiel_recalculer, à partir du 2 (clé d'idempotence mensuelle :
#                       rattrapé si le conteneur était arrêté le 2, jamais deux fois dans le mois)
#
# Les tâches ne font que mettre en file (clés d'idempotence par période) : c'est le worker qui exécute.
# Un échec est journalisé et n'arrête jamais la boucle. SIGTERM / SIGINT : arrêt propre.
# Au démarrage après l'heure prévue, la sauvegarde du jour est faite aussitôt (rattrapage) **si elle n'existe
# pas déjà** (backup-cron.sh --si-absente : un redémarrage du conteneur ne refait pas la sauvegarde du jour).
# Heure UTC. Réglages : SCHED_BACKUP_HHMM (défaut 0215), SCHED_TICK_S (défaut 60).
set -uo pipefail

BACKUP_HHMM="${SCHED_BACKUP_HHMM:-0215}"
TICK="${SCHED_TICK_S:-60}"
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
trap 'arret=1; log "arret_demande"; kill "${dormeur:-0}" 2>/dev/null || true' TERM INT

log "demarrage" "sauvegarde quotidienne a ${BACKUP_HHMM} UTC"
dernier_releve="" ; dernier_plan="" ; dernier_jour="" ; dernier_mois=""

while [ "$arret" -eq 0 ]; do
  minute=$(date -u +%M); hhmm=$(date -u +%H%M); jour=$(date -u +%Y-%m-%d); mois=$(date -u +%Y-%m); jdm=$(date -u +%d)
  cle5="${jour}T${hhmm:0:2}-$(( 10#$minute / 5 ))"
  cle15="${jour}T${hhmm:0:2}-$(( 10#$minute / 15 ))"

  if [ "$cle5" != "$dernier_releve" ]; then
    dernier_releve="$cle5"
    tache releve "$PY" -m controldone.connecteurs.releve
  fi
  if [ "$cle15" != "$dernier_plan" ]; then
    dernier_plan="$cle15"
    tache planificateur "$PY" -m controldone.agents.planificateur
  fi
  if [[ "$jour" != "$dernier_jour" && ! "$hhmm" < "$BACKUP_HHMM" ]]; then
    dernier_jour="$jour"
    tache purge "$PY" -c "from datetime import date; from controldone.jobs import enqueue; enqueue('purger_retention', {}, f'purger_retention:{date.today()}')"
    tache sauvegarde "$ICI/backup-cron.sh" --si-absente
  fi
  if [[ "$mois" != "$dernier_mois" ]] && { (( 10#$jdm > 2 )) || [[ "$jdm" == "02" && ! "$hhmm" < "0300" ]]; }; then
    dernier_mois="$mois"
    tache referentiel "$PY" -c "from controldone.jobs import enqueue; enqueue('referentiel_recalculer', {}, 'referentiel:${mois}')"
  fi

  sleep "$TICK" & dormeur=$!
  wait "$dormeur" 2>/dev/null || true
done
log "arret"
