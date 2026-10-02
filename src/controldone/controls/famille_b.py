"""Famille B — Cohérence interne de la déclaration (SPEC §11).

La famille B prend les valeurs imprimées comme données : elle **ne juge jamais un taux**, une base ou
un code. La prochaine action de chaque constat B contient « Demander au déclarant l'explication de cet
écart de calcul. » suivie de la phrase de renvoi.

Ce module contient B1, **contrôle de référence** du cadre (voir docs/ARCHITECTURE.md, « Comment écrire
un contrôle »). B2 à B5 suivent B1 (voir docs/DECISIONS.md, D-301 à D-303).
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from controldone.controls._aides_befg import num as _num
from controldone.controls.framework import (
    Classement,
    Confusion,
    ControlContext,
    arrondi_centime,
    cle_unite,
    control,
    eur_par_devise,
    montant_arithmetique,
    preuve,
)
from controldone.formatage import format_montant, format_nombre, format_pourcentage
from controldone.guardrails import PHRASE_RENVOI
from controldone.model import (
    CategorieTaxe,
    Composante,
    Document,
    PaiementNormalise,
    RaisonCode,
    ResultatControle,
    RolePreuve,
    TauxNature,
    TaxationDeclaration,
    ValeurSourcee,
)

__all__ = [
    "ACTION_B",
    "b1_base_taux_montant",
    "b2_sommes_taxes",
    "b3_somme_montants_articles",
    "b4_masses",
    "b5_colis",
]

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


# =====================================================================================================
# B2 à B5 — aides communes
# =====================================================================================================

_ZERO = Decimal(0)


def _ref_declaration(dec: Document, v: ValeurSourcee | None = None) -> str:
    """« la déclaration (MRN …, page …) » — document et page cités (§3.1)."""
    c = dec.dec
    mrn = c.mrn.valeur if c.mrn is not None and c.mrn.valeur else None
    page = v.page if v is not None else None
    ref = ", ".join(x for x in (f"MRN {mrn}" if mrn else None, f"page {page}" if page else None) if x)
    return f"la déclaration ({ref})" if ref else "la déclaration"


def _articles_tous_lus(dec: Document) -> bool:
    """Condition B2/B3 : nombre d'articles lus = ``nombre_articles`` imprimé (lu ≥ C_MIN_UTILE)."""
    c = dec.dec
    if c.nombre_articles is None or not c.nombre_articles.est_lisible:
        return False
    try:
        imprime = c.nombre_articles.entier()
    except ValueError:
        return False
    numeros = {a.numero_article.valeur for a in c.articles if a.numero_article is not None and a.numero_article.valeur}
    lus = len(numeros) if numeros else len(c.articles)
    if not c.articles:
        lus = len({t.article.valeur for t in c.taxations if t.article is not None and t.article.valeur})
    return lus == imprime


def _confusions_somme(
    total: ValeurSourcee,
    v_total: Decimal,
    operandes: Sequence[tuple[ValeurSourcee, Decimal]],
    somme: Decimal,
    tolerance: Decimal,
) -> list[Confusion]:
    """Test de confusion (§8.5.4) sur le total imprimé et sur chacune des lignes sommées."""
    out = [Confusion(total, autre=somme, tolerance=tolerance)]
    for v, x in operandes:
        def accepte(var: Decimal, x: Decimal = x) -> bool:
            return abs(v_total - (somme - x + var)) <= tolerance

        out.append(Confusion(v, accepte=accepte))
    return out


# =====================================================================================================
# B2 — Sommes des taxes
# =====================================================================================================


def _code_taxe(t: TaxationDeclaration) -> str:
    return (t.type_taxe.valeur or "").strip().upper() if t.type_taxe is not None and t.type_taxe.valeur else ""


def _montant_taxe(t: TaxationDeclaration) -> ValeurSourcee | None:
    """Montant imprimé de la taxe (à défaut, montant à payer)."""
    return t.montant if t.montant is not None else t.montant_a_payer


