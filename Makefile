# ControlDOne v2 — cibles de base (d'autres cibles seront ajoutées par les équipes).
VENV ?= .venv
PY := $(VENV)/bin/python

.PHONY: install test lint demo bench-dev

install:
	uv pip install --python $(PY) -e ".[dev]"

test:
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
