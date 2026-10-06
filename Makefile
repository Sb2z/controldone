# ControlDOne v2 — cibles de base (d'autres cibles seront ajoutées par les équipes).
VENV ?= .venv
PY := $(VENV)/bin/python

.PHONY: install test lint demo bench-dev serve-demo demo-complete diagnostic docker-build audit restauration-test restauration-test-pg audit-image lock test-pg-securite \
        hooks pre-commit couverture proprietes corpus corpus-g6 corpus-verifier

# Installation reproductible sur un clone neuf (F-17) : crée .venv s'il manque, installe les versions figées
# de requirements.lock, puis le paquet en mode éditable avec les outils de développement (pytest, ruff).
install:
	@test -x $(PY) || uv venv $(VENV)
	uv pip install --python $(PY) -r requirements.lock
	uv pip install --python $(PY) -e ".[dev]"

test:
	@$(PY) -c "import pytest" 2>/dev/null || $(MAKE) install
	$(PY) -m pytest -q

lint:
	$(VENV)/bin/ruff check src tests scripts

# --- Outillage (bloc O, D-3901–D-3904) -------------------------------------------------------------------------
# Vérifications avant enregistrement (.pre-commit-config.yaml, toutes locales, hors ligne) : `make hooks` installe
# le crochet git (à faire une fois, par choix du développeur) ; `make pre-commit` vérifie tout le dépôt.
hooks:
	$(VENV)/bin/pre-commit install
pre-commit:
	$(VENV)/bin/pre-commit run --all-files --show-diff-on-failure

# Couverture (coverage.py via pytest-cov, branches comprises) : résumé par paquet dans var/couverture/paquets.md,
# HTML dans var/couverture/html/. Base de référence : docs/QUALITE.md. COUV_MIN=… : taux global minimal.
COUV_MIN ?= 0
couverture:
	@mkdir -p var/couverture
	@# le résumé est produit même si des tests échouent ; le code de sortie reste celui de pytest
	$(PY) -m pytest -q --cov --cov-report=html --cov-report=json --cov-report=term:skip-covered $(PYTEST_ARGS); \
	  rc=$$?; $(PY) scripts/couverture_paquets.py var/couverture/couverture.json --out var/couverture/paquets.md \
	  --min $(COUV_MIN) || { [ $$rc -ne 0 ] || rc=1; }; exit $$rc

# Tests de propriétés (Hypothesis, tests/proprietes) : PROFIL=dev (défaut), ci (borné, déterministe) ou intensif.
PROFIL ?= dev
proprietes:
	HYPOTHESIS_PROFILE=$(PROFIL) $(PY) -m pytest -q tests/proprietes

# Corpus de banc non versionnés (bench/README.md) : recette et empreinte dans bench/corpus_empreintes.json.
# `make corpus-g6` régénère bench/corpus_g6 (sauté s'il est déjà conforme ; FORCE=1 pour refaire) et vérifie
# l'empreinte. Corpus quelconque : `make corpus GRAINE=20261101 PREFIXE=GU [NOMBRE=160] [PAR_CONTROLE=3]
# [SORTIE=bench/corpus_gu]` (empreinte affichée, à consigner).
CORPUS_JOBS ?= 2
corpus-g6:
	$(PY) scripts/corpus.py generer corpus_g6 --jobs $(CORPUS_JOBS) $(if $(FORCE),--force,)
corpus-verifier:
	$(PY) scripts/corpus.py verifier $(or $(CORPUS),corpus_g6)
corpus:
	@test -n "$(GRAINE)" -a -n "$(PREFIXE)" || { echo "Usage : make corpus GRAINE=entier PREFIXE=XX [NOMBRE=160] [PAR_CONTROLE=3] [SORTIE=bench/corpus_xx] [FORCE=1]"; exit 2; }
	$(PY) scripts/corpus.py generer --graine $(GRAINE) --prefixe $(PREFIXE) --jobs $(CORPUS_JOBS) \
	  $(if $(NOMBRE),--nombre $(NOMBRE),) $(if $(PAR_CONTROLE),--par-controle $(PAR_CONTROLE),) \
	  $(if $(SORTIE),--sortie $(SORTIE),) $(if $(FORCE),--force,)

# Audit des dépendances (D-3203) : vulnérabilités connues (pip-audit sur requirements.lock), SBOM CycloneDX et
# licences (permissives seulement ; exceptions justifiées dans config/audit_dependances.json). Outils dans un
# environnement séparé (.venv-audit), jamais dans l'image. Sorties : var/audit/. HORS_LIGNE=1 : ne pas échouer si
# aucune base de vulnérabilités n'est joignable (SBOM et licences restent produits).
AUDIT_VENV ?= .venv-audit
audit:
	@test -x $(AUDIT_VENV)/bin/pip-audit || { uv venv -q $(AUDIT_VENV) && uv pip install -q --python $(AUDIT_VENV)/bin/python "pip-audit>=2.7" "cyclonedx-bom>=4" "pip-licenses>=5"; }
	$(PY) scripts/audit_dependances.py --venv $(VENV) --outils $(AUDIT_VENV) --out var/audit $(if $(HORS_LIGNE),--hors-ligne,) $(if $(IMAGE),--image $(IMAGE),)

# Audit de l'image construite (D-3609) : make audit, plus les paquets du système de l'image (Debian, Tesseract…) par
# Trivy (binaire « trivy » s'il est installé, sinon l'image aquasec/trivy figée, par Docker). Échoue sur une
# vulnérabilité HIGH/CRITICAL corrigeable ; détail dans var/audit/image.md. Mandataire à autorité privée :
# AUDIT_CA_BUNDLE=fichier.pem. Construit l'image d'abord (docker-build).
audit-image: docker-build
	$(MAKE) audit IMAGE=controldone:$(or $(VERSION),2.0.0)

