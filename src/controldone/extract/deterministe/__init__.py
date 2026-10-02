"""Extracteurs déterministes (texte natif ou OCR + règles), SPEC §7.3.

Registre partagé : chaque équipe ajoute son extracteur dans son propre module et **ajoute une entrée**
à ``EXTRACTEURS_DETERMINISTES`` (clé = valeur de ``TypeDocument``). ``extracteurs()`` est découvert par
``controldone.pipeline``.
"""

from __future__ import annotations

import importlib
import logging

from controldone.extract.base import Extracteur

__all__ = ["EXTRACTEURS_DETERMINISTES", "extracteurs"]

log = logging.getLogger(__name__)

#: ``{type de document: (module, classe)}`` — une entrée par type, ajoutée par l'équipe qui en est chargée.
_MODULES: dict[str, tuple[str, str]] = {
    "declaration": ("declaration", "ExtracteurDeclaration"),
    "facture_commerciale": ("facture_commerciale", "ExtracteurFactureCommerciale"),
    "facture_transitaire": ("facture_transitaire", "ExtracteurFactureTransitaire"),
    "avoir": ("avoir", "ExtracteurAvoir"),
    "document_support": ("support", "ExtracteurSupport"),
}

#: ``{type de document: extracteur}``. Un module absent ou en erreur d'import est journalisé et ignoré :
#: le registre reste utilisable pendant que les autres équipes écrivent le leur.
EXTRACTEURS_DETERMINISTES: dict[str, Extracteur] = {}
for _type, (_mod, _cls) in _MODULES.items():
    try:
        EXTRACTEURS_DETERMINISTES[_type] = getattr(importlib.import_module(f"{__name__}.{_mod}"), _cls)()
    except Exception as _e:  # pragma: no cover - dépend de l'état des autres modules
        log.warning("extracteur_deterministe_indisponible type=%s exception=%s", _type, type(_e).__name__)


def extracteurs() -> list[Extracteur]:
    """Extracteurs déterministes publiés (découverts par le pipeline)."""
    return list(EXTRACTEURS_DETERMINISTES.values())


def __getattr__(nom: str):
    """Réexport des classes (``from controldone.extract.deterministe import ExtracteurDeclaration``)."""
    for _m, _c in _MODULES.values():
        if _c == nom:
            return getattr(importlib.import_module(f"{__name__}.{_m}"), _c)
    raise AttributeError(nom)
