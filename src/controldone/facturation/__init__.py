"""Facturation du fondateur (niveau 3) : offres, factures Factur-X EN 16931, numérotation continue,
paiements Stripe (mode test) ou bouchon, plateforme agréée partenaire (bouchon), suivi financier.

ControlDOne **n'est pas** une plateforme agréée : voir ``facturation.pa`` et ``docs/FACTURATION.md``.
"""

from __future__ import annotations

from typing import Any

from controldone.facturation.offres import CatalogueOffres, Consentement, CouponRefuse, charger_offres
from controldone.facturation.pa import PlateformeAgreee, PlateformeAgreeeBouchon
from controldone.facturation.paiements import (
    FournisseurPaiement,
    PaiementBouchon,
    PaiementStripe,
    SignatureInvalide,
    fournisseur_depuis_env,
)
from controldone.facturation.service import EmissionRefusee, ExpediteurFacture, ServiceFacturation

__all__ = [
    "CatalogueOffres",
    "Consentement",
    "CouponRefuse",
    "EmissionRefusee",
    "ExpediteurFacture",
    "FournisseurPaiement",
    "PaiementBouchon",
    "PaiementStripe",
    "PlateformeAgreee",
    "PlateformeAgreeeBouchon",
    "ServiceFacturation",
    "SignatureInvalide",
    "charger_offres",
    "fournisseur_depuis_env",
    "service_pour",
]


def service_pour(plateforme: Any) -> ServiceFacturation:
    """Service de facturation d'une ``Plateforme`` (web) : celui posé sur ``plateforme.facturation`` (tests),
    sinon PA bouchon et paiement selon l'environnement, sous ``<data_dir>``."""
    deja = getattr(plateforme, "facturation", None)
    if isinstance(deja, ServiceFacturation):
        return deja
    from pathlib import Path

    from controldone.config import get_settings

    data = Path(get_settings().data_dir)
    service = ServiceFacturation(plateforme.db, pa=PlateformeAgreeeBouchon(data / "pa_bouchon"),
                                 paiement=fournisseur_depuis_env(racine_bouchon=data / "paiement_bouchon"),
                                 dossier_sorties=getattr(plateforme, "dossier_sorties", None))
    plateforme.facturation = service
    return service