# Fichiers figés avec empreintes (D-3609) : requirements.lock (exécution) et deploy/requirements-build.lock (backend
# de construction de l'image). Pour monter une version : la modifier dans requirements.lock, puis make lock, puis
# make audit. Linux, Python 3.11 (image de production).
lock:
	uv pip compile requirements.lock --generate-hashes --python-version 3.11 --python-platform linux --no-annotate \
	  --no-header -o requirements.lock.tmp
	{ sed -n '/^#/p;/^[^#]/q' requirements.lock; cat requirements.lock.tmp; } > requirements.lock.neuf
	mv requirements.lock.neuf requirements.lock && rm -f requirements.lock.tmp
	uv pip compile deploy/requirements-build.lock --generate-hashes --python-version 3.11 --python-platform linux \
	  --no-annotate --no-header -o deploy/requirements-build.lock.tmp
	{ sed -n '/^#/p;/^[^#]/q' deploy/requirements-build.lock; cat deploy/requirements-build.lock.tmp; } > deploy/requirements-build.lock.neuf
	mv deploy/requirements-build.lock.neuf deploy/requirements-build.lock && rm -f deploy/requirements-build.lock.tmp

# Démonstration sur un jeu fictif : rapport dans var/demo/ (report.pdf, report.html…)
demo:
	$(PY) -m controldone.cli demo --out var/demo

# Banc, split dev : findings dans bench/out/<run_id>/ puis correcteur (WORKERS, LIMIT facultatifs)
WORKERS ?= 4
RUN_ID ?= dev_$(shell date +%Y%m%d_%H%M%S)
bench-dev:
	$(PY) -m controldone.bench_run --corpus bench/corpus --split dev --out bench/out/$(RUN_ID) --workers $(WORKERS) $(if $(LIMIT),--limit $(LIMIT),)

# Interface web de démonstration (données fictives) : base var/demo_web/, identifiants affichés à la création
DEMO_WEB ?= var/demo_web
serve-demo:
	CONTROLDONE_ENV=dev CONTROLDONE_DATA_DIR=$(DEMO_WEB) CONTROLDONE_DATABASE_URL=sqlite:///$(DEMO_WEB)/controldone.db \
	  $(PY) -m controldone.cli init-demo --si-absente
	CONTROLDONE_ENV=dev CONTROLDONE_DATA_DIR=$(DEMO_WEB) CONTROLDONE_DATABASE_URL=sqlite:///$(DEMO_WEB)/controldone.db \
	  $(PY) -m controldone.cli serve --host 127.0.0.1 --port $(or $(PORT),8000)

# Démonstration complète en une commande : installation si besoin, rapport (var/demo/), base web neuve
# (var/demo_web/, identifiants dans var/demo_web/identifiants.txt), serveur http://127.0.0.1:8000 (Ctrl-C).
demo-complete:
	scripts/demo_complete.sh

# Diagnostic d'un dossier réel ou fictif : make diagnostic DOSSIER=chemin [OUT=var/diagnostic] [SANS_LLM=1]
OUT ?= var/diagnostic
diagnostic:
	@test -n "$(DOSSIER)" || { echo "Usage : make diagnostic DOSSIER=chemin/du/lot [OUT=var/diagnostic] [SANS_LLM=1]"; exit 2; }
	$(PY) -m controldone.cli diagnostic "$(DOSSIER)" --out "$(OUT)" $(if $(SANS_LLM),--sans-llm,)

# Image de production (voir docs/DEPLOIEMENT.md) — construction seulement, aucun déploiement.
docker-build:
	docker build -f deploy/Dockerfile -t controldone:$(or $(VERSION),2.0.0) .

# Exercice de restauration de bout en bout (hors ligne, répertoire temporaire, données fictives, var/demo_web
# jamais touché) : init-demo, sauvegarde chiffrée, effacement, restauration ailleurs, contrôles, web démarré
# sur les données restaurées. GARDER=1 conserve le répertoire de travail.
restauration-test:
	$(PY) -m controldone.cli sauvegarde exercice $(if $(GARDER),--garder,)

# Débit partagé, révocations et sessions actives sous PostgreSQL (D-3610) : serveur jetable (scripts/pg_jetable.sh,
# 127.0.0.1, port 55441), tests marqués « postgresql », puis serveur arrêté et effacé. Pilote : uv pip install pg8000.
test-pg-securite:
	@url=$$(scripts/pg_jetable.sh demarrer /tmp/cd-pg-securite 55441) && \
	  CONTROLDONE_TEST_PG_URL="$$url" $(PY) -m pytest -q -m postgresql tests/security; code=$$?; \
	  scripts/pg_jetable.sh arreter /tmp/cd-pg-securite; exit $$code

# Même exercice sur PostgreSQL (D-3501) : serveur jetable dans /tmp (scripts/pg_jetable.sh, initdb + pg_ctl,
# 127.0.0.1 seulement), pg_dump / pg_restore, puis serveur arrêté et effacé. Pilote : uv pip install pg8000.
restauration-test-pg:
	@url=$$(scripts/pg_jetable.sh demarrer /tmp/cd-pg-exercice 55433) && \
	  $(PY) -m controldone.cli sauvegarde exercice --postgres "$$url" $(if $(GARDER),--garder,); code=$$?; \
	  scripts/pg_jetable.sh arreter /tmp/cd-pg-exercice; exit $$code
