"""Configuration du module de prospection : ``config/prospection.yaml`` (plafonds, exclusions, règles par pays,
barème du score, expéditeur). Le secret des liens de désinscription n'y figure pas (``jetons.py``)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

__all__ = ["A_COMPLETER", "ConfigProspection", "GroupeExclu", "charger_config"]

A_COMPLETER = "À COMPLÉTER"


@dataclass(frozen=True)
class GroupeExclu:
    groupe: str
    motifs: tuple[str, ...]


@dataclass(frozen=True)
class ConfigProspection:
    preparations_par_jour: int = 15
    envois_par_jour: int = 15
    conservation_annees: int = 3
    exclusions: tuple[GroupeExclu, ...] = ()
    pays_consentement_nominatif: frozenset[str] = frozenset({"CH", "BE"})
    pays_bloques: frozenset[str] = frozenset({"LU"})
    naf_importateurs: frozenset[str] = frozenset()
    departements_prioritaires: frozenset[str] = frozenset()
    expediteur_nom: str = A_COMPLETER
    expediteur_fonction: str = "fondateur de ControlDOne"
    brut: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)


def _liste(v: Any) -> list[str]:
    return [str(x).strip() for x in (v or []) if str(x).strip()]


def charger_config(
    chemin: Path | str | None = None, *, env: dict[str, str] | None = None
) -> ConfigProspection:
    """Lit ``config/prospection.yaml`` (ou ``chemin``). ``CONTROLDONE_PROSPECTION_EXPEDITEUR_NOM`` remplace le nom
    de l'expéditeur. Fichier absent : valeurs par défaut prudentes (aucune exclusion connue, d'où un refus de
    démarrer plutôt qu'un oubli silencieux : ``ValueError``)."""
    import os

    from controldone.config import get_settings

    p = Path(chemin) if chemin else Path(get_settings().config_dir) / "prospection.yaml"
    brut = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(brut, dict) or not brut.get("exclusions"):
        raise ValueError(f"configuration de prospection invalide (liste d'exclusion absente) : {p}")
    env = dict(os.environ) if env is None else env
    plafonds = brut.get("plafonds") or {}
    pays = brut.get("pays") or {}
    scoring = brut.get("scoring") or {}
    expediteur = brut.get("expediteur") or {}
    groupes = tuple(
        GroupeExclu(str(g.get("groupe") or f"groupe_{i}"), tuple(_liste(g.get("motifs"))))
        for i, g in enumerate(brut["exclusions"], 1)
        if isinstance(g, dict)
    )
    if not any(g.motifs for g in groupes):
        raise ValueError(f"configuration de prospection invalide (liste d'exclusion vide) : {p}")
    nom = (env.get("CONTROLDONE_PROSPECTION_EXPEDITEUR_NOM") or str(expediteur.get("nom") or "")).strip()
    return ConfigProspection(
        preparations_par_jour=max(0, int(plafonds.get("preparations_par_jour", 15))),
        envois_par_jour=max(0, int(plafonds.get("envois_par_jour", 15))),
        conservation_annees=max(1, int(brut.get("conservation_annees", 3))),
        exclusions=groupes,
        pays_consentement_nominatif=frozenset(x.upper() for x in _liste(pays.get("consentement_nominatif"))),
        pays_bloques=frozenset(x.upper() for x in _liste(pays.get("bloques"))),
        naf_importateurs=frozenset(x.upper() for x in _liste(scoring.get("naf_importateurs"))),
        departements_prioritaires=frozenset(_liste(scoring.get("departements_prioritaires"))),
        expediteur_nom=nom or A_COMPLETER,
        expediteur_fonction=str(expediteur.get("fonction") or "fondateur de ControlDOne").strip(),
        brut=brut,
    )
