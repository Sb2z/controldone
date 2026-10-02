"""Connecteurs entrants (protocole ``ConnecteurEntrant``) : dossier surveillé, boîte IMAP dédiée,
plateforme agréée partenaire (interface et bouchon — ControlDOne n'est pas une plateforme agréée).
Relevé : ``python -m controldone.connecteurs.releve`` (``relever_tout``, ``connecteurs_configures``)."""

from controldone.connecteurs.base import ConnecteurEntrant, Depot, ResultatDepot
from controldone.connecteurs.depot import integrer_depot
from controldone.connecteurs.dossier_surveille import DossierSurveille
from controldone.connecteurs.imap import BoiteImap, ConfigImap
from controldone.connecteurs.plateforme_agreee import (
    NOTE_PA,
    ClientPA,
    ClientPAFictif,
    FacturePA,
    PlateformeAgreeeEntrante,
    proposer_statut_litige,
)

__all__ = [
    "NOTE_PA",
    "BoiteImap",
    "ClientPA",
    "ClientPAFictif",
    "ConfigImap",
    "ConnecteurEntrant",
    "Depot",
    "DossierSurveille",
    "FacturePA",
    "PlateformeAgreeeEntrante",
    "ResultatDepot",
    "integrer_depot",
    "proposer_statut_litige",
]