def _totaux_par_categorie(dec: Document) -> dict[str, tuple[int, list[int]]]:
    """Totaux de catégorie imprimés (D-301) : pour un code de taxe, **une seule** ligne de niveau
    déclaration (sans article) **et** au moins une ligne par article -> la ligne sans article est le
    total imprimé de la catégorie. Retourne ``{code: (index_total, [index_lignes_articles])}``."""
    par_code: dict[str, tuple[list[int], list[int]]] = {}
    for i, t in enumerate(dec.dec.taxations):
        code = _code_taxe(t)
        if not code:
            continue
        sans, avec = par_code.setdefault(code, ([], []))
        (avec if t.article is not None and t.article.valeur else sans).append(i)
    return {code: (sans[0], avec) for code, (sans, avec) in par_code.items() if len(sans) == 1 and avec}


def _b2_categorie(ctx: ControlContext, dec: Document, code: str, i_total: int, lignes: list[int]) -> ResultatControle:
    taxations = dec.dec.taxations
    unite = cle_unite(dec=dec.id, taxe=code)
    details = {"declaration_id": dec.id, "type_taxe": code, "total": i_total, "lignes": lignes}
    total = _montant_taxe(taxations[i_total])
    operandes_vs = [_montant_taxe(taxations[i]) for i in lignes]
    for v in [total, *operandes_vs]:
        if not ctx.utilisable(v) or _num(v) is None:
            return ctx.non_verifiable(
                "B2", ctx.raison_inutilisable(v) if not ctx.utilisable(v) else RaisonCode.valeur_absente,
                unite=unite, sous_controle="categorie", documents=[dec.id], details=details,
            )
    assert total is not None
    v_total = _num(total) or _ZERO
    operandes = [(v, _num(v) or _ZERO) for v in operandes_vs if v is not None]
    somme = sum((x for _, x in operandes), _ZERO)
    return _b2_resultat(
        ctx, dec, unite=unite, sous_controle="categorie", total=total, v_total=v_total, operandes=operandes,
        somme=somme, details=details, objet=f"le total imprimé de la taxe {code}",
        composante=_COMPOSANTE.get(taxations[i_total].categorie),
    )


def _b2_resultat(
    ctx: ControlContext,
    dec: Document,
    *,
    unite: str,
    sous_controle: str,
    total: ValeurSourcee,
    v_total: Decimal,
    operandes: list[tuple[ValeurSourcee, Decimal]],
    somme: Decimal,
    details: dict,
    objet: str,
    composante: Composante | None,
    concorde: bool | None = None,
) -> ResultatControle:
    tol = ctx.tol
    n = len(operandes)
    t_somme = tol.t_somme(n)
    ecart = v_total - somme
    commun = dict(
        unite=unite, sous_controle=sous_controle,
        entrees={"total": total, **{f"ligne_{k}": v for k, (v, _) in enumerate(operandes)}},
        attendu=arrondi_centime(somme), constate=v_total, ecart=montant_arithmetique(v_total, somme),
        tolerance=t_somme, seuil_certitude=tol.s_calcul_declaration(), documents=[dec.id], details=details,
    )
    if concorde if concorde is not None else abs(ecart) <= t_somme:
        return ctx.conforme("B2", **commun)
    raisons = [] if _articles_tous_lus(dec) else [RaisonCode.valeur_absente]
    classement = ctx.classify(
        "B2", ecart=ecart, tolerance=t_somme, seuil_certitude=tol.s_calcul_declaration(),
        valeurs_cles=[total, *(v for v, _ in operandes)],
        confusion=_confusions_somme(total, v_total, operandes, somme, t_somme),
        raisons_supplementaires=raisons,
    )
    calcul_txt = (
        f"somme des {n} montants imprimés = {format_montant(arrondi_centime(somme), 'EUR')}"
    )
    libelle = (
        f"Sur {_ref_declaration(dec, total)}, {objet} ({format_montant(v_total, 'EUR')}) diffère de la "
        f"somme des {n} montants de taxe imprimés ({format_montant(arrondi_centime(somme), 'EUR')})."
    )
    if RaisonCode.valeur_absente in raisons:
        libelle += " Le nombre d'articles lus ne correspond pas au nombre d'articles imprimé : une ligne non lue peut expliquer l'écart."
    return ctx.constat(
        "B2", classement, libelle=libelle, prochaine_action=ACTION_B,
        montant=montant_arithmetique(v_total, somme), composante=composante,
        preuves=[
            preuve(total, RolePreuve.valeur_b),
            *(preuve(v, RolePreuve.operande) for v, _ in operandes),
            preuve(None, RolePreuve.valeur_a, calcul=calcul_txt),
        ],
        **commun,
    )


