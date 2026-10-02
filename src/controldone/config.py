"""Paramètres lus dans l'environnement (préfixe ``CONTROLDONE_``). Aucun secret dans le code.

La clé ``ANTHROPIC_API_KEY`` est lue sans préfixe (convention du SDK) et conservée en ``SecretStr``.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["RACINE_DEPOT", "Settings", "get_settings", "reset_settings"]

# src/controldone/config.py -> racine du dépôt (installation éditable ou exécution depuis le dépôt).
RACINE_DEPOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CONTROLDONE_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "sqlite:///var/controldone.db"
    data_dir: Path = Path("var")
    config_dir: Path = RACINE_DEPOT / "config"
    ref_dir: Path = RACINE_DEPOT / "ref"
    log_level: str = "INFO"
    seed: int | None = None  # mode déterministe (banc)

    # --- Modèle de langage (SPEC §7.3, §20.2, §20.5) ---
    anthropic_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("ANTHROPIC_API_KEY", "CONTROLDONE_ANTHROPIC_API_KEY")
    )
    llm_model: str = "claude-opus-5-5"
    llm_max_tokens: int = 16000
    llm_fallbacks: bool = True
    # Hypothèse : taux de conversion USD -> EUR pour le coût IA (le fournisseur facture en USD).
    usd_eur: Decimal = Decimal("0.92")
    llm_plafond_dossier_eur: Decimal = Decimal("0.50")
    llm_plafond_client_mensuel_eur: Decimal = Decimal("8.00")
    llm_plafond_diagnostic_eur: Decimal = Decimal("20.00")
    llm_confiance_ancree: float = 0.85

    @property
    def llm_disponible(self) -> bool:
        return self.anthropic_api_key is not None and bool(self.anthropic_api_key.get_secret_value())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings() -> None:
    """Vide le cache (tests)."""
    get_settings.cache_clear()
