"""Extraction : interface ``Extracteur`` et outils communs (SPEC §6.3, §7.3).

- ``base`` : contrat ``Extracteur``, ``ExtractionResult``, ``ExtractionContext``, ancrage, fusion ;
- ``valeurs`` : normalisation d'une valeur brute et construction d'une ``ValeurSourcee`` ;
- ``llm`` : extracteur modèle de langage (désactivé sans ``ANTHROPIC_API_KEY``).
"""

from controldone.extract.base import (
    PRIORITE_METHODE,
    CoutExtraction,
    Extracteur,
    ExtractionContext,
    ExtractionResult,
    anchor,
    ancrer,
    fusionner_resultats,
    fusionner_valeurs,
)
from controldone.extract.valeurs import ValeurNormalisee, normaliser_valeur, valeur_sourcee

__all__ = [
    "PRIORITE_METHODE",
    "CoutExtraction",
    "Extracteur",
    "ExtractionContext",
    "ExtractionResult",
    "ValeurNormalisee",
    "anchor",
    "ancrer",
    "fusionner_resultats",
    "fusionner_valeurs",
    "normaliser_valeur",
    "valeur_sourcee",
]
