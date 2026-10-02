#!/usr/bin/env bash
# Démonstration complète de ControlDOne en une commande (DONNÉES FICTIVES) :
#   1. installe l'environnement si besoin (.venv + paquet éditable) ;
#   2. controldone demo       -> rapport HTML/PDF dans var/demo/ ;
#   3. controldone init-demo  -> base neuve var/demo_web/ (fondateur + 2 clients fictifs, dossiers traités) ;
#   4. lance l'interface web sur http://127.0.0.1:${PORT:-8000} avec le worker intégré (Ctrl-C pour arrêter).
#
# Usage : scripts/demo_complete.sh            (ou make demo-complete)
#         scripts/demo_complete.sh --sans-serveur   (étapes 1 à 3 seulement)
#         scripts/demo_complete.sh totp             (code TOTP courant du fondateur de démonstration)
# Variables : PORT (défaut 8000), HOST (défaut 127.0.0.1).
set -euo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RACINE"
VENV="$RACINE/.venv"
PY="$VENV/bin/python"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
DEMO_WEB="$RACINE/var/demo_web"
IDENTIFIANTS="$DEMO_WEB/identifiants.txt"

titre() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }

if [ "${1:-}" = "totp" ]; then
  secret=$(sed -n 's/^  secret TOTP  : //p' "$IDENTIFIANTS" 2>/dev/null || true)
  [ -n "$secret" ] || { echo "Aucun secret : lancer d'abord scripts/demo_complete.sh" >&2; exit 1; }
  exec "$PY" -c "import sys; from controldone.auth import code_totp; print(code_totp(sys.argv[1]))" "$secret"
fi

# --- 1. Installation ------------------------------------------------------------------------------------
titre "1/4 Environnement"
if [ ! -x "$PY" ]; then
  echo "Création de .venv"
  if command -v uv >/dev/null; then uv venv --python 3.11 "$VENV"; else python3.11 -m venv "$VENV" || python3 -m venv "$VENV"; fi
fi
if ! "$PY" -c "import controldone, fastapi, uvicorn, pdfplumber" 2>/dev/null; then
  echo "Installation des dépendances (requirements.lock + paquet éditable)"
  if command -v uv >/dev/null; then
    uv pip install --python "$PY" -r requirements.lock && uv pip install --python "$PY" --no-deps -e .
  else
    "$PY" -m pip install -r requirements.lock && "$PY" -m pip install --no-deps -e .
  fi
fi
command -v tesseract >/dev/null || echo "Avertissement : tesseract absent (OCR des scans indisponible ; apt install tesseract-ocr tesseract-ocr-fra)."
echo "Python : $("$PY" --version)  —  dépôt : $RACINE"

# --- 2. Rapport de démonstration -----------------------------------------------------------------------
titre "2/4 Rapport de démonstration (controldone demo)"
"$PY" -m controldone.cli demo --out var/demo

# --- 3. Base web de démonstration ------------------------------------------------------------------------
titre "3/4 Base web de démonstration (controldone init-demo, base neuve)"
export CONTROLDONE_ENV=dev
export CONTROLDONE_DATA_DIR="$DEMO_WEB"
export CONTROLDONE_DATABASE_URL="sqlite:///$DEMO_WEB/controldone.db"
mkdir -p "$DEMO_WEB"
umask 077
"$PY" -W ignore::UserWarning -m controldone.cli init-demo --force > "$IDENTIFIANTS"
umask 022
echo "Identifiants enregistrés dans $IDENTIFIANTS (droits 0600)."

fondateur_email=$(sed -n 's/^  adresse      : //p' "$IDENTIFIANTS")
fondateur_mdp=$(sed -n 's/^  mot de passe : //p' "$IDENTIFIANTS")
totp_secret=$(sed -n 's/^  secret TOTP  : //p' "$IDENTIFIANTS")
client_ligne=$(grep -m1 ' client_admin ' "$IDENTIFIANTS" | sed 's/^ *//')
client_email=$(awk '{print $1}' <<<"$client_ligne")
client_mdp=$(awk '{print $2}' <<<"$client_ligne")

# --- 4. Résumé + serveur -------------------------------------------------------------------------------
titre "4/4 Démonstration prête — DONNÉES FICTIVES"
cat <<EOF
Rapport (controldone demo) :
  PDF   $RACINE/var/demo/report.pdf
  HTML  $RACINE/var/demo/report.html

Interface web : http://$HOST:$PORT/connexion

Fondateur (espace /admin, mot de passe + code TOTP) :
  adresse       $fondateur_email
  mot de passe  $fondateur_mdp
  secret TOTP   $totp_secret   (aussi dans $IDENTIFIANTS)
  code courant  scripts/demo_complete.sh totp   (ou ajouter le secret dans une application TOTP)

Client fictif (espace /espace) :
  adresse       $client_email
  mot de passe  $client_mdp
  (autres comptes : $IDENTIFIANTS)

API : http://$HOST:$PORT/api/v1/openapi.json (clé d'API à créer dans la fiche client du fondateur)
EOF

if [ "${1:-}" = "--sans-serveur" ]; then
  echo; echo "Serveur non lancé (--sans-serveur). Pour le lancer : make serve-demo"
  exit 0
fi
if "$PY" -c "import socket,sys; s=socket.socket(); sys.exit(0 if s.connect_ex(('$HOST', $PORT)) == 0 else 1)"; then
  echo "Le port $PORT est déjà utilisé : arrêter l'autre serveur ou relancer avec PORT=8001." >&2
  exit 1
fi
echo; echo "Serveur web + worker intégré sur http://$HOST:$PORT/ — Ctrl-C pour arrêter."
exec "$PY" -W ignore::UserWarning -m controldone.cli serve --host "$HOST" --port "$PORT"
