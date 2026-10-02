"""Famille B — Cohérence interne de la déclaration (SPEC §11).

La famille B prend les valeurs imprimées comme données : elle **ne juge jamais un taux**, une base ou
un code. La prochaine action de chaque constat B contient « Demander au déclarant l'explication de cet
écart de calcul. » suivie de la phrase de renvoi.

Ce module contient B1, **contrôle de référence** du cadre (voir docs/ARCHITECTURE.md, « Comment écrire
un contrôle »). B2 à B5 sont à ajouter ici.
"""

from __future__ import annotations

from decimal import Decimal

from controldone.controls.framework import (
    Confusion,
    ControlContext,
    arrondi_centime,
    cle_unite,
    control,
    montant_arithmetique,
    preuve,
)
from controldone.formatage import format_montant, format_nombre, format_pourcentage
from controldone.guardrails import PHRASE_RENVOI
from controldone.model import (
    CategorieTaxe,
    Composante,
    Document,
    RaisonCode,
    ResultatControle,
    RolePreuve,
    TauxNature,
    TaxationDeclaration,
    ValeurSourcee,
)

__all__ = ["ACTION_B", "b1_base_taux_montant"]

#: Prochaine action commune aux constats B (§11).
ACTION_B = "Demander au déclarant l'explication de cet écart de calcul. " + PHRASE_RENVOI

_COMPOSANTE = {
    CategorieTaxe.droit: Composante.droit,
    CategorieTaxe.autre_taxe: Composante.autre_taxe,
    CategorieTaxe.tva: Composante.tva,
    CategorieTaxe.forfait_petits_envois: Composante.forfait_petits_envois,
}
_CENT = Decimal(100)


def _nature_taux(t: TaxationDeclaration) -> TauxNature | None:
    """Nature du taux : imprimée, sinon déduite de la seule base présente ; ``None`` si indécidable."""
    if t.taux_nature is not None:
        return t.taux_nature
    a_base_montant = t.base_montant is not None and t.base_montant.est_lisible
    a_base_quantite = t.base_quantite is not None and t.base_quantite.est_lisible
    if a_base_montant and not a_base_quantite:
        return TauxNature.ad_valorem
    if a_base_quantite and not a_base_montant:
        return TauxNature.specifique
    return None


def _produit(base: Decimal, taux: Decimal, nature: TauxNature) -> Decimal:
    """Calcul exact, sans arrondi intermédiaire (§8.2)."""
    return base * taux / _CENT if nature is TauxNature.ad_valorem else base * taux


def _localisation(dec: Document, t: TaxationDeclaration) -> str:
    c = dec.dec
    mrn = c.mrn.valeur if c.mrn is not None and c.mrn.valeur else None
    page = t.montant.page if t.montant is not None else None
    ref = ", ".join(x for x in (f"MRN {mrn}" if mrn else None, f"page {page}" if page else None) if x)
    ref = f" ({ref})" if ref else ""
    if t.article is not None and t.article.valeur:
        return f"Sur l'article {t.article.valeur} de la déclaration{ref}"
    return f"Au niveau de la déclaration{ref}"


