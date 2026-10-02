# ControlDOne v2 — cibles de base (d'autres cibles seront ajoutées par les équipes).
VENV ?= .venv
PY := $(VENV)/bin/python

.PHONY: install test lint

install:
	uv pip install --python $(PY) -e ".[dev]"

test:
	$(PY) -m pytest -q

lint:
	$(VENV)/bin/ruff check src tests