def _b2_total(ctx: ControlContext, dec: Document, exclus: set[int]) -> ResultatControle | None:
    c = dec.dec
    unite = cle_unite(dec=dec.id)
    totaux = [(nom, v) for nom, v in (("total_droits_taxes", c.total_droits_taxes), ("total_a_payer", c.total_a_payer))
              if v is not None]
    indices = [i for i in range(len(c.taxations)) if i not in exclus]
    details: dict = {"declaration_id": dec.id, "lignes": indices}
    if not totaux or not indices:
        return ctx.non_applicable("B2", RaisonCode.valeur_absente, unite=unite, sous_controle="total",
                                  documents=[dec.id], details={**details, "motif": "total ou lignes absents"})
    lignes = [(i, _montant_taxe(c.taxations[i])) for i in indices]
    for v in [*(v for _, v in totaux), *(v for _, v in lignes)]:
        if not ctx.utilisable(v) or _num(v) is None:
            return ctx.non_verifiable(
                "B2", ctx.raison_inutilisable(v) if not ctx.utilisable(v) else RaisonCode.valeur_absente,
                unite=unite, sous_controle="total", documents=[dec.id], details=details,
            )
    tout = [(v, _num(v) or _ZERO) for _, v in lignes if v is not None]
    # TVA autoliquidée : mode de paiement de la ligne, ou, pour une ligne de TVA dont le mode n'est pas lu,
    # indice d'autoliquidation de la déclaration (code 1008 + TVA, FR7 : §12.1) — D-710.
    indice = any(ctx.utilisable(ind.valeur) or ctx.utilisable(ind.tva) for ind in c.indices_autoliquidation)

    def autoliquidee(t: TaxationDeclaration) -> bool:
        if t.paiement_normalise is PaiementNormalise.autoliquide:
            return True
        return indice and t.categorie is CategorieTaxe.tva and t.paiement_normalise is PaiementNormalise.inconnu

    hors_autoliq = [(v, _num(v) or _ZERO) for i, v in lignes if v is not None and not autoliquidee(c.taxations[i])]
    hypotheses = {"tva_autoliquidee_incluse": tout, "tva_autoliquidee_exclue": hors_autoliq}
    # Conforme si l'un des totaux imprimés concorde avec l'une des deux hypothèses (§11 B2).
    for nom_total, v_tot in totaux:
        vt = _num(v_tot) or _ZERO
        for nom_h, ops in hypotheses.items():
            s = sum((x for _, x in ops), _ZERO)
            if abs(vt - s) <= ctx.tol.t_somme(len(ops)):
                return _b2_resultat(
                    ctx, dec, unite=unite, sous_controle="total", total=v_tot, v_total=vt, operandes=ops, somme=s,
                    details={**details, "total": nom_total, "hypothese": nom_h}, objet="", composante=None,
                    concorde=True,
                )
    # Écart : total de référence = total_droits_taxes s'il est imprimé ; hypothèse la plus proche.
    nom_total, v_tot = totaux[0]
    vt = _num(v_tot) or _ZERO
    nom_h, ops = min(hypotheses.items(), key=lambda kv: (abs(vt - sum((x for _, x in kv[1]), _ZERO)), kv[0]))
    s = sum((x for _, x in ops), _ZERO)
    objet = ("le montant total des droits et taxes imprimé" if nom_total == "total_droits_taxes"
             else "le total à payer imprimé")
    return _b2_resultat(
        ctx, dec, unite=unite, sous_controle="total", total=v_tot, v_total=vt, operandes=ops, somme=s,
        details={**details, "total": nom_total, "hypothese": nom_h}, objet=objet, composante=None,
    )


