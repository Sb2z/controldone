# ControlDOne v2 — cibles de base (d'autres cibles seront ajoutées par les équipes).
VENV ?= .venv
PY := $(VENV)/bin/python

.PHONY: install test lint demo bench-dev serve-demo demo-complete diagnostic docker-build

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
	$(VENV)/bin/ruff check src tests

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
