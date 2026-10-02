"""Actions sortantes (file de validation) : types, statuts, modèle."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "TRANSITIONS",
    "ActionBloquee",
    "ActionSortante",
    "ModeAutonomie",
    "StatutAction",
    "TransitionInterdite",
    "TypeAction",
]


class TypeAction(StrEnum):
    email_client = "email_client"
    rapport_publication = "rapport_publication"
    reclamation_dossier = "reclamation_dossier"  # mise à disposition du client (§17.3), jamais envoyé au transitaire
    relance = "relance"
    facture_emise = "facture_emise"
    post_linkedin = "post_linkedin"
    email_prospection = "email_prospection"
    statut_litige_pa = "statut_litige_pa"  # proposé au client, qui décide seul (le produit n'est pas une PA)
    note_veille = "note_veille"  # note interne au fondateur, jamais publiée


class StatutAction(StrEnum):
    brouillon = "brouillon"
    approuve = "approuve"
    corrige = "corrige"  # approuvé avec corrections du fondateur
    refuse = "refuse"
    envoye = "envoye"


class ModeAutonomie(StrEnum):
    manuel = "manuel"  # défaut pour TOUS les types
    auto = "auto"  # approbation automatique si les garde-fous passent (envoi toujours explicite)


TRANSITIONS: dict[StatutAction, frozenset[StatutAction]] = {
    StatutAction.brouillon: frozenset({StatutAction.approuve, StatutAction.corrige, StatutAction.refuse}),
    StatutAction.approuve: frozenset({StatutAction.envoye}),
    StatutAction.corrige: frozenset({StatutAction.envoye}),
    StatutAction.refuse: frozenset(),
    StatutAction.envoye: frozenset(),
}


class TransitionInterdite(ValueError):
    pass


class ActionBloquee(ValueError):
    """Texte refusé par les garde-fous (§3.2) : ``motifs`` liste les expressions trouvées."""

    def __init__(self, motifs: list[str]) -> None:
        self.motifs = motifs
        super().__init__("action bloquée par les garde-fous : " + "; ".join(motifs))


class ActionSortante(BaseModel):
    """Instantané d'une action sortante (lecture seule)."""

    model_config = ConfigDict(frozen=True)

    id: str
    tenant_id: str | None
    kind: TypeAction
    statut: StatutAction
    payload: dict[str, Any] = Field(default_factory=dict)
    payload_corrige: dict[str, Any] | None = None
    motif_blocage: str | None = None
    motif_refus: str | None = None
    idempotency_key: str | None = None
    auto: bool = False
    cree_par: str
    cree_le: datetime
    decide_par: str | None = None
    decide_le: datetime | None = None
    envoye_le: datetime | None = None
    reference_envoi: str | None = None

    @property
    def payload_effectif(self) -> dict[str, Any]:
        """Contenu à envoyer : la version corrigée si elle existe."""
        return self.payload_corrige if self.payload_corrige is not None else self.payload
