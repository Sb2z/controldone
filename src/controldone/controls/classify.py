"""Classement « écart certain » / « à vérifier » (SPEC §8.5.1) et montant en jeu (§8.6)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from decimal import Decimal
from typing import NamedTuple

from controldone.controls.specs import ControlSpec, get_spec
from controldone.controls.tolerances import arrondi_centime
from controldone.model.dossier import Allocation, LienDocument
from controldone.model.enums import (
    MethodeAllocation,
    NatureMontant,
    Niveau,
    Outcome,
    RaisonCode,
    Sens,
    TauxChangeSens,
)
from controldone.model.resultats import RAISONS_INFORMATIVES
from controldone.model.valeur import ValeurSourcee

__all__ = [
    "Classement",
    "classify",
    "eur_par_devise",
    "montant_arithmetique",
    "montant_ecart_documentaire",
    "montant_pour_spec",
    "montant_recouvrable",
    "sens_pour",
    "trier_raisons",
]

_ORDRE_RAISONS = {r: i for i, r in enumerate(RaisonCode)}


def trier_raisons(raisons: Iterable[RaisonCode]) -> tuple[RaisonCode, ...]:
    """Dédoublonne et trie les raisons dans l'ordre canonique de l'énumération (sortie déterministe)."""
    return tuple(sorted(set(raisons), key=_ORDRE_RAISONS.__getitem__))


class Classement(NamedTuple):
    """Résultat de ``classify`` : ``(niveau, raisons)``. ``niveau is None`` signifie ``conforme``."""

    niveau: Niveau | None
    raisons: tuple[RaisonCode, ...]

    @property
    def outcome(self) -> Outcome:
        return Outcome.conforme if self.niveau is None else self.niveau.outcome

    @property
    def est_constat(self) -> bool:
        return self.niveau is not None


def classify(
    spec: ControlSpec | str,
    *,
    ecart: Decimal | None,
    tolerance: Decimal | None,
    seuil_certitude: Decimal | None,
    valeurs_cles: Sequence[ValeurSourcee],
    c_min_certain: float,
    liens: Sequence[LienDocument] = (),
    allocations: Sequence[Allocation] = (),
    lecture_douteuse: bool = False,
    explication: RaisonCode | None = None,
    renvoi: bool = False,
    eligible: bool | None = None,
    nature_montant: NatureMontant | None = None,
    montant: Decimal | None = None,
    raisons_supplementaires: Iterable[RaisonCode] = (),
) -> Classement:
    """Applique la règle générale de §8.5.1.

    - ``ecart`` : écart numérique ``b − a`` ; ``None`` pour un constat qualitatif (entité, devise,
      référence…) : la condition 2 est alors réputée remplie.
    - Si ``|ecart| ≤ tolerance`` (et pas de renvoi) : ``conforme``.
    - Sinon ``ecart_certain`` si et seulement si les 8 conditions sont vraies, ``a_verifier`` sinon,
      avec les raisons (§8.5.3) de chaque condition non remplie :

      1. contrôle éligible (Annexe A ; ``eligible`` surcharge, ex. B4 (b)) — ``controle_signal_seulement`` ;
      2. ``|écart| > seuil_certitude`` — ``ecart_sous_seuil`` ;
      3. chaque valeur clé : ``confiance ≥ c_min_certain`` — ``confiance_insuffisante`` ; ancrée ou
         structurée/saisie — ``valeur_non_ancree`` ; raisons mémorisées sur la valeur (ex.
         ``extracteurs_en_desaccord``) reprises ;
      4. aucune valeur clé n'est un total ``reconstruit`` — ``total_reconstruit`` (lecture prudente :
         tout total reconstruit parmi les valeurs clés suffit, D-016) ;
      5. liens ``forte``/``manuelle`` — ``rattachement_faible`` ; aucune allocation ``prorata`` —
         ``allocation_prorata`` ;
      6. test de confusion négatif — ``lecture_douteuse`` (calculé par l'appelant, voir
         ``ControlContext.classify``) ;
      7. aucune explication documentée — ``explication`` (ex. ``ecart_explique_par_ligne_de_pied``,
         ``version_rectificative``, ``avoir_impute``) ;
      8. pas de renvoi — ``renvoi_reglementaire``.

    En plus : un montant ``recouvrable`` négatif (écart en faveur du client) est toujours
    ``a_verifier`` (§8.6), raison ``ecart_en_faveur_client``.
    """
    sp = get_spec(spec) if isinstance(spec, str) else spec
    if ecart is not None and tolerance is not None and abs(ecart) <= tolerance and not renvoi:
        return Classement(None, ())

    raisons: list[RaisonCode] = list(raisons_supplementaires)
    # 1
    ok_eligible = sp.eligible_certain if eligible is None else eligible
    if not ok_eligible:
        raisons.append(RaisonCode.controle_signal_seulement)
    # 2
    if ecart is not None and seuil_certitude is not None and abs(ecart) <= seuil_certitude:
        raisons.append(RaisonCode.ecart_sous_seuil)
    # 3 et 4
    for v in valeurs_cles:
        if v.confiance < c_min_certain:
            raisons.append(RaisonCode.confiance_insuffisante)
        if not v.ancrage_suffisant():
            raisons.append(RaisonCode.valeur_non_ancree)
        if v.est_reconstruite:
            raisons.append(RaisonCode.total_reconstruit)
        raisons.extend(v.raisons)
    # 5
    if any(not lien.force.est_solide for lien in liens):
        raisons.append(RaisonCode.rattachement_faible)
    if any(a.methode is MethodeAllocation.prorata for a in allocations):
        raisons.append(RaisonCode.allocation_prorata)
    # 6, 7, 8
    if lecture_douteuse:
        raisons.append(RaisonCode.lecture_douteuse)
    if explication is not None:
        raisons.append(explication)
    if renvoi:
        raisons.append(RaisonCode.renvoi_reglementaire)
    # §8.6 : écart en faveur du client
    nature = nature_montant or sp.nature_montant
    signe = montant if montant is not None else ecart
    if nature is NatureMontant.recouvrable and signe is not None and signe < 0:
        raisons.append(RaisonCode.ecart_en_faveur_client)

    triees = trier_raisons(raisons)
    doute = [r for r in triees if r not in RAISONS_INFORMATIVES]
    return Classement(Niveau.a_verifier if doute else Niveau.ecart_certain, triees)


# --- Montant en jeu (§8.6) -----------------------------------------------------------------------


def montant_recouvrable(refacture: Decimal, reference: Decimal) -> Decimal:
    """``recouvrable`` : montant refacturé − montant de référence, en EUR, au centime.
    ``> 0`` : refacturé au-delà de la référence (en défaveur du client)."""
    return arrondi_centime(refacture - reference)


def eur_par_devise(taux: Decimal, sens: TauxChangeSens | str) -> Decimal:
    """Taux exprimé en EUR par unité de devise (§8.7), sans arrondi."""
    if TauxChangeSens(sens) is TauxChangeSens.eur_par_devise:
        return taux
    if taux == 0:
        raise ValueError("taux de change nul")
    return Decimal(1) / taux


def montant_ecart_documentaire(
    declare: Decimal,
    reference: Decimal,
    *,
    devise: str | None,
    taux_eur_par_devise: Decimal | None = None,
) -> Decimal | None:
    """``ecart_documentaire`` : valeur comparée − valeur de référence, convertie en EUR au **taux imprimé**
    de la déclaration ; ``None`` si la conversion est impossible (devise non EUR sans taux)."""
    ecart = declare - reference
    if devise == "EUR":
        return arrondi_centime(ecart)
    if taux_eur_par_devise is None:
        return None
    return arrondi_centime(ecart * taux_eur_par_devise)


def montant_arithmetique(imprime: Decimal, recalcule: Decimal) -> Decimal:
    """``arithmetique_declaration`` : montant imprimé − montant recalculé (> 0 : imprimé supérieur)."""
    return arrondi_centime(imprime - recalcule)


def montant_pour_spec(
    spec: ControlSpec | str, montant: Decimal | None, *, renvoi: bool = False
) -> Decimal | None:
    """Applique les règles de nature : ``renvoi``/``aucun`` -> ``None`` ; sinon arrondi au centime."""
    sp = get_spec(spec) if isinstance(spec, str) else spec
    if renvoi or not sp.montant_autorise or montant is None:
        return None
    return arrondi_centime(montant)


def sens_pour(nature: NatureMontant | None, montant: Decimal | None) -> Sens | None:
    """``sens`` d'un constat : défini pour les montants ``recouvrable`` seulement."""
    if nature is not NatureMontant.recouvrable or montant is None or montant == 0:
        return None
    return Sens.defaveur_client if montant > 0 else Sens.faveur_client
