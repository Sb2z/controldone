"""Préparation des déclarations MACF (CBAM) en délégation — voir ``docs/MACF.md``.

Le produit ne dépose aucune déclaration MACF, ne dit pas si le MACF s'applique et ne se prononce ni sur
le classement ni sur les valeurs d'émissions. Il PRÉPARE un pack de données pour le client ou son
déclarant MACF autorisé :

1. ``selection`` : articles des déclarations traitées dont le code imprimé figure dans la liste
   versionnée ``config/macf_codes_nc.yaml`` (``codes``) — chaque ligne « à faire vérifier » ;
2. ``agregation`` : masses nettes par code, origine, fournisseur, installation, période ; cumul annuel
   comparé arithmétiquement au seuil de 50 t, suivi de la phrase de renvoi ;
3. ``demandes`` : données à obtenir des fournisseurs et brouillons de demande (file sortante, jamais envoyés) ;
4. ``export`` : CSV, XLSX, synthèse PDF marqués « préparation — à vérifier par le déclarant MACF autorisé ».
"""

from controldone.macf.agregation import Agregat, SyntheseSeuil, agreger, synthese_seuil
from controldone.macf.codes import CorrespondanceCode, ListeCodesMACF, StatutCode, charger_liste
from controldone.macf.demandes import (
    DONNEES_A_DEMANDER,
    MENTION_PREPARATION,
    brouillons_demandes,
    proposer_brouillons,
)
from controldone.macf.export import PackMACF, ecrire_csv, ecrire_pack, ecrire_pdf, ecrire_xlsx, preparer_pack
from controldone.macf.selection import LigneMACF, lignes_depuis_scope, masse_kg, selectionner_lignes

__all__ = [
    "DONNEES_A_DEMANDER",
    "MENTION_PREPARATION",
    "Agregat",
    "CorrespondanceCode",
    "LigneMACF",
    "ListeCodesMACF",
    "PackMACF",
    "StatutCode",
    "SyntheseSeuil",
    "agreger",
    "brouillons_demandes",
    "charger_liste",
    "ecrire_csv",
    "ecrire_pack",
    "ecrire_pdf",
    "ecrire_xlsx",
    "lignes_depuis_scope",
    "masse_kg",
    "preparer_pack",
    "proposer_brouillons",
    "selectionner_lignes",
    "synthese_seuil",
]
