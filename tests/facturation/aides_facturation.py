"""Aides des tests de facturation (données FICTIVES)."""

from __future__ import annotations

from pathlib import Path

from controldone.auth.roles import Acteur, Role
from controldone.config import RACINE_DEPOT
from controldone.storage import Database

FONDATEUR = Acteur("usr_fondateur", Role.fondateur)
SYSTEME = Acteur.systeme("tests")
CONFIG = RACINE_DEPOT / "config" / "offres.yaml"

VENDEUR_FICTIF = {
    "raison_sociale": "CONTROLDONE FICTIF", "forme_juridique": "EI (entrepreneur individuel) FICTIF",
    "siren": "999999999", "rcs": "RCS Paris 999 999 999 FICTIF", "tva_intracom": "FR99999999999",
    "adresse_ligne": "1 rue de l'Exemple FICTIVE", "code_postal": "75001", "ville": "Paris",
    "email": "facturation@controldone-fictif.test", "iban": "FR7630006000011234567890189", "bic": "AGRIFRPPXXX",
}

FACTURATION_A = {"siren": "000000001", "tva_intracom": "FR00000000001", "adresse_ligne": "10 avenue Fictive",
                 "code_postal": "69001", "ville": "Lyon", "email": "compta@client-a-fictif.test"}
FACTURATION_B = {"siren": "000000002", "adresse_ligne": "5 quai Fictif", "code_postal": "13002", "ville": "Marseille",
                 "livraison_ligne": "Entrepôt FICTIF, 3 rue du Port", "livraison_code_postal": "13015",
                 "livraison_ville": "Marseille"}



def approuver(db: Database, action_id: str) -> None:
    from controldone.outbox import FileSortante

    FileSortante(db).approuver(action_id, FONDATEUR)


def chemin_config() -> Path:
    return CONFIG
