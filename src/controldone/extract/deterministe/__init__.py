"""Extracteurs déterministes (texte natif ou OCR + règles), SPEC §7.3.

Chargement **explicite** (D-1214) : une erreur d'import d'un extracteur fait échouer l'import du paquet au
lieu de faire disparaître l'extracteur en silence (le rappel s'effondrerait sans erreur visible).
``extracteurs()`` est appelé par ``controldone.pipeline.composants_par_defaut``.
"""

from __future__ import annotations

from controldone.extract.base import Extracteur
from controldone.extract.deterministe.avoir import ExtracteurAvoir
from controldone.extract.deterministe.declaration import ExtracteurDeclaration
from controldone.extract.deterministe.facture_commerciale import ExtracteurFactureCommerciale
from controldone.extract.deterministe.facture_transitaire import ExtracteurFactureTransitaire
from controldone.extract.deterministe.support import ExtracteurSupport

__all__ = [
    "EXTRACTEURS_DETERMINISTES",
    "ExtracteurAvoir",
    "ExtracteurDeclaration",
    "ExtracteurFactureCommerciale",
    "ExtracteurFactureTransitaire",
    "ExtracteurSupport",
    "extracteurs",
]

#: ``{type de document: extracteur}`` (clé = valeur de ``TypeDocument``).
EXTRACTEURS_DETERMINISTES: dict[str, Extracteur] = {
    "declaration": ExtracteurDeclaration(),
    "facture_commerciale": ExtracteurFactureCommerciale(),
    "facture_transitaire": ExtracteurFactureTransitaire(),
    "avoir": ExtracteurAvoir(),
    "document_support": ExtracteurSupport(),
}


def extracteurs() -> list[Extracteur]:
    """Extracteurs déterministes publiés."""
    return list(EXTRACTEURS_DETERMINISTES.values())
