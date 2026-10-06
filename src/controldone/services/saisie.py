"""Analyse **stricte** des montants saisis par un utilisateur (formulaires web, API, MCP) — D-1316.

Une seule fonction, ``montant_saisi``, pour toutes les entrées (avoir reçu, base de commission, avoir de
facture, plafond IA, prix d'un client…). Règles :

- chiffres, séparateur décimal ``,`` ou ``.`` (au plus ``decimales`` chiffres après) ; séparateurs de
  milliers admis : espace, espace insécable (U+00A0, U+202F), apostrophe, et ``.`` ou ``,`` quand l'autre
  signe est le séparateur décimal (« 1 234,56 », « 1.234,56 », « 1,234.56 », « 1'234.56 ») ;
- symbole ``€`` ou code ``EUR`` en tête ou en fin tolérés ;
- refusés : vide, ``NaN``, ``Infinity``, notation scientifique (``1e9``), signe ``+``, valeur négative (sauf
  ``negatif=True``), zéro (sauf ``zero=True``), au-delà de ``maximum`` ; groupes de milliers mal formés.

Le résultat est un ``Decimal`` quantifié au centime (``ROUND_HALF_UP`` n'intervient jamais : au plus deux
décimales sont acceptées par défaut).
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from controldone.services.plateforme import RequeteInvalide

__all__ = ["MONTANT_MAX", "montant_saisi"]

MONTANT_MAX = Decimal("1000000000")  # 1 milliard d'euros
_ESPACES = str.maketrans({" ": " ", " ": " ", " ": " ", "'": " ", "’": " "})
_DEVISE_RE = re.compile(r"^(?:€|eur)\s*|\s*(?:€|eur)$", re.IGNORECASE)
_SIMPLE_RE = re.compile(r"^\d+(?:[.,]\d+)?$")
_GROUPES_RE = re.compile(r"^\d{1,3}(?:(?P<sep>[ .,])\d{3})+(?:(?P<dec>[.,])\d+)?$")


def montant_saisi(
    texte: object,
    *,
    nom: str = "montant",
    maximum: Decimal = MONTANT_MAX,
    decimales: int = 2,
    negatif: bool = False,
    zero: bool = False,
) -> Decimal:
    """``Decimal`` exact du montant saisi, ou ``RequeteInvalide`` (message lisible, jamais une erreur 500)."""
    if texte is None:
        raise RequeteInvalide(f"{nom} : valeur obligatoire")
    brut = str(texte).translate(_ESPACES).strip()
    if len(brut) > 40:
        raise RequeteInvalide(f"{nom} : valeur trop longue")
    brut = _DEVISE_RE.sub("", brut).strip()
    signe = 1
    if brut.startswith("-"):
        signe, brut = -1, brut[1:].strip()
    if not brut:
        raise RequeteInvalide(f"{nom} : valeur obligatoire")
    compact = brut
    if _SIMPLE_RE.fullmatch(compact):
        normal = compact.replace(",", ".")
    else:
        m = _GROUPES_RE.fullmatch(compact)
        if m is None or (m.group("dec") is not None and m.group("dec") == m.group("sep")):
            raise RequeteInvalide(f"{nom} : nombre attendu (ex. 1 234,56)")
        partie_entiere = compact[: m.start("dec")] if m.group("dec") else compact
        normal = partie_entiere.replace(m.group("sep"), "")
        if m.group("dec"):
            normal += "." + compact[m.end("dec") :]
    if "." in normal and len(normal.split(".", 1)[1]) > decimales:
        raise RequeteInvalide(f"{nom} : {decimales} décimales au plus")
    try:
        valeur = Decimal(normal) * signe
    except InvalidOperation as exc:  # pragma: no cover - exclu par les expressions ci-dessus
        raise RequeteInvalide(f"{nom} : nombre attendu") from exc
    if not valeur.is_finite():  # pragma: no cover - idem
        raise RequeteInvalide(f"{nom} : nombre attendu")
    if valeur < 0 and not negatif:
        raise RequeteInvalide(f"{nom} : valeur positive attendue")
    if valeur == 0 and not zero:
        raise RequeteInvalide(f"{nom} : valeur non nulle attendue")
    if abs(valeur) > maximum:
        raise RequeteInvalide(f"{nom} : valeur trop élevée")
    return valeur.quantize(Decimal(1).scaleb(-decimales)) if decimales <= 2 else valeur
