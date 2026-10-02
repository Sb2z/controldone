"""File de validation des actions sortantes (outbox). Aucun envoi réel n'est livré."""

from controldone.outbox.expediteurs import Expediteur, ExpediteurFichier
from controldone.outbox.modele import (
    ActionBloquee,
    ActionSortante,
    ModeAutonomie,
    StatutAction,
    TransitionInterdite,
    TypeAction,
)
from controldone.outbox.service import FileSortante, verifier_textes

__all__ = [
    "ActionBloquee",
    "ActionSortante",
    "Expediteur",
    "ExpediteurFichier",
    "FileSortante",
    "ModeAutonomie",
    "StatutAction",
    "TransitionInterdite",
    "TypeAction",
    "verifier_textes",
]
