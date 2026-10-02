"""Anonymisation du référentiel : clé de transitaire, regroupements, arrondis (fonctions pures).

- Transitaire : **alias public** s'il figure dans la liste tenue par le fondateur
  (``config/referentiel_alias_publics.yaml``), sinon ``T-`` + HMAC-SHA256(sel secret, TVA ou nom
  normalisé) tronqué : impossible à recalculer sans le sel, stable d'un calcul à l'autre.
- Pays d'origine -> groupe de pays ; Incoterm -> famille (E, F, C, D) ; déclaration -> régime
  (``standard`` H1 et assimilés, ``petits_envois`` H7).
- Montants arrondis à 5 EUR ; taux arrondis au pas de 5 points ; effectifs publiés en tranches.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from controldone.normalize.fiscal import normalize_vat
from controldone.normalize.text import cle_texte

__all__ = [
    "AliasPublics",
    "arrondir_montant",
    "arrondir_taux",
    "charger_alias_publics",
    "cle_transitaire",
    "famille_incoterm",
    "groupe_pays",
    "percentile",
    "regime_declaration",
    "tranche_effectif",
]

_UE = set("AT BE BG CY CZ DE DK EE ES FI FR GR HR HU IE IT LT LU LV MT NL PL PT RO SE SI SK".split())
_GROUPES: dict[str, set[str]] = {
    "chine": {"CN"},
    "asie_est": set("HK MO TW JP KR MN".split()),
    "asie_sud_est": set("VN TH MY ID PH SG KH MM LA BN".split()),
    "asie_sud": set("IN BD PK LK NP".split()),
    "amerique_nord": set("US CA MX".split()),
    "royaume_uni": {"GB"},
    "turquie": {"TR"},
    "europe_autre": set("CH NO IS LI RS BA ME MK AL UA MD BY RU XK".split()),
    "afrique_nord": set("MA DZ TN EG LY".split()),
}
_INCOTERMS = {
    "E": {"EXW"},
    "F": {"FCA", "FAS", "FOB"},
    "C": {"CFR", "CIF", "CPT", "CIP"},
    "D": {"DAP", "DPU", "DDP", "DAT", "DAF", "DDU", "DES", "DEQ"},
}

AliasPublics = Mapping[str, Mapping[str, Sequence[str]]]


def charger_alias_publics(chemin: Path | str | None = None) -> dict[str, dict[str, list[str]]]:
    """``{alias_public: {"tva": [...], "noms": [...]}}`` depuis le YAML du fondateur (absent = vide).

    Un transitaire n'est **nommé** qu'avec son accord écrit (brief juridique §5.4, D-1318) : une entrée sans
    champ ``accord_ecrit`` (référence et date de l'accord) est ignorée — le transitaire reste sous empreinte
    salée."""
    import yaml

    if chemin is None:
        from controldone.config import get_settings

        chemin = Path(get_settings().config_dir) / "referentiel_alias_publics.yaml"
    p = Path(chemin)
    if not p.exists():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    alias = data.get("alias") or {}
    sortie: dict[str, dict[str, list[str]]] = {}
    for k, v in alias.items():
        v = v or {}
        if not str(v.get("accord_ecrit") or "").strip():
            import logging

            logging.getLogger("controldone.referentiel").warning("alias_sans_accord_ecrit_ignore")
            continue
        sortie[str(k)] = {"tva": [str(x) for x in v.get("tva", [])], "noms": [str(x) for x in v.get("noms", [])]}
    return sortie


def cle_transitaire(nom: str | None, tva: str | None, *, sel: bytes, alias_publics: AliasPublics | None = None
                    ) -> str | None:
    """Alias public, sinon ``T-<12 hex>`` (HMAC salé) ; ``None`` sans nom ni TVA."""
    tva_n = normalize_vat(tva) if tva else None
    nom_n = cle_texte(nom) if nom else None
    for alias, reconnus in (alias_publics or {}).items():
        if tva_n and tva_n in {normalize_vat(x) for x in reconnus.get("tva", [])}:
            return alias
        if nom_n and nom_n in {cle_texte(x) for x in reconnus.get("noms", [])}:
            return alias
    if not (tva_n or nom_n):
        return None
    if not sel:
        raise ValueError("sel du référentiel obligatoire")
    cle = f"tva:{tva_n}" if tva_n else f"nom:{nom_n}"
    return "T-" + hmac.new(sel, cle.encode("utf-8"), hashlib.sha256).hexdigest()[:12]


def groupe_pays(iso2: str | None) -> str:
    if not iso2:
        return "inconnu"
    code = iso2.strip().upper()
    if code in _UE:
        return "ue"
    for groupe, codes in _GROUPES.items():
        if code in codes:
            return groupe
    return "autre"


def famille_incoterm(incoterm: str | None) -> str:
    if not incoterm:
        return "inconnue"
    code = incoterm.strip().upper()[:3]
    for famille, codes in _INCOTERMS.items():
        if code in codes:
            return famille
    return "inconnue"


def regime_declaration(sous_type: str | None) -> str:
    if not sous_type:
        return "inconnu"
    return "petits_envois" if sous_type == "h7" else "standard"


def arrondir_montant(x: Decimal, pas: Decimal = Decimal("5")) -> Decimal:
    """Arrondi au multiple de ``pas`` le plus proche (5 EUR par défaut)."""
    return ((Decimal(x) / pas).quantize(Decimal(1), rounding=ROUND_HALF_UP) * pas).quantize(Decimal("0.01"))


def arrondir_taux(x: Decimal, pas: Decimal = Decimal("0.05")) -> Decimal:
    return ((Decimal(x) / pas).quantize(Decimal(1), rounding=ROUND_HALF_UP) * pas).quantize(Decimal("0.01"))


def tranche_effectif(n: int) -> str:
    for borne, libelle in ((20, "10-19"), (50, "20-49"), (100, "50-99")):
        if n < borne:
            return libelle
    return "100+"


def percentile(valeurs: Sequence[Decimal], p: int) -> Decimal:
    """Percentile par rang le plus proche (valeur effectivement observée, pas d'interpolation)."""
    if not valeurs:
        raise ValueError("liste vide")
    tri = sorted(valeurs)
    rang = max(1, -(-p * len(tri) // 100))  # plafond(p × n / 100)
    return tri[min(rang, len(tri)) - 1]
