"""Lecture des dates (FR, EN, ES, DE, IT, NL, ISO, ``jj.mm.aaaa``) -> ``datetime.date`` (SPEC §5.2)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from controldone.normalize.text import cle_texte

__all__ = ["DateLue", "parse_date", "parse_date_detail"]

_MOIS: dict[str, int] = {}
for _num, _noms in {
    1: "janvier janv jan january enero ene januar gennaio gen januari",
    2: "fevrier fevr fev feb february febrero februar febbraio febr februari",
    3: "mars mar march marzo marz maart mrt",
    4: "avril avr apr april abril abr aprile",
    5: "mai may mayo maggio mag mei",
    6: "juin jun june junio juni giugno giu",
    7: "juillet juil jul july julio juli luglio lug",
    8: "aout aou aug august agosto ago augustus",
    9: "septembre sept sep september septiembre setiembre set settembre",
    10: "octobre oct october octubre oktober ottobre ott okt",
    11: "novembre nov november noviembre",
    12: "decembre dec december diciembre dic dezember dicembre dez",
}.items():
    for _n in _noms.split():
        _MOIS[_n] = _num

_MOTS_MOIS = "|".join(sorted(_MOIS, key=len, reverse=True))
_ISO_RE = re.compile(r"(?<!\d)(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)")
_NUM_RE = re.compile(r"(?<!\d)(\d{1,2})[./\-](\d{1,2})[./\-](\d{4}|\d{2})(?!\d)")
_COMPACT_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})(\d{2})(\d{2})(?!\d)")
_JOUR_MOIS_RE = re.compile(
    rf"(?<!\d)(\d{{1,2}})(?:er|e|st|nd|rd|th|º|o)?\.?\s*(?:de\s+)?-?\s*({_MOTS_MOIS})\.?\s*,?\s*(?:de\s+|del\s+)?-?\s*(\d{{4}}|\d{{2}})(?!\d)"
)
_MOIS_JOUR_RE = re.compile(
    rf"(?<![a-z])({_MOTS_MOIS})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\s*,?\s+(\d{{4}})(?!\d)"
)


@dataclass(frozen=True, slots=True)
class DateLue:
    date: date
    #: Vrai si jour et mois pouvaient être inversés (ex. 03/04/2026) : l'ordre préféré a été appliqué.
    ambigu: bool


def _annee(a: str) -> int:
    n = int(a)
    if len(a) == 2:
        return 2000 + n if n <= 69 else 1900 + n
    return n


def _faire(a: int, m: int, j: int) -> date | None:
    try:
        return date(a, m, j)
    except ValueError:
        return None


def parse_date_detail(texte: str | None, *, ordre: str = "DMY") -> DateLue | None:
    """Lit la première date reconnue. ``ordre`` (``DMY`` ou ``MDY``) tranche ``03/04/2026``."""
    if not texte:
        return None
    t = cle_texte(texte)
    m = _ISO_RE.search(t)
    if m:
        d = _faire(int(m[1]), int(m[2]), int(m[3]))
        if d:
            return DateLue(d, False)
    m = _JOUR_MOIS_RE.search(t)
    if m:
        d = _faire(_annee(m[3]), _MOIS[m[2]], int(m[1]))
        if d:
            return DateLue(d, False)
    m = _MOIS_JOUR_RE.search(t)
    if m:
        d = _faire(int(m[3]), _MOIS[m[1]], int(m[2]))
        if d:
            return DateLue(d, False)
    m = _NUM_RE.search(t)
    if m:
        x, y, a = int(m[1]), int(m[2]), _annee(m[3])
        if x > 12 >= y:
            d, amb = _faire(a, y, x), False
        elif y > 12 >= x:
            d, amb = _faire(a, x, y), False
        elif ordre.upper() == "MDY":
            d, amb = _faire(a, x, y), x != y
        else:
            d, amb = _faire(a, y, x), x != y
        if d:
            return DateLue(d, amb)
    m = _COMPACT_RE.search(t)
    if m:
        d = _faire(int(m[1]), int(m[2]), int(m[3]))
        if d:
            return DateLue(d, False)
    return None


def parse_date(texte: str | None, *, ordre: str = "DMY") -> date | None:
    """Date ISO d'un texte : ``14/08/2026``, ``14.08.2026``, ``2026-08-14``, ``14 août 2026``,
    ``August 14, 2026``, ``14 de agosto de 2026``, ``1er août 2026``…"""
    lu = parse_date_detail(texte, ordre=ordre)
    return lu.date if lu else None
