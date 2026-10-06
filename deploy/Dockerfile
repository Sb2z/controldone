# syntax=docker/dockerfile:1
# ControlDOne v2 — image d'exécution (web, worker, planificateur).
#
# Construction (depuis la racine du dépôt) :
#   docker build -f deploy/Dockerfile -t controldone:2.0.0 .
#
# - Base python:3.11-slim, utilisateur non root (uid 10001), aucune chaîne de compilation dans l'image finale
#   (toutes les dépendances sont des roues binaires ; l'étape « build » ne sert qu'à créer le venv).
# - Dépendances figées **avec empreintes** (requirements.lock, D-3609) et installées par « pip --require-hashes » ;
#   le backend de construction du paquet (hatchling) aussi (deploy/requirements-build.lock), dans un environnement
#   séparé de l'étape « build » : aucun téléchargement non vérifié, aucun outil de construction dans l'image.
# - Système de fichiers en lecture seule possible : seules /app/var (volume), /backups (volume) et /tmp (tmpfs)
#   sont écrits. Le bytecode est précompilé à la construction.
# - Pilote PostgreSQL pg8000 (extra « postgres ») figé dans requirements.lock ; client PostgreSQL
#   (pg_dump / pg_restore, version majeure PG_CLIENT_MAJOR, défaut 16) pour la sauvegarde PostgreSQL (D-4101) :
#   docker build --build-arg PG_CLIENT_MAJOR=17 … pour un serveur 17.
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
COPY requirements.lock deploy/requirements-build.lock ./
# --only-binary : refuse toute compilation (garantit l'absence d'outils de construction).
# --require-hashes : chaque archive téléchargée doit avoir l'empreinte figée (version republiée, miroir altéré).
RUN pip install --only-binary=:all: --require-hashes -r requirements.lock \
 && python -m venv /opt/construction \
 && /opt/construction/bin/pip install --only-binary=:all: --require-hashes -r requirements-build.lock

COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
COPY ref ./ref
COPY scripts/backup.sh ./scripts/backup.sh
COPY deploy/backup-cron.sh deploy/scheduler.sh ./deploy/
# Paquet lui-même sans dépendances (déjà figées ci-dessus) avec le backend figé de /opt/construction (pas
# d'environnement de construction téléchargé), puis précompilation du bytecode. /opt/construction reste dans cette
# étape : l'image finale ne copie que /opt/venv et /app. pip et setuptools sont ensuite retirés du venv : inutiles à
# l'exécution (le paquet est relié par un simple .pth) et porteurs de copies anciennes de wheel / jaraco.context
# signalées par l'audit de l'image (make audit-image, D-3609).
RUN PYTHONPATH=/opt/construction/lib/python3.11/site-packages pip install --no-deps --no-build-isolation -e . \
 && pip uninstall -y -q setuptools pip \
 && python -m compileall -q /app/src /opt/venv/lib/python3.11/site-packages

############################
# Étape 2 : image finale
############################
FROM ${PYTHON_IMAGE} AS runtime

LABEL org.opencontainers.image.title="ControlDOne" \
      org.opencontainers.image.version="2.0.0" \
      org.opencontainers.image.description="Contrôle de cohérence des documents d'import (web, worker, planificateur)"

# Version majeure du client PostgreSQL (pg_dump / pg_restore) : celle du SERVEUR de production (pg_dump refuse
# un serveur plus récent que lui). Vide = image sans client PostgreSQL (SQLite seulement). Paquet du dépôt officiel
# PGDG (apt.postgresql.org), authentifié par sa clé versionnée dans deploy/pgdg.asc (empreinte vérifiée
# B97B 0AFC AA1A 47F0 44F2 44A0 7FCC 7D46 ACCC 4CF8) : aucune clé téléchargée à la construction (D-4101).
ARG PG_CLIENT_MAJOR=16
COPY deploy/pgdg.asc /usr/share/keyrings/pgdg.asc

# OCR : tesseract + langues fra, eng et osd (orientation) ; client PostgreSQL (sauvegarde, D-3501).
# Aucune recommandation, listes apt supprimées.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-fra tesseract-ocr-eng tesseract-ocr-osd \
        tini ca-certificates \
 && if [ -n "${PG_CLIENT_MAJOR}" ]; then \
        . /etc/os-release \
     && echo "deb [signed-by=/usr/share/keyrings/pgdg.asc] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" \
          > /etc/apt/sources.list.d/pgdg.list \
     && apt-get update \
     && apt-get install -y --no-install-recommends "postgresql-client-${PG_CLIENT_MAJOR}" \
     && ln -s "/usr/lib/postgresql/${PG_CLIENT_MAJOR}/bin" /usr/lib/postgresql/client-bin \
     && /usr/lib/postgresql/client-bin/pg_dump --version; \
    fi \
 && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/* \
 && python -m pip uninstall -y -q setuptools wheel pip
# (pip, setuptools et wheel de l'interpréteur de base retirés : aucun gestionnaire de paquets Python à l'exécution,
# et plus de copies vendues vulnérables ; D-3609.)

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
    CONTROLDONE_PG_DUMP=/usr/lib/postgresql/client-bin/pg_dump \
    CONTROLDONE_PG_RESTORE=/usr/lib/postgresql/client-bin/pg_restore \
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
