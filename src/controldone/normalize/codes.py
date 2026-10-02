"""Codes marchandise (SPEC §5.2 : chiffres seulement, longueur 6, 8 ou 10 ; forme imprimée conservée)."""

from __future__ import annotations

import re

__all__ = ["code_marchandise", "code_sh6"]


def code_marchandise(texte: str | None) -> str | None:
    """Chiffres du code (``"8471.30.00"`` -> ``"84713000"``) si la longueur est 6, 8 ou 10, sinon ``None``.

    La reconstitution d'un zéro final perdu (9 chiffres) n'est **pas** faite ici : elle exige un code
    identique sur un autre document du dossier (§7.4) et produit une valeur ``derive``.
    """
    if not texte:
        return None
    chiffres = re.sub(r"[\s.\-/]", "", texte)
    if not chiffres.isdigit():
        return None
    return chiffres if len(chiffres) in (6, 8, 10) else None


def code_sh6(texte: str | None) -> str | None:
    c = re.sub(r"\D", "", texte or "")
    return c[:6] if len(c) >= 6 else None
