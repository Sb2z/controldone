"""Configuration commune des tests : aucune clé d'API, aucun réseau."""

import pytest


@pytest.fixture(autouse=True)
def _sans_cle_api(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from controldone.config import reset_settings

    reset_settings()
    yield
    reset_settings()