@control("B2")
def b2_sommes_taxes(ctx: ControlContext) -> list[ResultatControle]:
    """B2 — Sommes des taxes (§11), par déclaration (dernière version).

    (a) ``sous_controle="categorie"`` : pour chaque code de taxe portant un total de catégorie imprimé
    (ligne sans article, voir ``_totaux_par_categorie``), Σ montants par article contre ce total ;
    (b) ``sous_controle="total"`` : Σ des lignes (hors totaux de catégorie) contre ``total_droits_taxes``
    ou ``total_a_payer``, TVA autoliquidée incluse ou exclue (``conforme`` si une hypothèse concorde).
    Tolérance ``T_SOMME(n)`` ; ``ecart_certain`` si ``|écart| > 1,00 EUR``, tous les articles lus et
    règle générale. Montant ``arithmetique_declaration`` = total imprimé − somme.
    """
    declarations = ctx.declarations()
    if not declarations:
        return [ctx.non_verifiable("B2", RaisonCode.document_manquant)]
    resultats: list[ResultatControle] = []
    for dec in declarations:
        totaux = _totaux_par_categorie(dec)
        for code, (i_total, lignes) in sorted(totaux.items()):
            resultats.append(_b2_categorie(ctx, dec, code, i_total, lignes))
        r = _b2_total(ctx, dec, {i for i, _ in totaux.values()})
        if r is not None:
            resultats.append(r)
    return resultats


# =====================================================================================================
# B3 — Somme des montants facturés des articles
# =====================================================================================================


def _b3_declaration(ctx: ControlContext, dec: Document) -> ResultatControle:
    c = dec.dec
    unite = cle_unite(dec=dec.id)
    details: dict = {"declaration_id": dec.id}
    montants = [a.montant_facture_article for a in c.articles]
    presents = [v for v in montants if v is not None]
    if c.montant_total_facture is None or not presents:
        return ctx.non_applicable("B3", RaisonCode.valeur_absente, unite=unite, documents=[dec.id], details=details)
    if len(presents) != len(montants):
        return ctx.non_verifiable("B3", RaisonCode.valeur_absente, unite=unite, documents=[dec.id],
                                  details={**details, "articles_sans_montant": len(montants) - len(presents)})
    for v in [c.montant_total_facture, *presents]:
        if not ctx.utilisable(v) or _num(v) is None:
            return ctx.non_verifiable(
                "B3", ctx.raison_inutilisable(v) if not ctx.utilisable(v) else RaisonCode.valeur_absente,
                unite=unite, documents=[dec.id], details=details,
            )
    total = c.montant_total_facture
    v_total = _num(total) or _ZERO
    operandes = [(v, _num(v) or _ZERO) for v in presents]
    somme = sum((x for _, x in operandes), _ZERO)
    devise = (c.devise_facture.valeur or "").upper() if c.devise_facture is not None and c.devise_facture.valeur else None
    tol = ctx.tol
    t_somme = tol.t_somme(len(operandes))
    ecart = v_total - somme
    commun = dict(
        unite=unite, entrees={"total": total, **{f"article_{k}": v for k, (v, _) in enumerate(operandes)}},
        attendu=somme, constate=v_total, ecart=ecart, tolerance=t_somme,
        seuil_certitude=tol.s_calcul_declaration(), documents=[dec.id], details={**details, "devise": devise},
    )
    if abs(ecart) <= t_somme:
        return ctx.conforme("B3", **commun)

    # Montant en EUR (§8.6) : direct si EUR, sinon au taux imprimé de la déclaration (§8.7).
    raisons: list[RaisonCode] = [] if _articles_tous_lus(dec) else [RaisonCode.valeur_absente]
    valeurs_cles = [total, *presents]
    montant: Decimal | None
    ecart_eur: Decimal | None
    if devise == "EUR":
        montant, ecart_eur = montant_arithmetique(v_total, somme), ecart
    else:
        taux = _num(c.taux_change) if ctx.utilisable(c.taux_change) else None
        sens = c.taux_change_sens.valeur if c.taux_change_sens is not None and c.taux_change_sens.valeur else None
        if devise and taux and sens in ("eur_par_devise", "devise_par_eur"):
            ecart_eur = ecart * eur_par_devise(taux, sens)
            montant = arrondi_centime(ecart_eur)
            assert c.taux_change is not None and c.taux_change_sens is not None
            valeurs_cles += [c.taux_change, c.taux_change_sens]
            raisons.append(RaisonCode.montant_converti)
        else:
            montant, ecart_eur = None, None
            raisons.append(RaisonCode.devise_incertaine if not devise else RaisonCode.valeur_absente)
    classement = ctx.classify(
        "B3", ecart=ecart_eur if ecart_eur is not None else ecart, tolerance=None,
        seuil_certitude=tol.s_calcul_declaration() if ecart_eur is not None else None,
        valeurs_cles=valeurs_cles,
        confusion=_confusions_somme(total, v_total, operandes, somme, t_somme),
        raisons_supplementaires=raisons,
    )
    unite_dev = devise or None
    libelle = (
        f"Sur {_ref_declaration(dec, total)}, le montant total facturé imprimé "
        f"({format_montant(v_total, unite_dev)}) diffère de la somme des montants facturés imprimés sur les "
        f"{len(operandes)} articles ({format_montant(somme, unite_dev)})."
    )
    return ctx.constat(
        "B3", classement, libelle=libelle, prochaine_action=ACTION_B, montant=montant, composante=Composante.valeur,
        preuves=[
            preuve(total, RolePreuve.valeur_b),
            *(preuve(v, RolePreuve.operande) for v, _ in operandes),
            preuve(None, RolePreuve.valeur_a, calcul=f"somme des montants des articles = {format_montant(somme, unite_dev)}"),
        ],
        **commun,
    )


