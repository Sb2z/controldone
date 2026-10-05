"""Normalisation de texte : accents, espaces, casse."""

from __future__ import annotations

import re
import unicodedata

__all__ = ["ESPACES", "cle_texte", "normaliser_espaces", "sans_accents"]

#: Espaces rencontrés dans les montants et textes : normale, insécable, fine insécable, fine, etc.
ESPACES = "         　\t"
_ESPACES_RE = re.compile(r"[\s        　]+")


_BARREES = str.maketrans({"ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D"})


def sans_accents(texte: str) -> str:
    """Supprime les diacritiques (``é`` -> ``e``, ``ç`` -> ``c``) ; ``œ`` -> ``oe``, ``æ`` -> ``ae`` ; lettres
    barrées sans décomposition Unicode (polonais ``ł``, ``ø``, ``đ``) -> lettre simple (D-2501)."""
    texte = texte.replace("œ", "oe").replace("Œ", "OE").replace("æ", "ae").replace("Æ", "AE")
    texte = texte.translate(_BARREES)
    decompose = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in decompose if not unicodedata.combining(c))


def normaliser_espaces(texte: str) -> str:
    """Remplace toute suite d'espaces (y compris insécables, fines, retours à la ligne) par une espace."""
    return _ESPACES_RE.sub(" ", texte).strip()


def cle_texte(texte: str) -> str:
    """Clé de comparaison : minuscules, sans accents, apostrophes droites, espaces normalisées."""
    t = sans_accents(texte).casefold()
    t = t.replace("’", "'").replace("‘", "'").replace("`", "'")
    return normaliser_espaces(t)
