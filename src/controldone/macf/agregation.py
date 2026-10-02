"""Agrégation des masses nettes lues et comparaison ARITHMÉTIQUE au seuil annuel de 50 t.

Le cumul porte uniquement sur les déclarations traitées par ControlDOne (pas sur toutes les importations
du client) et exclut l'électricité et l'hydrogène (secteurs ``hors_cumul_50t`` de la liste). Le texte
produit est un calcul, suivi de la phrase de renvoi : il ne dit jamais si le seuil s'applique.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal

from controldone.formatage import format_nombre
from controldone.guardrails import PHRASE_RENVOI, assert_clean
from controldone.macf.selection import LigneMACF

__all__ = ["Agregat", "SyntheseSeuil", "agreger", "synthese_seuil"]

_MILLE = Decimal(1000)


@dataclass(frozen=True)
class Agregat:
    periode: str
    code_imprime: str
    pays_origine: str
    fournisseur: str
    installation: str
    secteur: str
    nombre_lignes: int
    masse_nette_kg: Decimal
    lignes_sans_masse: int
    dossiers: tuple[str, ...]


def _cle(x: str | None, defaut: str) -> str:
    return x if x else defaut


def agreger(lignes: Iterable[LigneMACF], *, annee: int | None = None) -> list[Agregat]:
    """Masse nette par période (trimestre), code imprimé, pays d'origine, fournisseur, installation."""
    groupes: dict[tuple[str, ...], list[LigneMACF]] = {}
    for li in lignes:
        if annee is not None and li.annee != annee:
            continue
        cle = (li.periode, _cle(li.code_imprime, "non lu"), _cle(li.pays_origine, "non lu"),
               _cle(li.fournisseur, "non lu"), _cle(li.installation, "à demander au fournisseur"),
               _cle(li.secteur_libelle, "—"))
        groupes.setdefault(cle, []).append(li)
    sortie = []
    for cle in sorted(groupes):
        ls = groupes[cle]
        masses = [li.masse_nette_kg for li in ls if li.masse_nette_kg is not None]
        sortie.append(Agregat(*cle, nombre_lignes=len(ls), masse_nette_kg=sum(masses, Decimal("0.000")),
                              lignes_sans_masse=len(ls) - len(masses),
                              dossiers=tuple(sorted({li.dossier_reference or li.dossier_id for li in ls}))))
    return sortie


@dataclass(frozen=True)
class SyntheseSeuil:
    annee: int
    seuil_t: Decimal
    masse_cumulee_kg: Decimal
    lignes_comptees: int
    lignes_sans_masse: int
    lignes_hors_cumul: int
    lignes_sans_date: int
    textes: list[str] = field(default_factory=list)

    @property
    def masse_cumulee_t(self) -> Decimal:
        return (self.masse_cumulee_kg / _MILLE).quantize(Decimal("0.001"))

    @property
    def difference_t(self) -> Decimal:
        """Seuil moins masse cumulée lue (négatif si la masse lue est supérieure au seuil)."""
        return (self.seuil_t - self.masse_cumulee_t).quantize(Decimal("0.001"))

    @property
    def texte(self) -> str:
        return "\n".join(self.textes)


def _t(x: Decimal) -> str:
    return f"{format_nombre(x, 3)} t"


def synthese_seuil(lignes: Iterable[LigneMACF], annee: int, *, seuil_t: Decimal | str = "50") -> SyntheseSeuil:
    """Cumul annuel des masses nettes lues comparé, par simple soustraction, au seuil cité."""
    seuil = Decimal(str(seuil_t))
    ls = list(lignes)
    sans_date = sum(1 for li in ls if li.annee is None)
    de_l_annee = [li for li in ls if li.annee == annee]
    hors = [li for li in de_l_annee if li.hors_cumul_50t]
    comptables = [li for li in de_l_annee if not li.hors_cumul_50t]
    avec_masse = [li for li in comptables if li.masse_nette_kg is not None]
    total = sum((li.masse_nette_kg for li in avec_masse), Decimal("0.000"))
    s = SyntheseSeuil(annee=annee, seuil_t=seuil, masse_cumulee_kg=total, lignes_comptees=len(avec_masse),
                      lignes_sans_masse=len(comptables) - len(avec_masse), lignes_hors_cumul=len(hors),
                      lignes_sans_date=sans_date)
    d = s.difference_t
    if d >= 0:
        comparaison = f"Calcul : {_t(seuil)} - {_t(s.masse_cumulee_t)} = {_t(d)} (masse lue inférieure ou égale au seuil cité)."
    else:
        comparaison = f"Calcul : {_t(s.masse_cumulee_t)} - {_t(seuil)} = {_t(-d)} (masse lue supérieure au seuil cité)."
    textes = [
        f"Année {annee} : masse nette cumulée lue sur {s.lignes_comptees} ligne(s) de déclaration traitée(s) "
        f"par ControlDOne dont le code imprimé figure dans la liste MACF : {_t(s.masse_cumulee_t)} "
        f"(électricité et hydrogène exclus du cumul).",
        f"Seuil annuel de {_t(seuil)} cité par la source (DEHSt, voir docs/MACF.md). {comparaison}",
        "Ce cumul ne porte que sur les dossiers transmis à ControlDOne, pas sur l'ensemble de vos importations.",
    ]
    if s.lignes_sans_masse:
        textes.append(f"{s.lignes_sans_masse} ligne(s) sans masse nette lisible ne sont pas comptée(s) : "
                      "masse à compléter.")
    if sans_date:
        textes.append(f"{sans_date} ligne(s) sans date d'acceptation lisible ne sont rattachée(s) à aucune année.")
    textes.append(PHRASE_RENVOI)
    for t in textes:
        assert_clean(t)
    return SyntheseSeuil(**{**s.__dict__, "textes": textes})