@control("B3")
def b3_somme_montants_articles(ctx: ControlContext) -> list[ResultatControle]:
    """B3 — Σ ``montant_facture_article`` contre ``montant_total_facture`` (même devise), ``T_SOMME``.

    Classement comme B2. Montant ``arithmetique_declaration`` en EUR : direct si la devise est l'euro,
    sinon converti au taux imprimé de la déclaration (``null`` si la conversion est impossible).
    """
    declarations = ctx.declarations()
    if not declarations:
        return [ctx.non_verifiable("B3", RaisonCode.document_manquant)]
    return [_b3_declaration(ctx, d) for d in declarations]


# =====================================================================================================
# B4 — Masses
# =====================================================================================================


def _kg(x: Decimal) -> str:
    """Masse lisible : au plus 3 décimales, zéros de fin retirés (``0,6`` et non ``0,6000``)."""
    d = x.quantize(Decimal("0.001")).normalize()
    return f"{format_nombre(d if d != 0 else Decimal(0))} kg"


def _b4_nette_brute(
    ctx: ControlContext, dec: Document, *, unite: str, sous_controle: str, nette: ValeurSourcee,
    brute: ValeurSourcee, v_nette: Decimal, v_brute: Decimal, sujet: str, operandes: Sequence[ValeurSourcee] = (),
) -> ResultatControle:
    tol = ctx.tol
    t = tol.t_masse(v_nette, v_brute)
    ecart = v_nette - v_brute
    entrees = {"masse_brute": brute, **({f"masse_nette_{k}": v for k, v in enumerate(operandes)} if operandes
                                       else {"masse_nette": nette})}
    commun = dict(
        unite=unite, sous_controle=sous_controle, entrees=entrees,
        attendu=v_brute, constate=v_nette, ecart=ecart, tolerance=t, seuil_certitude=t, documents=[dec.id],
        details={"declaration_id": dec.id},
    )
    if ecart <= t:
        return ctx.conforme("B4", **commun)
    confusions = [Confusion(brute, accepte=lambda v: v_nette - v <= t)]
    if operandes:
        for v_op in operandes:
            x = _num(v_op) or _ZERO
            confusions.append(Confusion(v_op, accepte=lambda v, x=x: v_nette - x + v - v_brute <= t))
    else:
        confusions.append(Confusion(nette, accepte=lambda v: v - v_brute <= t))
    classement = ctx.classify(
        "B4", ecart=ecart, tolerance=t, seuil_certitude=t, valeurs_cles=[nette, brute, *operandes],
        confusion=confusions,
    )
    libelle = (
        f"{sujet} de {_ref_declaration(dec, brute)}, la masse nette imprimée ({_kg(v_nette)}) est supérieure à "
        f"la masse brute imprimée ({_kg(v_brute)}) au-delà de la tolérance ({_kg(t)})."
    )
    preuves = [preuve(brute, RolePreuve.valeur_a)]
    preuves += [preuve(v, RolePreuve.operande) for v in operandes] or [preuve(nette, RolePreuve.valeur_b)]
    return ctx.constat("B4", classement, libelle=libelle, prochaine_action=ACTION_B, preuves=preuves, **commun)


