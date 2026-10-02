from decimal import Decimal as D

from controldone.config import Settings, get_settings


def test_defauts(monkeypatch):
    monkeypatch.delenv("CONTROLDONE_LLM_MODEL", raising=False)
    s = Settings(_env_file=None)
    assert s.llm_model == "claude-opus-5-5" and s.usd_eur == D("0.92")
    assert s.llm_plafond_dossier_eur == D("0.50") and not s.llm_disponible
    assert (s.config_dir / "formulations_interdites.yaml").exists()


def test_variables_d_environnement(monkeypatch):
    monkeypatch.setenv("CONTROLDONE_LLM_MODEL", "claude-sonnet-5-5")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("CONTROLDONE_USD_EUR", "0.9")
    s = Settings(_env_file=None)
    assert s.llm_model == "claude-sonnet-5-5" and s.llm_disponible and s.usd_eur == D("0.9")
    assert "sk-test" not in repr(s)


def test_cache():
    assert get_settings() is get_settings()
