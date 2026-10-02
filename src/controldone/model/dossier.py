"""Dossier, LienDocument, Allocation (SPEC §6.2.7, §6.2.8)."""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field

from controldone.ids import Prefixe, nouvel_id
from controldone.model.base import Enregistrement, Modele
from controldone.model.enums import ForceLien, MethodeAllocation, RoleLien, SignalLien, StatutGlobal

__all__ = ["Allocation", "ClesDossier", "Dossier", "LienDocument", "poids_force"]

#: Poids des signaux (§7.5 étape 6) : forte 3, moyenne 2, faible 1.
POIDS_FORCE: dict[ForceLien, int] = {ForceLien.forte: 3, ForceLien.moyenne: 2, ForceLien.faible: 1}


def poids_force(force: ForceLien) -> int:
    return POIDS_FORCE.get(force, 0)


class LienDocument(Modele):
    """Lien d'un document au dossier (§6.2.8). Un lien par document du dossier.

    Le document **graine** (facture commerciale, ou document orphelin formant son propre dossier,
    §7.5) porte ``force = forte`` et le signal ``graine`` (D-013).
    """

    id: str = Field(default_factory=lambda: nouvel_id(Prefixe.lien))
    document_id: str
    role: RoleLien
    force: ForceLien
    signaux: list[SignalLien] = Field(default_factory=list)
    score: int = 0


class Allocation(Modele):
    """Répartition plusieurs-à-plusieurs (§6.2.8).

    - facture commerciale -> déclaration : ``source_document_id`` = facture, ``cible_document_id`` = déclaration ;
    - ligne de facture transitaire -> MRN : ``source_document_id`` = facture transitaire,
      ``source_ligne`` = index 0-based de la ligne, ``cible_document_id`` = déclaration, ``mrn`` renseigné.
    """

    id: str = Field(default_factory=lambda: nouvel_id(Prefixe.allocation))
    source_document_id: str
    source_ligne: int | None = None
    cible_document_id: str | None = None
    mrn: str | None = None
    montant_alloue: Decimal | None = None
    methode: MethodeAllocation


class ClesDossier(Modele):
    """Clés du dossier, toujours affichées dans cet ordre (§6.2.7)."""

    num_facture_transitaire: list[str] = Field(default_factory=list)
    ref_transport: list[str] = Field(default_factory=list)
    mrn: list[str] = Field(default_factory=list)
    num_facture_commerciale: list[str] = Field(default_factory=list)


class Dossier(Enregistrement):
    id: str = Field(default_factory=lambda: nouvel_id(Prefixe.dossier))
    #: Référence lisible ``D-AAAA-NNNNN``.
    reference: str | None = Field(default=None, pattern=r"^D-\d{4}-\d{5}$")
    version: int = Field(default=1, ge=1)
    cles: ClesDossier = Field(default_factory=ClesDossier)
    statut_global: StatutGlobal | None = None
    liens: list[LienDocument] = Field(default_factory=list)
    allocations: list[Allocation] = Field(default_factory=list)
    transitaire_id: str | None = None
    incomplet: bool = False
    documents_manquants: list[str] = Field(default_factory=list)
    #: Lot(s) d'origine et frontière de regroupement (§7.5 étape 1), informatif.
    lot_ids: list[str] = Field(default_factory=list)
    frontiere: str | None = None

    def lien(self, document_id: str) -> LienDocument | None:
        for lien in self.liens:
            if lien.document_id == document_id:
                return lien
        return None

    def document_ids(self, role: RoleLien | None = None) -> list[str]:
        return [lien.document_id for lien in self.liens if role is None or lien.role is role]