def _b1_ligne(ctx: ControlContext, dec: Document, index: int, t: TaxationDeclaration) -> ResultatControle:
    unite = cle_unite(dec=dec.id, tax=index)
    code_taxe = t.type_taxe.valeur if t.type_taxe is not None and t.type_taxe.valeur else "?"
    details = {"declaration_id": dec.id, "taxation": index, "type_taxe": code_taxe}
    nature = _nature_taux(t)
    base = t.base_montant if nature is TauxNature.ad_valorem else t.base_quantite
    requis: dict[str, ValeurSourcee | None] = {"base": base, "taux": t.taux, "montant": t.montant}

    # Données absentes ou trop douteuses : non vérifiable (P3, P-8), jamais conforme.
    if nature is None:
        return ctx.non_verifiable("B1", RaisonCode.valeur_absente, unite=unite, documents=[dec.id], details=details)
    for v in requis.values():
        if not ctx.utilisable(v):
            return ctx.non_verifiable(
                "B1", ctx.raison_inutilisable(v), unite=unite, documents=[dec.id], details=details,
                entrees={k: x for k, x in requis.items() if x is not None},
            )
    assert base is not None and t.taux is not None and t.montant is not None
    try:
        v_base, v_taux, v_montant = base.decimal_signe(), t.taux.decimal(), t.montant.decimal_signe()
    except ValueError:
        return ctx.non_verifiable("B1", RaisonCode.valeur_absente, unite=unite, documents=[dec.id], details=details)

    tol = ctx.tol
    calcul = _produit(v_base, v_taux, nature)
    ecart = v_montant - calcul
    commun = dict(
        unite=unite,
        entrees={"base": base, "taux": t.taux, "montant": t.montant},
        attendu=arrondi_centime(calcul),
        constate=v_montant,
        ecart=montant_arithmetique(v_montant, calcul),
        tolerance=tol.t_taxe_ligne(),
        seuil_certitude=tol.s_calcul_declaration(),
        documents=[dec.id],
        details=details,
    )
    if tol.taxe_ligne_concorde(v_montant, calcul):
        return ctx.conforme("B1", **commun)

    # Test de confusion (§8.5.4) sur chacune des trois valeurs imprimées.
    confusion = [
        Confusion(t.montant, accepte=lambda v: tol.taxe_ligne_concorde(v, calcul)),
        Confusion(base, accepte=lambda v: tol.taxe_ligne_concorde(v_montant, _produit(v, v_taux, nature))),
        Confusion(t.taux, accepte=lambda v: tol.taxe_ligne_concorde(v_montant, _produit(v_base, v, nature))),
    ]
    classement = ctx.classify(
        "B1",
        ecart=ecart,
        tolerance=tol.t_taxe_ligne(),
        seuil_certitude=tol.s_calcul_declaration(),
        valeurs_cles=[base, t.taux, t.montant],
        confusion=confusion,
    )

    if nature is TauxNature.ad_valorem:
        expr = f"{format_montant(v_base, None)} × {format_pourcentage(v_taux)}"
    else:
        unite_base = t.base_unite.valeur if t.base_unite is not None and t.base_unite.valeur else ""
        expr = f"{format_nombre(v_base)}{(' ' + unite_base) if unite_base else ''} × {format_montant(v_taux, 'EUR')}"
    calcul_txt = f"{expr} = {format_montant(arrondi_centime(calcul), 'EUR')}"
    libelle = (
        f"{_localisation(dec, t)}, le montant imprimé pour la taxe {code_taxe} "
        f"({format_montant(v_montant, 'EUR')}) diffère du produit base × taux imprimés ({calcul_txt})."
    )
    return ctx.constat(
        "B1",
        classement,
        libelle=libelle,
        prochaine_action=ACTION_B,
        montant=montant_arithmetique(v_montant, calcul),
        composante=_COMPOSANTE.get(t.categorie),
        preuves=[
            preuve(base, RolePreuve.operande),
            preuve(t.taux, RolePreuve.operande),
            preuve(t.montant, RolePreuve.valeur_b),
            preuve(None, RolePreuve.valeur_a, calcul=calcul_txt),
        ],
        **commun,
    )


@control("B1")
def b1_base_taux_montant(ctx: ControlContext) -> list[ResultatControle]:
    """B1 — Base × taux = montant, par ligne de taxation (hors forfait petits envois, traité par G1).

    - Unité : ligne de taxation (``cle_unite(dec=<id>, tax=<index>)``) de la dernière version de chaque
      déclaration.
    - Règle : ``calcul = base_montant × taux / 100`` (ad valorem) ou ``base_quantite × taux`` (spécifique) ;
      ``conforme`` si ``|montant − calcul| ≤ 0,01`` ou montant égal à l'arrondi à l'euro du calcul.
    - Classement : ``ecart_certain`` si ``|écart| > 1,00 EUR`` et règle générale ; sinon ``a_verifier``.
    - Montant : ``arithmetique_declaration`` = ``montant − calcul``.
    """
    declarations = ctx.declarations()
    if not declarations:
        return [ctx.non_verifiable("B1", RaisonCode.document_manquant)]
    resultats: list[ResultatControle] = []
    for dec in declarations:
        for i, t in enumerate(dec.dec.taxations):
            if t.categorie is CategorieTaxe.forfait_petits_envois:
                continue
            resultats.append(_b1_ligne(ctx, dec, i, t))
    return resultats
