"""Masses et unités de quantité (SPEC §5.2 : masses en kg à 3 décimales ; unités UN/ECE Rec. 20)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from controldone.normalize.amounts import parse_nombre
from controldone.normalize.text import cle_texte

__all__ = [
    "UNITES_ENTIERES",
    "UNITE_INCONNUE",
    "UniteNormalisee",
    "normalize_unit",
    "parse_weight_kg",
]

UNITE_INCONNUE = "inconnue"
_KG = Decimal("0.001")

# Libellés (clé sans accents, minuscules) -> code UN/ECE Rec. 20
_UNITES: dict[str, str] = {}
for _code, _libelles in {
    "C62": "pcs pc pce pces piece pieces pieza piezas u un unit units unite unites unidad unidades ea each "
    "nr nbr nb stk st qty c62 h87 nar item items article articles",
    "KGM": "kg kgs kilo kilos kilogramme kilogrammes kilogram kilograms kilogramo kilogramos kgm",
    "GRM": "g gr grs gramme grammes gram grams gramo gramos grm",
    "TNE": "t to tonne tonnes ton tons tonelada toneladas tne",
    "LTR": "l lt ltr litre litres liter liters litro litros",
    "MLT": "ml millilitre millilitres milliliter milliliters mlt",
    "MTR": "m mtr metre metres meter meters metro metros ml_lineaire",
    "MTK": "m2 m² sqm mtk metre carre metres carres square meter square meters",
    "MTQ": "m3 m³ cbm mtq metre cube metres cubes cubic meter cubic meters",
    "CMT": "cm centimetre centimetres centimeter centimeters cmt",
    "PR": "pr prs pair pairs paire paires par pares",
    "SET": "set sets jeu jeux ensemble ensembles juego juegos",
    "DZN": "dz dzn doz dozen dozens douzaine douzaines docena docenas",
    "CT": "ctn ctns carton cartons caja cajas",
    "BX": "box boxes boite boites",
    "PK": "pk pkg pkgs pack packs paquet paquets package packages colis",
    "RO": "roll rolls rouleau rouleaux rollo rollos",
    "KWH": "kwh",
}.items():
    _UNITES[_code.lower()] = _code
    for _l in _libelles.split():
        _UNITES[_l.replace("_", " ")] = _code
# libellés de plusieurs mots
for _l, _code in {
    "metre carre": "MTK", "metres carres": "MTK", "square meter": "MTK", "square meters": "MTK",
    "metre cube": "MTQ", "metres cubes": "MTQ", "cubic meter": "MTQ", "cubic meters": "MTQ",
}.items():
    _UNITES[_l] = _code

#: Unités dénombrées : la quantité se recopie exactement (``T_QUANTITE = 0``, §8.3).
UNITES_ENTIERES: frozenset[str] = frozenset({"C62", "PR", "SET", "DZN", "CT", "BX", "PK", "RO"})


@dataclass(frozen=True, slots=True)
class UniteNormalisee:
    code: str  # code UN/ECE ou ``inconnue``
    brut: str

    @property
    def connue(self) -> bool:
        return self.code != UNITE_INCONNUE

    @property
    def entiere(self) -> bool:
        return self.code in UNITES_ENTIERES


def normalize_unit(texte: str | None) -> UniteNormalisee:
    """``"pcs"`` -> ``C62`` ; ``"paires"`` -> ``PR`` ; inconnu -> ``inconnue`` (brut conservé)."""
    brut = (texte or "").strip()
    cle = cle_texte(brut).strip(" .:;,()")
    code = _UNITES.get(cle)
    if code is None:
        cle2 = cle.rstrip("s") if len(cle) > 3 else cle
        code = _UNITES.get(cle2)
    return UniteNormalisee(code=code or UNITE_INCONNUE, brut=brut)


_UNITE_MASSE_RE = re.compile(
    r"(?<![a-z])(kilogrammes?|kilograms?|kilogramos?|kilos?|kgs?|grammes?|grams?|gramos?|grs?|g|tonnes?|tons?|"
    r"toneladas?|t|lbs?|pounds?)\.?\s*$"
)
_FACTEURS_KG: dict[str, Decimal] = {
    "kg": Decimal(1), "g": Decimal("0.001"), "t": Decimal(1000), "lb": Decimal("0.45359237"),
}


def _famille_masse(unite: str) -> str:
    if unite.startswith(("kilo", "kg")):
        return "kg"
    if unite.startswith(("g", "gr")):
        return "g"
    if unite.startswith(("t", "ton")):
        return "t"
    return "lb"


def parse_weight_kg(texte: str | None, *, separateur_decimal: str | None = None) -> Decimal | None:
    """Masse en kg à 3 décimales (``ROUND_HALF_UP``). Sans unité : kg supposé.

    >>> parse_weight_kg("1 234,5 kg")
    Decimal('1234.500')
    >>> parse_weight_kg("500 g")
    Decimal('0.500')
    """
    if not texte:
        return None
    t = cle_texte(texte)
    m = _UNITE_MASSE_RE.search(t)
    facteur = Decimal(1)
    if m:
        facteur = _FACTEURS_KG[_famille_masse(m.group(1))]
        t = t[: m.start()]
    lu = parse_nombre(t, separateur_decimal=separateur_decimal)
    if lu is None or lu.negatif:
        return None
    return (lu.valeur * facteur).quantize(_KG, rounding=ROUND_HALF_UP)
