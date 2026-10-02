# syntax=docker/dockerfile:1
# ControlDOne v2 — image d'exécution (web, worker, planificateur).
#
# Construction (depuis la racine du dépôt) :
#   docker build -f deploy/Dockerfile -t controldone:2.0.0 .
#
# - Base python:3.11-slim, utilisateur non root (uid 10001), aucune chaîne de compilation dans l'image finale
#   (toutes les dépendances sont des roues binaires ; l'étape « build » ne sert qu'à créer le venv).
# - Dépendances figées par requirements.lock (généré depuis le venv de développement : uv pip freeze).
# - Système de fichiers en lecture seule possible : seules /app/var (volume), /backups (volume) et /tmp (tmpfs)
#   sont écrits. Le bytecode est précompilé à la construction.
# - Installation « éditable » volontaire : config/ et ref/ sont lus relativement à la racine du dépôt
#   (controldone.config.RACINE_DEPOT), ici /app.

ARG PYTHON_IMAGE=python:3.11-slim

############################
# Étape 1 : venv + dépendances
############################
FROM ${PYTHON_IMAGE} AS build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /app
COPY requirements.lock ./
# --only-binary : refuse toute compilation (garantit l'absence d'outils de construction).
RUN pip install --only-binary=:all: -r requirements.lock

COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
COPY ref ./ref
COPY scripts/backup.sh ./scripts/backup.sh
COPY deploy/backup-cron.sh deploy/scheduler.sh ./deploy/
# Paquet lui-même sans dépendances (déjà figées ci-dessus), puis précompilation du bytecode.
RUN pip install --no-deps -e . \
 && python -m compileall -q /app/src /opt/venv/lib/python3.11/site-packages

############################
# Étape 2 : image finale
############################
FROM ${PYTHON_IMAGE} AS runtime

LABEL org.opencontainers.image.title="ControlDOne" \
      org.opencontainers.image.version="2.0.0" \
      org.opencontainers.image.description="Contrôle de cohérence des documents d'import (web, worker, planificateur)"

# OCR : tesseract + langues fra, eng et osd (orientation). Aucune recommandation, listes apt supprimées.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-fra tesseract-ocr-eng tesseract-ocr-osd \
        tini ca-certificates \
 && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*

RUN groupadd --system --gid 10001 controldone \
 && useradd --system --uid 10001 --gid controldone --home-dir /app --no-create-home --shell /usr/sbin/nologin controldone

COPY --from=build /opt/venv /opt/venv
COPY --from=build --chown=root:root /app /app

RUN mkdir -p /app/var /backups \
 && chown controldone:controldone /app/var /backups \
 && chmod 0700 /app/var /backups \
 && chmod 0755 /app/scripts/backup.sh /app/deploy/backup-cron.sh /app/deploy/scheduler.sh

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    CONTROLDONE_ENV=prod \
    CONTROLDONE_DATA_DIR=/app/var \
    CONTROLDONE_DATABASE_URL=sqlite:////app/var/controldone.db \
    CONTROLDONE_PYTHON=/opt/venv/bin/python \
    BACKUP_DIR=/backups

WORKDIR /app
USER controldone:controldone
VOLUME ["/app/var", "/backups"]
EXPOSE 8000

# Sonde de vie du service web (les services worker et scheduler la désactivent dans docker-compose.yml).
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/sante', timeout=4).status == 200 else 1)"]

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["controldone", "serve", "--host", "0.0.0.0", "--port", "8000", "--sans-worker", "--proxy", "--https", "--init-schema"]
