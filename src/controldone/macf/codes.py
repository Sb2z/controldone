"""Liste versionnée des codes NC de l'annexe I MACF/CBAM (``config/macf_codes_nc.yaml``).

La correspondance se fait sur le code **imprimé** de la déclaration, par préfixe : le produit ne dit
jamais si une marchandise relève du MACF ni quel est son classement. Toute ligne retenue est « à faire
vérifier » ; un code imprimé trop court pour trancher (« 7202 » face à l'exclusion « 7202 2 ») est
« à préciser ».
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

import yaml

__all__ = [
    "CorrespondanceCode",
    "EntreeCode",
    "ListeCodesMACF",
    "Secteur",
    "StatutCode",
    "charger_liste",
    "chiffres_code",
]


class StatutCode(StrEnum):
    #: Le code imprimé commence par un code de la liste et n'est visé par aucune exclusion.
    dans_liste = "dans_liste"
    #: Le code imprimé est trop court pour être départagé (préfixe d'un code ou d'une exclusion).
    a_preciser = "a_preciser"
    hors_liste = "hors_liste"
    #: Code absent ou sans chiffres exploitables.
    illisible = "illisible"


def chiffres_code(texte: str | None) -> str:
    """Chiffres du code tel qu'imprimé (``"7208 51 98"`` -> ``"72085198"``)."""
    return re.sub(r"\D", "", texte or "")


@dataclass(frozen=True, slots=True)
class EntreeCode:
    code: str  # tel qu'écrit dans l'annexe
    libelle: str
    secteur: str
    exclusions: tuple[str, ...] = ()

    @property
    def prefixe(self) -> str:
        return chiffres_code(self.code)

    @property
    def prefixes_exclus(self) -> tuple[str, ...]:
        return tuple(chiffres_code(e) for e in self.exclusions)


@dataclass(frozen=True, slots=True)
class Secteur:
    id: str
    libelle: str
    gaz: tuple[str, ...]
    hors_cumul_50t: bool


@dataclass(frozen=True, slots=True)
class CorrespondanceCode:
    code_imprime: str | None
    statut: StatutCode
    entree: EntreeCode | None = None
    secteur: Secteur | None = None
    motif: str = ""

    @property
    def retenue(self) -> bool:
        """Ligne à faire figurer dans la préparation (dans la liste ou à préciser)."""
        return self.statut in (StatutCode.dans_liste, StatutCode.a_preciser)


@dataclass(frozen=True)
class ListeCodesMACF:
    version: str
    statut: str
    source_url: str
    source_texte: str
    consulte_le: str
    seuil_tonnes: str
    seuil_source_url: str
    secteurs: dict[str, Secteur]
    entrees: tuple[EntreeCode, ...]
    brut: dict = field(default_factory=dict, repr=False)

    @property
    def a_verifier(self) -> bool:
        return self.statut != "verifie"

    def classer(self, code_imprime: str | None) -> CorrespondanceCode:
        """Rapproche un code imprimé de la liste (par préfixe, jamais par interprétation)."""
        c = chiffres_code(code_imprime)
        if len(c) < 2:
            return CorrespondanceCode(
                code_imprime, StatutCode.illisible, motif="code imprimé absent ou illisible"
            )
        ambigu: EntreeCode | None = None
        for e in self.entrees:
            p = e.prefixe
            if c.startswith(p):
                if any(c.startswith(x) for x in e.prefixes_exclus):
                    continue  # code visé par une exclusion de l'entrée
                if any(x.startswith(c) for x in e.prefixes_exclus):
                    ambigu = ambigu or e
                    continue
                return CorrespondanceCode(
                    code_imprime,
                    StatutCode.dans_liste,
                    e,
                    self.secteurs[e.secteur],
                    motif=f"le code imprimé commence par {e.code} (liste annexe I)",
                )
            if p.startswith(c):
                ambigu = ambigu or e
        if ambigu is not None:
            return CorrespondanceCode(
                code_imprime,
                StatutCode.a_preciser,
                ambigu,
                self.secteurs[ambigu.secteur],
                motif=f"code imprimé trop court pour être rapproché de {ambigu.code} : à préciser",
            )
        return CorrespondanceCode(code_imprime, StatutCode.hors_liste, motif="aucun code de la liste")


def _chemin_defaut() -> Path:
    from controldone.config import get_settings

    return Path(get_settings().config_dir) / "macf_codes_nc.yaml"


@lru_cache(maxsize=4)
def _charger(chemin: str) -> ListeCodesMACF:
    with open(chemin, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict) or "secteurs" not in data:
        raise ValueError(f"liste MACF invalide : {chemin}")
    secteurs: dict[str, Secteur] = {}
    entrees: list[EntreeCode] = []
    for s in data["secteurs"]:
        secteurs[s["id"]] = Secteur(
            s["id"], s["libelle"], tuple(s.get("gaz", ())), bool(s.get("hors_cumul_50t"))
        )
        for c in s["codes"]:
            entrees.append(EntreeCode(str(c["code"]), c["libelle"], s["id"], tuple(c.get("exclusions", ()))))
    # préfixes les plus longs d'abord : l'entrée la plus précise l'emporte (« 7301 » avant « 72 »… disjoints ici)
    entrees.sort(key=lambda e: -len(e.prefixe))
    src = data.get("source", {})
    return ListeCodesMACF(
        version=str(data["version"]),
        statut=str(data.get("statut", "a_verifier")),
        source_url=src.get("url", ""),
        source_texte=src.get("texte", ""),
        consulte_le=str(src.get("consulte_le", "")),
        seuil_tonnes=str(data.get("seuil_annuel_tonnes", "50")),
        seuil_source_url=data.get("seuil_source", {}).get("url", ""),
        secteurs=secteurs,
        entrees=tuple(entrees),
        brut=data,
    )


def charger_liste(chemin: Path | str | None = None) -> ListeCodesMACF:
    """Charge ``config/macf_codes_nc.yaml`` (mis en cache par chemin)."""
    return _charger(str(chemin or _chemin_defaut()))
