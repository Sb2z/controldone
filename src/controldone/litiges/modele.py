"""Modèle du dossier de demande d'avoir (extension de ``model.recouvrement.Reclamation``, §17.3).

Le contenu complet est enregistré dans ``reclamations.contenu`` (JSON) via ``TenantScope.enregistrer_reclamation``.
Montants : ``Decimal`` exacts (sérialisés en chaînes).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import Field

from controldone.model.base import Modele
from controldone.model.enums import Composante, Niveau
from controldone.model.recouvrement import Reclamation

from .etats import StatutReclamation

__all__ = [
    "AvoirImpute",
    "Commission",
    "DossierReclamation",
    "LigneReclamation",
    "PieceLigne",
    "Relance",
]


class PieceLigne(Modele):
    """Pièce justificative d'une ligne : document, page, texte lu, calcul (§17.3 point 4)."""

    document: str  # libellé lisible : « facture du transitaire n° FT-1 »
    document_id: str | None = None
    page: int | None = None
    valeur_lue: str | None = None
    role: str | None = None
    calcul: str | None = None


class LigneReclamation(Modele):
    """Un écart constaté entre documents, tel qu'il figure dans le dossier (§17.3 point 3)."""

    ecart_id: str
    constat_id: str
    dossier_id: str
    dossier_reference: str | None = None
    controle_id: str
    niveau: Niveau
    a_confirmer: bool = False  # écart « à vérifier » coché par le client (§17.3 point 5)
    facture: str | None = None  # numéro de la facture du transitaire
    mrn: str | None = None
    ref_transport: str | None = None
    composante: Composante
    montant_refacture: str | None = None  # valeur lue (texte imprimé)
    source_refacture: str | None = None
    montant_reference: str | None = None
    source_reference: str | None = None
    ecart: Decimal  # montant de l'écart constaté entre documents (EUR)
    tolerance: str | None = None  # tolérance appliquée par le contrôle (affichée dans le relevé)
    constat: str = ""  # libellé comparatif du constat
    pieces: list[PieceLigne] = Field(default_factory=list)


class Relance(Modele):
    """Relance planifiée **adressée au client** (jamais au transitaire)."""

    jours: int
    due_le: date
    statut: str = "planifiee"  # planifiee | brouillon_cree | annulee
    outbox_id: str | None = None


class AvoirImpute(Modele):
    avoir_id: str
    numero: str | None = None
    date_avoir: date | None = None
    montant_total: Decimal
    impute: Decimal  # part imputée sur les écarts de cette réclamation
    reliquat: Decimal  # reliquat non imputé de l'avoir (toutes réclamations confondues, E5)
    imputations: dict[str, Decimal] = Field(default_factory=dict)  # ecart_id -> montant
    le: datetime
    #: ``transitaire`` (avoir émis par le transitaire) ou ``administration`` (remboursement, remise ou
    #: dégrèvement accordé par la douane ou une autre autorité : hors assiette de la commission, D-1314).
    origine: str = "transitaire"
    hors_assiette: bool = False
    montant_tva: Decimal | None = None  # TVA portée par l'avoir (information ; jamais dans l'assiette)


class Commission(Modele):
    """Ligne de commission (§17.4) : base = crédits imputés sur des écarts issus de constats validés."""

    avoir_id: str
    base: Decimal
    taux: Decimal
    montant: Decimal
    outbox_id: str | None = None
    le: datetime


class DossierReclamation(Reclamation):
    statut: StatutReclamation = StatutReclamation.brouillon
    entite: dict[str, str | None] = Field(default_factory=dict)  # raison_sociale, adresse, tva
    transitaire: dict[str, str | None] = Field(default_factory=dict)  # nom, adresse, contact
    factures: list[str] = Field(default_factory=list)
    lignes: list[LigneReclamation] = Field(default_factory=list)
    total_a_confirmer: Decimal = Decimal("0.00")
    texte: str = ""
    pdf_sha256: str | None = None
    relances: list[Relance] = Field(default_factory=list)
    avoirs: list[AvoirImpute] = Field(default_factory=list)
    commissions: list[Commission] = Field(default_factory=list)
    historique: list[dict[str, str | None]] = Field(default_factory=list)
    outbox_mise_a_disposition: str | None = None
    derniere_activite: datetime | None = None