def _b4_declaration(ctx: ControlContext, dec: Document) -> list[ResultatControle]:
    c = dec.dec
    out: list[ResultatControle] = []
    nettes: list[ValeurSourcee] = []
    brutes: list[ValeurSourcee] = []
    for i, a in enumerate(c.articles):
        num = a.numero_article.valeur if a.numero_article is not None and a.numero_article.valeur else str(i + 1)
        if a.masse_nette is not None:
            nettes.append(a.masse_nette)
        if a.masse_brute is not None:
            brutes.append(a.masse_brute)
        if a.masse_nette is None or a.masse_brute is None:
            continue
        unite = cle_unite(dec=dec.id, art=i)
        if not (ctx.utilisable(a.masse_nette) and ctx.utilisable(a.masse_brute)):
            v = a.masse_nette if not ctx.utilisable(a.masse_nette) else a.masse_brute
            out.append(ctx.non_verifiable("B4", ctx.raison_inutilisable(v), unite=unite, sous_controle="nette_brute",
                                          documents=[dec.id]))
            continue
        vn, vb = _num(a.masse_nette), _num(a.masse_brute)
        if vn is None or vb is None:
            out.append(ctx.non_verifiable("B4", RaisonCode.valeur_absente, unite=unite, sous_controle="nette_brute",
                                          documents=[dec.id]))
            continue
        out.append(_b4_nette_brute(ctx, dec, unite=unite, sous_controle="nette_brute", nette=a.masse_nette,
                                   brute=a.masse_brute, v_nette=vn, v_brute=vb, sujet=f"Sur l'article {num}"))

    total = c.masse_brute_totale
    n_art = len(c.articles)
    if total is None or not c.articles:
        return out
    if not ctx.utilisable(total) or _num(total) is None:
        for sc in ("nette_total", "somme_brute"):
            out.append(ctx.non_verifiable("B4", ctx.raison_inutilisable(total), unite=cle_unite(dec=dec.id),
                                          sous_controle=sc, documents=[dec.id]))
        return out
    v_total = _num(total) or _ZERO

    # (a) au total : Σ masses nettes des articles ≤ masse brute totale + T_MASSE.
    if len(nettes) == n_art:
        if all(ctx.utilisable(v) and _num(v) is not None for v in nettes):
            somme_n = sum((_num(v) or _ZERO for v in nettes), _ZERO)
            out.append(_b4_nette_brute(
                ctx, dec, unite=cle_unite(dec=dec.id), sous_controle="nette_total", nette=nettes[0], brute=total,
                v_nette=somme_n, v_brute=v_total, sujet="Au total", operandes=nettes,
            ))
        else:
            out.append(ctx.non_verifiable("B4", RaisonCode.confiance_insuffisante, unite=cle_unite(dec=dec.id),
                                          sous_controle="nette_total", documents=[dec.id]))

    # (b) Σ masses brutes des articles contre la masse brute totale : a_verifier uniquement.
    if len(brutes) == n_art:
        unite = cle_unite(dec=dec.id)
        if not all(ctx.utilisable(v) and _num(v) is not None for v in brutes):
            out.append(ctx.non_verifiable("B4", RaisonCode.confiance_insuffisante, unite=unite,
                                          sous_controle="somme_brute", documents=[dec.id]))
            return out
        somme_b = sum((_num(v) or _ZERO for v in brutes), _ZERO)
        t = ctx.tol.t_masse(v_total, somme_b)
        ecart = somme_b - v_total
        commun = dict(unite=unite, sous_controle="somme_brute", entrees={"masse_brute_totale": total},
                      attendu=v_total, constate=somme_b, ecart=ecart, tolerance=t, seuil_certitude=t,
                      documents=[dec.id], details={"declaration_id": dec.id})
        if abs(ecart) <= t:
            out.append(ctx.conforme("B4", **commun))
        else:
            classement = ctx.classify("B4", ecart=ecart, tolerance=t, seuil_certitude=t,
                                      valeurs_cles=[total, *brutes], eligible=False)
            libelle = (
                f"Sur {_ref_declaration(dec, total)}, la masse brute totale imprimée ({_kg(v_total)}) diffère de "
                f"la somme des masses brutes imprimées sur les {n_art} articles ({_kg(somme_b)})."
            )
            out.append(ctx.constat(
                "B4", classement, libelle=libelle, prochaine_action=ACTION_B,
                preuves=[preuve(total, RolePreuve.valeur_a), *(preuve(v, RolePreuve.operande) for v in brutes)],
                **commun,
            ))
    return out


