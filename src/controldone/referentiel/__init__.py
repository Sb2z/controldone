"""Référentiel anonymisé de long terme (voir ``docs/REFERENTIEL.md``) : prix et taux d'écart par
transitaire × flux, k-anonymat (≥ 5 clients et ≥ 10 dossiers), arrondis, opt-out par client."""

from controldone.referentiel.anonymisation import (
    arrondir_montant,
    arrondir_taux,
    charger_alias_publics,
    cle_transitaire,
    famille_incoterm,
    groupe_pays,
    regime_declaration,
    tranche_effectif,
)
from controldone.referentiel.calcul import Agregat, EnregistrementFlux, ResultatReferentiel, Seuils, agreger
from controldone.referentiel.collecte import collecter, opt_out
from controldone.referentiel.export import SCHEMA_REFERENTIEL, en_csv, en_json, recalculer, sel_referentiel

__all__ = [
    "SCHEMA_REFERENTIEL",
    "Agregat",
    "EnregistrementFlux",
    "ResultatReferentiel",
    "Seuils",
    "agreger",
    "arrondir_montant",
    "arrondir_taux",
    "charger_alias_publics",
    "cle_transitaire",
    "collecter",
    "en_csv",
    "en_json",
    "famille_incoterm",
    "groupe_pays",
    "opt_out",
    "recalculer",
    "regime_declaration",
    "sel_referentiel",
    "tranche_effectif",
]
