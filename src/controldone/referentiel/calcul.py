"""Calcul du référentiel anonymisé (pur, déterministe) : agrégats de prix et de taux d'écart par
transitaire × flux (groupe de pays d'origine, régime, famille d'Incoterm, mois).

Transitaire **nommé** (alias public, accord écrit) : **statistiques de prix seulement** — jamais de taux
d'écart ou d'erreur attribué à un transitaire identifiable (brief juridique §5.4, D-1318) ;
``taux_dossiers_avec_ecart`` vaut alors ``None`` (vide à l'export).

Seuils de publication (k-anonymat) : un agrégat n'est publié que s'il réunit au moins ``k_clients``
clients distincts (défaut 5) **et** ``k_dossiers`` dossiers (défaut 10) ; une statistique de prix d'une
prestation n'est publiée que si elle-même réunit ces deux seuils. Les agrégats supprimés ne sont que
comptés. Aucun identifiant n'entre dans un agrégat : ni client, ni dossier, ni numéro de document, ni
nom ou TVA (hors alias public), ni adresse.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal

from .anonymisation import (
    AliasPublics,
    arrondir_montant,
    arrondir_taux,
    cle_transitaire,
    famille_incoterm,
    groupe_pays,
    percentile,
    regime_declaration,
    tranche_effectif,
)

__all__ = ["Agregat", "EnregistrementFlux", "ResultatReferentiel", "Seuils", "agreger"]


@dataclass(frozen=True)
class EnregistrementFlux:
    """Un dossier validé, avant anonymisation (jamais exporté tel quel)."""

    client_id: str
    transitaire_nom: str | None
    transitaire_tva: str | None
    pays_origine: str | None
    incoterm: str | None
    sous_type_declaration: str | None
    mois: str  # AAAA-MM
    avec_ecart: bool  # au moins un constat « écart certain » validé
    prix: dict[str, Decimal] = field(default_factory=dict)  # nature de prestation -> montant HT (EUR)


@dataclass(frozen=True)
class Seuils:
    k_clients: int = 5
    k_dossiers: int = 10


@dataclass
class Agregat:
    transitaire: str
    groupe_origine: str
    regime: str
    famille_incoterm: str
    mois: str
    dossiers: str  # tranche
    taux_dossiers_avec_ecart: Decimal | None  # arrondi au pas de 5 points ; None pour un transitaire nommé
    prix: dict[str, dict[str, Decimal]] = field(default_factory=dict)  # nature -> {p25, mediane, p75}
    nomme: bool = False  # alias public (accord écrit) : prix seulement

    def cle(self) -> tuple[str, ...]:
        return (self.transitaire, self.groupe_origine, self.regime, self.famille_incoterm, self.mois)


@dataclass
class ResultatReferentiel:
    agregats: list[Agregat]
    supprimes: int  # agrégats non publiés (sous les seuils)
    seuils: Seuils


def agreger(enregistrements: Iterable[EnregistrementFlux], *, sel: bytes, alias_publics: AliasPublics | None = None,
            seuils: Seuils | None = None) -> ResultatReferentiel:
    seuils = seuils or Seuils()
    groupes: dict[tuple[str, ...], list[EnregistrementFlux]] = defaultdict(list)
    for e in enregistrements:
        tra = cle_transitaire(e.transitaire_nom, e.transitaire_tva, sel=sel, alias_publics=alias_publics)
        if tra is None:
            continue
        cle = (tra, groupe_pays(e.pays_origine), regime_declaration(e.sous_type_declaration),
               famille_incoterm(e.incoterm), e.mois)
        groupes[cle].append(e)
    publies, supprimes = [], 0
    for cle in sorted(groupes):
        lot = groupes[cle]
        if len({e.client_id for e in lot}) < seuils.k_clients or len(lot) < seuils.k_dossiers:
            supprimes += 1
            continue
        taux = Decimal(sum(1 for e in lot if e.avec_ecart)) / Decimal(len(lot))
        prix: dict[str, dict[str, Decimal]] = {}
        natures = sorted({n for e in lot for n in e.prix})
        for nature in natures:
            porteurs = [e for e in lot if nature in e.prix]
            if len({e.client_id for e in porteurs}) < seuils.k_clients or len(porteurs) < seuils.k_dossiers:
                continue
            valeurs = [Decimal(e.prix[nature]) for e in porteurs]
            prix[nature] = {"p25": arrondir_montant(percentile(valeurs, 25)),
                            "mediane": arrondir_montant(percentile(valeurs, 50)),
                            "p75": arrondir_montant(percentile(valeurs, 75))}
        nomme = cle[0] in (alias_publics or {})
        publies.append(Agregat(*cle, dossiers=tranche_effectif(len(lot)),
                               taux_dossiers_avec_ecart=None if nomme else arrondir_taux(taux), prix=prix, nomme=nomme))
    return ResultatReferentiel(publies, supprimes, seuils)
