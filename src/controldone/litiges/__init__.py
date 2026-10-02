"""Litiges et recouvrement (SPEC §17) : dossier de demande d'avoir rédigé pour le client, relances au
client, imputation des avoirs, statut, commission. Voir ``docs/AGENTS.md`` (agent ``litiges``)."""

from controldone.litiges.commission import (
    TAUX_COMMISSION_DEFAUT,
    base_commission,
    montant_commission,
    taux_commission,
)
from controldone.litiges.etats import (
    STATUTS_ACTIFS,
    STATUTS_TERMINAUX,
    TRANSITIONS_RECLAMATION,
    StatutReclamation,
    TransitionReclamationInterdite,
    statut_depuis_ecarts,
    verifier_transition,
)
from controldone.litiges.facture import LigneFacture, payload_facture
from controldone.litiges.modele import DossierReclamation, LigneReclamation, Relance
from controldone.litiges.redaction import rendre_pdf, rendre_texte
from controldone.litiges.service import (
    RELANCES_DEFAUT,
    AvoirRecu,
    ResultatAvoir,
    ServiceLitiges,
    commission_cle,
    destinataires_client,
    id_ecart,
)

__all__ = [
    "RELANCES_DEFAUT",
    "STATUTS_ACTIFS",
    "STATUTS_TERMINAUX",
    "TAUX_COMMISSION_DEFAUT",
    "TRANSITIONS_RECLAMATION",
    "AvoirRecu",
    "DossierReclamation",
    "LigneFacture",
    "LigneReclamation",
    "Relance",
    "ResultatAvoir",
    "ServiceLitiges",
    "StatutReclamation",
    "TransitionReclamationInterdite",
    "base_commission",
    "commission_cle",
    "destinataires_client",
    "id_ecart",
    "montant_commission",
    "payload_facture",
    "rendre_pdf",
    "rendre_texte",
    "statut_depuis_ecarts",
    "taux_commission",
    "verifier_transition",
]
