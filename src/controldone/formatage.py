"""Formatage français des nombres pour les textes (libellés, rapports).

Séparateur de milliers : espace insécable (U+00A0) ; virgule décimale ; devise après le nombre.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from controldone.normalize.currency import exposant_devise

__all__ = ["ESPACE_INSECABLE", "format_montant", "format_nombre", "format_pourcentage"]

ESPACE_INSECABLE = " "


def format_nombre(x: Decimal | int | str, decimales: int | None = None) -> str:
    """``Decimal("2091")`` -> ``"2 091"`` ; ``Decimal("2.5")`` -> ``"2,5"`` ; ``decimales=2`` -> ``"2,50"``."""
    d = Decimal(str(x))
    if decimales is not None:
        d = d.quantize(Decimal(1).scaleb(-decimales), rounding=ROUND_HALF_UP)
    signe = "-" if d < 0 else ""
    texte = format(abs(d), "f")
    entier, _, frac = texte.partition(".")
    groupes = []
    while len(entier) > 3:
        groupes.insert(0, entier[-3:])
        entier = entier[:-3]
    groupes.insert(0, entier)
    s = ESPACE_INSECABLE.join(groupes)
    return f"{signe}{s},{frac}" if frac else f"{signe}{s}"


def format_montant(x: Decimal, devise: str | None = "EUR") -> str:
    """``Decimal("2091")``, ``"EUR"`` -> ``"2 091,00 EUR"`` (décimales selon la devise)."""
    dec = exposant_devise(devise) if devise else 2
    s = format_nombre(x, dec)
    return f"{s}{ESPACE_INSECABLE}{devise}" if devise else s


def format_pourcentage(x: Decimal) -> str:
    """``Decimal("2.5")`` -> ``"2,5 %"`` (le taux est déjà exprimé en pour cent)."""
    d = Decimal(str(x)).normalize()
    if d == d.to_integral_value():
        d = d.quantize(Decimal(1))
    return f"{format_nombre(d)}{ESPACE_INSECABLE}%"
