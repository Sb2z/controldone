"""Paramètres lus dans l'environnement (préfixe ``CONTROLDONE_``) et dans le fichier ``.env``. Aucun secret
dans le code.

Source unique (D-1310) : ``.env`` (répertoire courant, ou ``CONTROLDONE_ENV_FILE``) est chargé **une fois**
dans ``os.environ`` sans écraser une variable déjà définie (l'environnement réel l'emporte). Ainsi toutes
les lectures — ``Settings``, mais aussi le mode d'exécution, la clé maîtresse, le secret de session,
Stripe, les données vendeur — voient les mêmes valeurs : un ``.env`` qui contient ``CONTROLDONE_ENV=prod``
met vraiment le service en production (clés obligatoires, cookie ``Secure``).

La clé ``ANTHROPIC_API_KEY`` est lue sans préfixe (convention du SDK) et conservée en ``SecretStr``.
"""

from __future__ import annotations

import os
import tempfile
import threading
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["RACINE_DEPOT", "Settings", "charger_fichier_env", "env", "get_settings", "reset_settings"]

# src/controldone/config.py -> racine du dépôt (installation éditable ou exécution depuis le dépôt).
RACINE_DEPOT = Path(__file__).resolve().parents[2]

_verrou = threading.Lock()
_charges: set[Path] = set()


def _valeur_env(brut: str) -> str:
    v = brut.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    if " #" in v:  # commentaire en fin de ligne (valeur non guillemetée)
        v = v.split(" #", 1)[0].rstrip()
    return v


def charger_fichier_env(chemin: Path | str | None = None, *, forcer: bool = False) -> dict[str, str]:
    """Charge ``KEY=VALUE`` de ``chemin`` (défaut : ``CONTROLDONE_ENV_FILE`` ou ``./.env``) dans
    ``os.environ`` **sans écraser** les variables existantes ; une fois par fichier. Lignes vides,
    commentaires ``#`` et préfixe ``export`` admis. Renvoie les variables ajoutées."""
    p = Path(chemin or os.environ.get("CONTROLDONE_ENV_FILE") or ".env").resolve()
    with _verrou:
        if p in _charges and not forcer:
            return {}
        _charges.add(p)
        if not p.is_file():
            return {}
        ajoutees: dict[str, str] = {}
        for ligne in p.read_text(encoding="utf-8").splitlines():
            ligne = ligne.strip()
            if not ligne or ligne.startswith("#") or "=" not in ligne:
                continue
            if ligne.startswith("export "):
                ligne = ligne[7:].lstrip()
            cle, _, brut = ligne.partition("=")
            cle = cle.strip()
            if not cle.replace("_", "").isalnum():
                continue
            valeur = _valeur_env(brut)
            if cle not in os.environ and valeur != "":
                os.environ[cle] = valeur
                ajoutees[cle] = valeur
        return ajoutees


def env(nom: str, defaut: str = "") -> str:
    """``os.environ[nom]`` après chargement de ``.env`` (à utiliser au lieu de ``os.environ.get``)."""
    charger_fichier_env()
    return os.environ.get(nom, defaut)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CONTROLDONE_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    #: ``dev`` | ``test`` | ``prod`` (valeur inconnue = ``prod``) — lu aussi par ``storage.cles.mode_execution``.
    env: str = "dev"
    database_url: str = "sqlite:///var/controldone.db"
    data_dir: Path = Path("var")
    config_dir: Path = RACINE_DEPOT / "config"
    ref_dir: Path = RACINE_DEPOT / "ref"
    log_level: str = "INFO"
    seed: int | None = None  # mode déterministe (banc)
    #: Répertoire temporaire des dépôts, du déchiffrement des lots et des sauvegardes. Défaut :
    #: ``<data_dir>/tmp`` (sur le volume de données, pas sur un tmpfs ``/tmp`` en mémoire) — D-1305.
    tmp_dir: Path | None = None

    # --- File de tâches ---
    job_lease_s: int = 120
    job_poll_s: float = 2.0
    #: Durée maximale du traitement d'un lot (pipeline exécuté dans un processus fils, tué au-delà ; le job
    #: devient ``dead``). 0 = pas de limite (développement, tests) ; production : 1800 (D-1311).
    lot_duree_max_s: int = 0
    #: Purge des jobs ``done`` plus anciens que ce nombre de jours (handler ``purger_retention``).
    jobs_conservation_jours: int = 30
    #: Clôture automatique d'un dossier sans écart ouvert ni constat en attente, inactif depuis N jours.
    cloture_auto_jours: int = 60

    # --- Web ---
    #: Dépôts traités en même temps par le processus web (les suivants attendent leur tour).
    depots_simultanes: int = 2

    # --- Modèle de langage (SPEC §7.3, §20.2, §20.5) ---
    anthropic_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("ANTHROPIC_API_KEY", "CONTROLDONE_ANTHROPIC_API_KEY")
    )
    llm_model: str = "claude-opus-5-5"
    llm_max_tokens: int = 16000
    llm_fallbacks: bool = True
    # Hypothèse : taux de conversion USD -> EUR pour le coût IA (le fournisseur facture en USD).
    usd_eur: Decimal = Decimal("0.92")
    #: Plafond par lot traité (``OptionsPipeline.plafond_ia_dossier_eur``, passé par le worker).
    llm_plafond_dossier_eur: Decimal = Decimal("0.50")
    #: Plafond mensuel par défaut d'un nouveau client « continu » (colonne du client, modifiable).
    llm_plafond_client_mensuel_eur: Decimal = Decimal("8.00")
    #: Plafond mensuel par défaut d'un nouveau client « diagnostic ».
    llm_plafond_diagnostic_eur: Decimal = Decimal("20.00")
    llm_confiance_ancree: float = 0.85

    @property
    def llm_disponible(self) -> bool:
        return self.anthropic_api_key is not None and bool(self.anthropic_api_key.get_secret_value())

    @property
    def repertoire_temporaire(self) -> Path:
        return Path(self.tmp_dir) if self.tmp_dir else Path(self.data_dir) / "tmp"

    def plafond_mensuel_defaut(self, offre: str) -> Decimal:
        return self.llm_plafond_diagnostic_eur if offre == "diagnostic" else self.llm_plafond_client_mensuel_eur

    def appliquer_repertoire_temporaire(self) -> Path:
        """Crée ``repertoire_temporaire`` (0700) et en fait le répertoire de ``tempfile`` du processus
        (téléversements multipart de Starlette, déchiffrement des lots, sauvegardes)."""
        rep = self.repertoire_temporaire.resolve()
        rep.mkdir(parents=True, exist_ok=True, mode=0o700)
        tempfile.tempdir = str(rep)
        return rep


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    charger_fichier_env()
    return Settings()


def reset_settings() -> None:
    """Vide le cache (tests)."""
    get_settings.cache_clear()
