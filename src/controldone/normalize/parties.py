"""Reconnaissance d'un transitaire du référentiel à partir d'un pavé lu (TVA, nom) — règle unique (D-1211).

Utilisée par le regroupement (``Dossier.transitaire_id``), l'imputation des avoirs (``cle_emetteur``, §17.2)
et le choix de la grille tarifaire (famille D) : un même document désigne partout le même transitaire.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from controldone.normalize.fiscal import normalize_vat
from controldone.normalize.text import cle_texte

if TYPE_CHECKING:
    from controldone.model.referentiel import Transitaire

__all__ = ["identifier_transitaire"]

#: Longueur minimale d'un nom ou alias reconnu à l'intérieur d'un nom plus long (« TRANSIT FICTIF SAS »).
LONGUEUR_MIN_INCLUSION = 4


def identifier_transitaire(
    tva: str | None, nom: str | None, transitaires: Iterable[Transitaire]
) -> str | None:
    """Identifiant du transitaire désigné par un numéro de TVA ou un nom lus.

    1. TVA normalisée égale à celle d'un transitaire ;
    2. sinon nom égal (après ``cle_texte``) au nom ou à un alias ;
    3. sinon nom ou alias d'au moins 4 caractères contenu **en mots entiers** dans le nom lu.
    Aux étapes 2 et 3, un seul transitaire doit correspondre (sinon ``None`` : ambigu).
    """
    ts = list(transitaires)
    t_lu = normalize_vat(tva) if tva else None
    if t_lu:
        for t in ts:
            if t.tva and normalize_vat(t.tva) == t_lu:
                return t.id
    n_lu = cle_texte(nom) if nom else ""
    if not n_lu:
        return None
    noms = {t.id: [cle_texte(x) for x in (t.nom, *t.alias) if x] for t in ts}
    egaux = {tid for tid, xs in noms.items() if n_lu in xs}
    if egaux:
        return next(iter(egaux)) if len(egaux) == 1 else None
    inclus = {
        tid
        for tid, xs in noms.items()
        if any(len(x) >= LONGUEUR_MIN_INCLUSION and f" {x} " in f" {n_lu} " for x in xs)
    }
    return next(iter(inclus)) if len(inclus) == 1 else None
