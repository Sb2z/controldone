"""Incoterms : code à 3 lettres + lieu libre (SPEC §5.2)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from controldone.normalize.text import cle_texte

__all__ = ["INCOTERMS", "INCOTERMS_ANCIENS", "IncotermLu", "parse_incoterm"]

INCOTERMS: frozenset[str] = frozenset("EXW FCA FAS FOB CFR CIF CPT CIP DAP DPU DDP".split())
#: Anciens codes reconnus (Incoterms 2000/2010).
INCOTERMS_ANCIENS: frozenset[str] = frozenset("DAT DAF DES DEQ DDU".split())
_TOUS = INCOTERMS | INCOTERMS_ANCIENS

_LONGS: dict[str, str] = {
    "ex works": "EXW", "ex-works": "EXW", "a l'usine": "EXW", "en fabrica": "EXW",
    "free carrier": "FCA", "franco transporteur": "FCA",
    "free alongside ship": "FAS", "franco le long du navire": "FAS",
    "free on board": "FOB", "franco a bord": "FOB", "franco bord": "FOB",
    "cost and freight": "CFR", "cost & freight": "CFR", "c&f": "CFR", "cout et fret": "CFR",
    "cost insurance and freight": "CIF", "cost, insurance and freight": "CIF", "cost insurance freight": "CIF",
    "cout, assurance et fret": "CIF", "cout assurance fret": "CIF",
    "carriage paid to": "CPT", "port paye jusqu'a": "CPT",
    "carriage and insurance paid to": "CIP", "port paye, assurance comprise": "CIP",
    "delivered at place unloaded": "DPU", "rendu au lieu de destination decharge": "DPU",
    "delivered at place": "DAP", "rendu au lieu de destination": "DAP",
    "delivered duty paid": "DDP", "rendu droits acquittes": "DDP",
    "delivered duty unpaid": "DDU", "rendu droits non acquittes": "DDU",
}


@dataclass(frozen=True, slots=True)
class IncotermLu:
    code: str
    lieu: str | None
    ancien: bool


def parse_incoterm(texte: str | None) -> IncotermLu | None:
    """``"FOB Shanghai"`` -> ``IncotermLu("FOB", "Shanghai", False)`` ; ``"Ex Works Lyon"`` -> EXW."""
    if not texte:
        return None
    brut = texte.strip()
    nettoye = re.sub(r"(?i)\bincoterms?\s*(?:®|\(r\))?\s*(?:19|20)?\d{2}\b", " ", brut)
    nettoye = re.sub(r"(?i)\bincoterms?\b\s*:?", " ", nettoye)
    for m in re.finditer(r"(?<![A-Za-z])([A-Za-z]{3})(?![A-Za-z])", nettoye):
        code = m.group(1).upper()
        if code in _TOUS and (m.group(1).isupper() or len(nettoye.strip()) <= 4):
            lieu = (nettoye[: m.start()] + " " + nettoye[m.end():]).strip(" ,;:-/")
            lieu = re.sub(r"\s+", " ", lieu) or None
            return IncotermLu(code, lieu, code in INCOTERMS_ANCIENS)
    cle = cle_texte(nettoye)
    for libelle, code in sorted(_LONGS.items(), key=lambda kv: -len(kv[0])):
        i = cle.find(libelle)
        if i >= 0:
            reste = cle[i + len(libelle):].strip(" ,;:-/")
            # le lieu est repris dans le texte d'origine (casse conservée) quand c'est possible
            lieu = nettoye.strip()[-len(reste):].strip(" ,;:-/") if reste else None
            return IncotermLu(code, lieu or None, code in INCOTERMS_ANCIENS)
    return None