@control("B4")
def b4_masses(ctx: ControlContext) -> list[ResultatControle]:
    """B4 — Masses (§11).

    (a) ``nette_brute`` (par article) et ``nette_total`` (Σ masses nettes des articles contre la masse brute
    totale) : ``masse_nette ≤ masse_brute + T_MASSE`` ; ``ecart_certain`` possible (seuil = tolérance) ;
    (b) ``somme_brute`` : Σ masses brutes des articles contre ``masse_brute_totale``, ``a_verifier`` seulement.
    Montant : aucun. Une sous-vérification sans données n'est pas exécutée.
    """
    declarations = ctx.declarations()
    if not declarations:
        return [ctx.non_verifiable("B4", RaisonCode.document_manquant)]
    out: list[ResultatControle] = []
    for dec in declarations:
        rs = _b4_declaration(ctx, dec)
        out.extend(rs or [ctx.non_applicable("B4", RaisonCode.valeur_absente, unite=cle_unite(dec=dec.id),
                                             documents=[dec.id], details={"motif": "aucune masse lue"})])
    return out


# =====================================================================================================
# B5 — Colis
# =====================================================================================================


def _b5_declaration(ctx: ControlContext, dec: Document) -> ResultatControle:
    c = dec.dec
    unite = cle_unite(dec=dec.id)
    colis = [a.nombre_colis for a in c.articles]
    presents = [v for v in colis if v is not None]
    total = c.nombre_colis_total
    if total is None or not presents:
        return ctx.non_applicable("B5", RaisonCode.valeur_absente, unite=unite, documents=[dec.id])
    if len(presents) != len(colis):
        return ctx.non_verifiable("B5", RaisonCode.valeur_absente, unite=unite, documents=[dec.id])
    for v in [total, *presents]:
        if not ctx.utilisable(v) or _num(v) is None:
            return ctx.non_verifiable(
                "B5", ctx.raison_inutilisable(v) if not ctx.utilisable(v) else RaisonCode.valeur_absente,
                unite=unite, documents=[dec.id],
            )
    v_total = _num(total) or _ZERO
    somme = sum((_num(v) or _ZERO for v in presents), _ZERO)
    ecart = somme - v_total
    t = ctx.tol.t_colis()
    commun = dict(unite=unite, entrees={"nombre_colis_total": total}, attendu=v_total, constate=somme, ecart=ecart,
                  tolerance=t, seuil_certitude=t, documents=[dec.id], details={"declaration_id": dec.id})
    if abs(ecart) <= t:
        return ctx.conforme("B5", **commun)
    classement: Classement = ctx.classify("B5", ecart=ecart, tolerance=t, seuil_certitude=t,
                                          valeurs_cles=[total, *presents])
    libelle = (
        f"Sur {_ref_declaration(dec, total)}, le nombre total de colis imprimé ({format_nombre(v_total)}) diffère "
        f"de la somme des nombres de colis imprimés sur les {len(presents)} articles ({format_nombre(somme)})."
    )
    return ctx.constat(
        "B5", classement, libelle=libelle, prochaine_action=ACTION_B,
        preuves=[preuve(total, RolePreuve.valeur_a), *(preuve(v, RolePreuve.operande) for v in presents)],
        **commun,
    )


@control("B5")
def b5_colis(ctx: ControlContext) -> list[ResultatControle]:
    """B5 — Σ ``nombre_colis`` des articles contre ``nombre_colis_total`` (exact), quand les deux existent.
    ``a_verifier`` uniquement ; montant : aucun."""
    declarations = ctx.declarations()
    if not declarations:
        return [ctx.non_verifiable("B5", RaisonCode.document_manquant)]
    return [_b5_declaration(ctx, d) for d in declarations]

