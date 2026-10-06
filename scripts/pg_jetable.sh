#!/usr/bin/env bash
# Serveur PostgreSQL JETABLE pour l'exercice de restauration et les tests (D-3501) — jamais un service système.
#
#   scripts/pg_jetable.sh demarrer [répertoire] [port]   -> affiche l'URL d'administration (postgresql+pg8000://…)
#   scripts/pg_jetable.sh arreter  [répertoire]          -> arrête le serveur et efface le répertoire
#
# Grappe créée par initdb dans un répertoire temporaire (défaut /tmp/cd-pg-jetable), écoute sur 127.0.0.1
# seulement (défaut port 55432), authentification « trust » locale, UTF-8. Lancé en root (conteneur), il tourne
# sous l'utilisateur « postgres » (initdb refuse root). Binaires : PG_BIN (défaut : /usr/lib/postgresql/<max>/bin).
set -euo pipefail
action="${1:-}"; DIR="${2:-/tmp/cd-pg-jetable}"; PORT="${3:-55432}"
if [ -z "${PG_BIN:-}" ]; then
  PG_BIN="$(ls -d /usr/lib/postgresql/*/bin 2>/dev/null | sort -V | tail -n 1 || true)"
fi
[ -x "${PG_BIN:-}/initdb" ] || { echo "initdb introuvable (installer postgresql, ou définir PG_BIN)" >&2; exit 2; }
en_tant_que() {
  if [ "$(id -u)" = "0" ]; then runuser -u postgres -- "$@"; else "$@"; fi
}
case "$action" in
  demarrer)
    if [ -f "$DIR/data/postmaster.pid" ]; then
      echo "postgresql+pg8000://cd@127.0.0.1:$PORT/postgres"; exit 0
    fi
    rm -rf "$DIR"; mkdir -p "$DIR"; chmod 700 "$DIR"
    [ "$(id -u)" = "0" ] && chown postgres "$DIR"
    en_tant_que "$PG_BIN/initdb" -D "$DIR/data" -A trust -U cd -E UTF8 --locale=C.UTF-8 --no-sync >/dev/null
    en_tant_que "$PG_BIN/pg_ctl" -D "$DIR/data" -l "$DIR/journal" -w \
      -o "-p $PORT -k $DIR -c listen_addresses=127.0.0.1 -c fsync=off" start >/dev/null
    echo "postgresql+pg8000://cd@127.0.0.1:$PORT/postgres"
    ;;
  arreter)
    if [ -f "$DIR/data/postmaster.pid" ]; then
      en_tant_que "$PG_BIN/pg_ctl" -D "$DIR/data" -m fast -w stop >/dev/null || true
    fi
    rm -rf "$DIR"
    ;;
  *) echo "usage : $0 demarrer|arreter [répertoire] [port]" >&2; exit 2 ;;
esac
