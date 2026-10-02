"""Famille G — Petits envois : droit forfaitaire par article (SPEC §16).

Le produit **ne décide pas** si le forfait s'applique ni ce qu'est un « article » au sens réglementaire :
il vérifie la cohérence des **nombres imprimés** (G1, G2), la refacturation (G4, G5) et signale par une
note de renvoi (G3, G6, ``PHRASE_RENVOI``, montant ``null``) ce qui relève d'une appréciation.

Unités : G1 ``cle_unite(dec=, tax=)`` ; G2, G3, G6 ``cle_unite(dec=)`` ; G4 ``cle_unite(ft=, dec=[…])``
(convention partagée avec C1–C5) ; G5 ``cle_unite(ft=, ligne=)``.
"""

from __future__ import annotations

import re
from decimal import Decimal

from controldone.controls import _aides_befg as aides
from controldone.controls._aides_befg import ZERO, num
from controldone.controls.framework import (
    Confusion,
    ControlContext,
    arrondi_centime,
    cle_unite,
    control,
    eur_par_devise,
    montant_arithmetique,
    montant_recouvrable,
    preuve,
)
from controldone.formatage import format_montant, format_nombre
from controldone.guardrails import PHRASE_RENVOI
from controldone.model import (
    CategorieTaxe,
    Composante,
    Document,
    NatureLigne,
    RaisonCode,
    ResultatControle,
    RolePreuve,
    TaxationDeclaration,
    ValeurSourcee,
)
from controldone.recouvrement.imputation import EcartImputable, imputer_avoirs, lignes_credit_depuis_avoir

__all__ = [
    "ACTION_G_CALCUL",
    "ACTION_G_REFACTURATION",
    "ACTION_G_RENVOI",
    "g1_nombre_articles_montant",
    "g2_base_nombre_articles",
    "g3_base_codes_distincts",
    "g4_forfait_refacture",
    "g5_base_refacturation",
    "g6_applicabilite",
]

#: Écart de calcul sur la déclaration (G1, G2) : même prochaine action que la famille B, avec renvoi.
ACTION_G_CALCUL = "Demander au déclarant l'explication de cet écart de calcul. " + PHRASE_RENVOI
#: Notes de renvoi (G3, G6).
ACTION_G_RENVOI = (
    "Faire examiner les valeurs lues par un professionnel avant toute démarche. " + PHRASE_RENVOI
)
#: Refacturation (G4, G5).
ACTION_G_REFACTURATION = (
    "Demander au transitaire le détail du forfait refacturé et, si l'écart est confirmé, un avoir."
)


def _forfaits(ctx: ControlContext, dec: Document) -> list[tuple[int, TaxationDeclaration]]:
    return aides.lignes_forfait(dec, ctx.parametres_petits_envois)


def _decs_avec_forfait(ctx: ControlContext) -> list[Document]:
    return [d for d in ctx.declarations() if _forfaits(ctx, d)]


def _sans_forfait(ctx: ControlContext, cid: str) -> list[ResultatControle]:
    """Aucune déclaration ou aucune ligne de forfait : le contrôle ne s'applique pas (ou non vérifiable)."""
    if not ctx.declarations():
        return [ctx.non_verifiable(cid, RaisonCode.document_manquant)]
    return [ctx.non_applicable(cid, RaisonCode.valeur_absente,
                               details={"motif": "aucune ligne de forfait petits envois sur la déclaration"})]


def _taux(t: TaxationDeclaration) -> ValeurSourcee | None:
    return t.taux


# =====================================================================================================
# G1 — Nombre d'articles × montant unitaire = montant du forfait
# =====================================================================================================


def _g1_ligne(ctx: ControlContext, dec: Document, i: int, t: TaxationDeclaration) -> ResultatControle:
    unite = cle_unite(dec=dec.id, tax=i)
    requis = {"base_quantite": t.base_quantite, "taux": t.taux, "montant": t.montant}
    details = {"declaration_id": dec.id, "taxation": i}
    for v in requis.values():
        if not aides.utilisable_num(ctx, v):
            raison = ctx.raison_inutilisable(v) if not ctx.utilisable(v) else RaisonCode.valeur_absente
            return ctx.non_verifiable("G1", raison, unite=unite, documents=[dec.id], details=details)
    assert t.base_quantite is not None and t.taux is not None and t.montant is not None
    base, taux, montant = num(t.base_quantite) or ZERO, num(t.taux) or ZERO, num(t.montant) or ZERO
    calcul = base * taux
    tol = ctx.tol
    t_g1 = tol.t_ligne()
    ecart = montant - calcul
    commun = dict(
        unite=unite, entrees=requis, attendu=arrondi_centime(calcul), constate=montant,
        ecart=montant_arithmetique(montant, calcul), tolerance=t_g1, seuil_certitude=tol.s_calcul_declaration(),
        documents=[dec.id], details=details,
    )
    if abs(ecart) <= t_g1:
        return ctx.conforme("G1", **commun)
    classement = ctx.classify(
        "G1", ecart=ecart, tolerance=t_g1, seuil_certitude=tol.s_calcul_declaration(),
        valeurs_cles=[t.base_quantite, t.taux, t.montant],
        confusion=[
            Confusion(t.montant, accepte=lambda v: abs(v - calcul) <= t_g1),
            Confusion(t.base_quantite, accepte=lambda v: abs(montant - v * taux) <= t_g1),
            Confusion(t.taux, accepte=lambda v: abs(montant - base * v) <= t_g1),
        ],
    )
    calcul_txt = f"{format_nombre(base)} × {format_montant(taux, 'EUR')} = {format_montant(arrondi_centime(calcul), 'EUR')}"
    code = aides.texte(t.type_taxe) or "forfait"
    libelle = (
        f"Sur {aides.ref_document(dec, t.montant)}, le montant imprimé de la ligne de forfait petits envois "
        f"{code} ({format_montant(montant, 'EUR')}) diffère du produit du nombre d'articles imprimé par le "
        f"montant unitaire imprimé ({calcul_txt})."
    )
    return ctx.constat(
        "G1", classement, libelle=libelle, prochaine_action=ACTION_G_CALCUL,
        montant=montant_arithmetique(montant, calcul), composante=Composante.forfait_petits_envois,
        preuves=[preuve(t.base_quantite, RolePreuve.operande), preuve(t.taux, RolePreuve.operande),
                 preuve(t.montant, RolePreuve.valeur_b), preuve(None, RolePreuve.valeur_a, calcul=calcul_txt)],
        **commun,
    )


@control("G1")
def g1_nombre_articles_montant(ctx: ControlContext) -> list[ResultatControle]:
    """G1 — ``base_quantite × taux imprimé`` contre le montant imprimé de chaque ligne de forfait,
    tolérance 0,01 EUR ; ``ecart_certain`` si ``|écart| > 1,00 EUR`` et règle générale. Le taux de
    référence configuré n'est jamais utilisé pour le calcul (taux absent -> ``non_verifiable``)."""
    decs = _decs_avec_forfait(ctx)
    if not decs:
        return _sans_forfait(ctx, "G1")
    return [_g1_ligne(ctx, d, i, t) for d in decs for i, t in _forfaits(ctx, d)]


# =====================================================================================================
# G2 — Base du forfait contre nombre d'articles de la déclaration
# =====================================================================================================


def _base_declaree(ctx: ControlContext, dec: Document) -> tuple[Decimal, list[ValeurSourcee]] | None:
    """Σ ``base_quantite`` des lignes de forfait de la déclaration ; ``None`` si une base est inexploitable."""
    total, vals = ZERO, []
    for _, t in _forfaits(ctx, dec):
        if not aides.utilisable_num(ctx, t.base_quantite):
            return None
        assert t.base_quantite is not None
        total += num(t.base_quantite) or ZERO
        vals.append(t.base_quantite)
    return total, vals


def _g2_declaration(ctx: ControlContext, dec: Document) -> ResultatControle:
    unite = cle_unite(dec=dec.id)
    c = dec.dec
    details: dict = {"declaration_id": dec.id}
    base = _base_declaree(ctx, dec)
    if base is None:
        return ctx.non_verifiable("G2", RaisonCode.valeur_absente, unite=unite, documents=[dec.id], details=details)
    v_base, bases = base
    raisons: list[RaisonCode] = []
    if ctx.utilisable(c.nombre_articles) and aides.entier(c.nombre_articles) is not None:
        n = Decimal(aides.entier(c.nombre_articles) or 0)
        v_n: ValeurSourcee | None = c.nombre_articles
        source = "nombre_articles"
    elif c.articles:
        # Nombre de blocs articles lus : une valeur dérivée, jamais suffisante pour un écart certain.
        n, v_n, source = Decimal(len(c.articles)), None, "blocs_articles"
        raisons.append(RaisonCode.valeur_absente)
    else:
        return ctx.non_verifiable("G2", RaisonCode.valeur_absente, unite=unite, documents=[dec.id], details=details)
    ecart = v_base - n
    forfaits = _forfaits(ctx, dec)
    taux_vals = [t.taux for _, t in forfaits]
    taux_unique = {num(v) for v in taux_vals if aides.utilisable_num(ctx, v)}
    taux = taux_unique.pop() if len(taux_unique) == 1 and all(aides.utilisable_num(ctx, v) for v in taux_vals) else None
    montant = arrondi_centime(ecart * taux) if taux is not None else None
    commun = dict(
        unite=unite, entrees={"base_quantite": bases[0], **({"nombre_articles": v_n} if v_n else {})},
        attendu=n, constate=v_base, ecart=ecart, tolerance=ZERO, seuil_certitude=ZERO, documents=[dec.id],
        details={**details, "source_nombre_articles": source},
    )
    if ecart == 0:
        return ctx.conforme("G2", **commun)
    cles = [*bases, *([v_n] if v_n is not None else [])]
    classement = ctx.classify(
        "G2", ecart=ecart, tolerance=ZERO, seuil_certitude=ZERO, valeurs_cles=cles,
        confusion=[Confusion(b, accepte=lambda v, b=b: v_base - (num(b) or ZERO) + v == n) for b in bases]
        + ([Confusion(v_n, accepte=lambda v: v == v_base)] if v_n is not None else []),
        raisons_supplementaires=raisons,
    )
    ref_n = (f"le nombre d'articles imprimé ({format_nombre(n)})" if v_n is not None
             else f"le nombre de blocs articles lus ({format_nombre(n)})")
    libelle = (
        f"Sur {aides.ref_document(dec, bases[0])}, la base imprimée de la ligne de forfait petits envois "
        f"({format_nombre(v_base)} articles) diffère de {ref_n}."
    )
    if montant is not None:
        libelle += (
            f" Au montant unitaire imprimé ({format_montant(taux, 'EUR')}), la différence représente "
            f"{format_montant(montant, 'EUR')}."
        )
    preuves = [preuve(b, RolePreuve.valeur_b) for b in bases]
    preuves.append(preuve(v_n, RolePreuve.valeur_a) if v_n is not None
                   else preuve(None, RolePreuve.valeur_a, calcul=f"{len(c.articles)} blocs articles lus"))
    return ctx.constat(
        "G2", classement, libelle=libelle, prochaine_action=ACTION_G_CALCUL, montant=montant,
        composante=Composante.forfait_petits_envois, preuves=preuves, **commun,
    )


@control("G2")
def g2_base_nombre_articles(ctx: ControlContext) -> list[ResultatControle]:
    """G2 — Base du forfait (Σ ``base_quantite`` des lignes de forfait) contre ``nombre_articles`` imprimé
    (à défaut, nombre de blocs articles lus, jamais certain). Exact. Montant ``arithmetique_declaration`` =
    ``(base − nombre_articles) × taux imprimé`` (``null`` sans taux imprimé unique)."""
    decs = _decs_avec_forfait(ctx)
    if not decs:
        return _sans_forfait(ctx, "G2")
    return [_g2_declaration(ctx, d) for d in decs]


# =====================================================================================================
# G3 — Base du forfait contre codes marchandise distincts (signal + renvoi)
# =====================================================================================================


def _g3_declaration(ctx: ControlContext, dec: Document) -> ResultatControle:
    unite = cle_unite(dec=dec.id)
    c = dec.dec
    details: dict = {"declaration_id": dec.id}
    base = _base_declaree(ctx, dec)
    if base is None:
        return ctx.non_verifiable("G3", RaisonCode.valeur_absente, unite=unite, documents=[dec.id], details=details)
    v_base, bases = base
    codes = [a.code_marchandise for a in c.articles]
    if not codes or any(not ctx.utilisable(v) for v in codes):
        return ctx.non_verifiable("G3", RaisonCode.valeur_absente, unite=unite, documents=[dec.id], details=details)
    chiffres = [re.sub(r"\D", "", v.valeur or "") for v in codes if v is not None]
    if any(len(x) < 6 for x in chiffres):
        return ctx.non_verifiable("G3", RaisonCode.valeur_absente, unite=unite, documents=[dec.id], details=details)
    n_complet = len(set(chiffres))
    n_sh6 = len({x[:6] for x in chiffres})
    commun = dict(
        unite=unite, entrees={"base_quantite": bases[0]}, attendu=f"{n_complet}|{n_sh6}", constate=v_base,
        documents=[dec.id], details={**details, "codes_distincts": n_complet, "codes_distincts_6": n_sh6},
    )
    if v_base in (Decimal(n_complet), Decimal(n_sh6)):
        return ctx.conforme("G3", **commun)
    classement = ctx.classify("G3", ecart=None, tolerance=None, seuil_certitude=None,
                              valeurs_cles=[*bases, *(v for v in codes if v is not None)], renvoi=True)
    libelle = (
        f"Sur {aides.ref_document(dec, bases[0])}, la base imprimée de la ligne de forfait petits envois "
        f"({format_nombre(v_base)}) diffère du nombre de codes marchandise distincts imprimés sur les articles "
        f"({n_complet} en code complet, {n_sh6} à 6 chiffres)."
    )
    return ctx.constat(
        "G3", classement, libelle=libelle, prochaine_action=ACTION_G_RENVOI, renvoi=True,
        composante=Composante.forfait_petits_envois,
        preuves=[*(preuve(b, RolePreuve.valeur_b) for b in bases),
                 *(preuve(v, RolePreuve.contexte) for v in codes if v is not None)],
        **commun,
    )


@control("G3")
def g3_base_codes_distincts(ctx: ControlContext) -> list[ResultatControle]:
    """G3 — Base du forfait contre le nombre de codes marchandise distincts (code complet, puis 6 chiffres).
    Constat si la base diffère des deux comptages : note de renvoi (``a_verifier``, montant ``null``)."""
    decs = _decs_avec_forfait(ctx)
    if not decs:
        return _sans_forfait(ctx, "G3")
    return [_g3_declaration(ctx, d) for d in decs]


# =====================================================================================================
# G4 — Forfait refacturé contre forfait liquidé
# =====================================================================================================


def _a_droits_hors_forfait(ctx: ControlContext, decs: list[Document]) -> bool:
    for d in decs:
        for t in d.dec.taxations:
            if t.categorie is CategorieTaxe.droit and not aides.est_forfait(t, ctx.parametres_petits_envois):
                v = num(aides.montant_liquide(t))
                if v is None or v != 0:
                    return True
    return False


def _lignes_g4(ctx: ControlContext, ft: Document, groupe: aides.GroupeDebours, decs: list[Document]) -> tuple[
    list[int], NatureLigne
]:
    """Lignes de forfait refacturées du groupe ; à défaut, lignes de droits si la déclaration ne porte
    que ce droit (§16 G4)."""
    lignes = [i for i in groupe.lignes if ft.ft.lignes[i].nature is NatureLigne.debours_forfait_petits_envois]
    if lignes:
        return lignes, NatureLigne.debours_forfait_petits_envois
    if not _a_droits_hors_forfait(ctx, decs):
        droits = [i for i in groupe.lignes if ft.ft.lignes[i].nature is NatureLigne.debours_droits]
        if droits:
            return droits, NatureLigne.debours_droits
    return [], NatureLigne.debours_forfait_petits_envois


def _credit_impute(
    ctx: ControlContext, ft: Document, unite: str, decs: list[Document], brut: Decimal
) -> Decimal:
    """Avoirs du dossier déjà imputés (§17.2) sur l'écart brut de forfait de cette unité."""
    avoirs = aides.avoirs_imputables(ctx)
    if not avoirs or brut <= 0:
        return ZERO
    emetteur = aides.emetteur_de(ctx, ft)
    ecart = EcartImputable(
        id=unite, composante=Composante.forfait_petits_envois, reste=arrondi_centime(brut), emetteur=emetteur,
        facture_ref=aides.texte(ft.ft.numero),
        mrn=aides.texte(decs[0].dec.mrn) if len(decs) == 1 else None,
    )
    lignes = [lc for a in avoirs for lc in lignes_credit_depuis_avoir(a, emetteur=aides.emetteur_de(ctx, a))]
    nb = sum(aides.nb_articles(d) for d in decs)
    return imputer_avoirs(lignes, [ecart], t_debours=ctx.tol.t_debours(nb)).credit_pour(unite)


def _g4_unite(ctx: ControlContext, ft: Document, groupe: aides.GroupeDebours,
              decs: list[Document]) -> ResultatControle | None:
    unite = cle_unite(ft=ft.id, dec=[d.id for d in decs])
    doc_ids = [ft.id, *(d.id for d in decs)]
    details: dict = {"facture_transitaire_id": ft.id, "declarations": [d.id for d in decs]}
    taxes = [t for d in decs for _, t in _forfaits(ctx, d)]
    if not taxes:
        return None
    liq = aides.liquide(ctx, taxes)
    if liq is None:
        return ctx.non_verifiable("G4", RaisonCode.valeur_absente, unite=unite, documents=doc_ids, details=details)
    v_liq, vals_liq = liq
    lignes, nature = _lignes_g4(ctx, ft, groupe, decs)
    vals_ref = [aides.montant_ht(ft.ft.lignes[i]) for i in lignes]
    if any(not aides.utilisable_num(ctx, v) for v in vals_ref):
        return ctx.non_verifiable("G4", RaisonCode.valeur_absente, unite=unite, documents=doc_ids, details=details)
    refacture = sum((num(v) or ZERO for v in vals_ref), ZERO)
    brut = refacture - v_liq
    nb = sum(aides.nb_articles(d) for d in decs)
    tol = ctx.tol
    t_deb, s_deb = tol.t_debours(nb), tol.s_debours(nb)
    credit = _credit_impute(ctx, ft, unite, decs, brut)
    net = brut - credit
    details |= {"nature_refacturee": nature.value, "credit_impute": str(credit), "lignes": lignes}
    commun = dict(
        unite=unite, entrees={f"refacture_{k}": v for k, v in enumerate(vals_ref) if v is not None},
        attendu=arrondi_centime(v_liq), constate=arrondi_centime(refacture), ecart=arrondi_centime(net),
        tolerance=t_deb, seuil_certitude=s_deb, documents=doc_ids, details=details,
    )
    if abs(net) <= t_deb:
        return ctx.conforme("G4", **commun)
    valeurs_cles = [*(v for v in vals_ref if v is not None), *vals_liq]
    classement = ctx.classify(
        "G4", ecart=net, tolerance=t_deb, seuil_certitude=s_deb, valeurs_cles=valeurs_cles, montant=net,
        confusion=[Confusion(v, autre=num(v) - net, tolerance=t_deb) for v in vals_ref if v is not None],
    )
    mrns = ", ".join(aides.texte(d.dec.mrn) or "?" for d in decs)
    libelle = (
        f"{aides.maj(aides.ref_document(ft, vals_ref[0] if vals_ref else None))} refacture "
        f"{format_montant(arrondi_centime(refacture), 'EUR')} au titre du forfait petits envois ; le montant "
        f"liquidé indiqué sur la déclaration (MRN {mrns}) pour ce forfait est de "
        f"{format_montant(arrondi_centime(v_liq), 'EUR')}."
    )
    if credit > 0:
        libelle += f" Un avoir de {format_montant(credit, 'EUR')} déjà reçu est déduit de l'écart."
    return ctx.constat(
        "G4", classement, libelle=libelle, prochaine_action=ACTION_G_REFACTURATION,
        montant=montant_recouvrable(refacture - credit, v_liq), montant_brut=montant_recouvrable(refacture, v_liq),
        composante=Composante.forfait_petits_envois,
        preuves=[*(preuve(v, RolePreuve.valeur_b) for v in vals_ref),
                 *(preuve(v, RolePreuve.valeur_a) for v in vals_liq)],
        **commun,
    )


@control("G4")
def g4_forfait_refacture(ctx: ControlContext) -> list[ResultatControle]:
    """G4 — Comme C1 pour la catégorie ``forfait_petits_envois`` (§16) : Σ lignes
    ``debours_forfait_petits_envois`` de la facture transitaire (à défaut, lignes de droits si la
    déclaration ne porte que ce droit) contre Σ des montants liquidés des lignes de forfait, ``T_DEBOURS`` /
    ``S_DEBOURS``, net des avoirs imputés (§17.2). Montant ``recouvrable``."""
    decs = _decs_avec_forfait(ctx)
    if not decs:
        return _sans_forfait(ctx, "G4")
    fts = ctx.factures_transitaires()
    if not fts:
        return [ctx.non_applicable("G4", RaisonCode.facture_transitaire_absente)]
    par_prefixe = {d.dec.mrn_prefixe: d for d in ctx.declarations() if d.dec.mrn_prefixe}
    out: list[ResultatControle] = []
    for ft in fts:
        for g in aides.ventiler_debours(ft, list(par_prefixe)):
            concernees = [par_prefixe[p] for p in g.prefixes if p in par_prefixe and par_prefixe[p] in decs]
            if not concernees:
                continue
            r = _g4_unite(ctx, ft, g, concernees)
            if r is not None:
                out.append(r)
    return out or [ctx.non_applicable("G4", RaisonCode.valeur_absente,
                                      details={"motif": "aucun débours rattaché à une déclaration avec forfait"})]


# =====================================================================================================
# G5 — Base de refacturation du transitaire
# =====================================================================================================


def _g5_ligne(ctx: ControlContext, ft: Document, i: int, decs: list[Document]) -> ResultatControle:
    ln = ft.ft.lignes[i]
    unite = cle_unite(ft=ft.id, ligne=i)
    doc_ids = [ft.id, *(d.id for d in decs)]
    details: dict = {"facture_transitaire_id": ft.id, "ligne": i, "declarations": [d.id for d in decs]}
    bases = [_base_declaree(ctx, d) for d in decs]
    for v in (ln.quantite, ln.prix_unitaire):
        if not aides.utilisable_num(ctx, v):
            return ctx.non_verifiable("G5", RaisonCode.valeur_absente, unite=unite, documents=doc_ids, details=details)
    if any(b is None for b in bases):
        return ctx.non_verifiable("G5", RaisonCode.valeur_absente, unite=unite, documents=doc_ids, details=details)
    assert ln.quantite is not None and ln.prix_unitaire is not None
    n_tr, pu = num(ln.quantite) or ZERO, num(ln.prix_unitaire) or ZERO
    base_dec = sum((b[0] for b in bases if b is not None), ZERO)
    vals_base = [v for b in bases if b is not None for v in b[1]]
    ecart = (n_tr - base_dec) * pu
    tol = ctx.tol
    s_deb = tol.s_debours()
    commun = dict(
        unite=unite, entrees={"quantite": ln.quantite, "prix_unitaire": ln.prix_unitaire},
        attendu=base_dec, constate=n_tr, ecart=arrondi_centime(ecart), tolerance=ZERO, seuil_certitude=s_deb,
        documents=doc_ids, details=details,
    )
    if n_tr == base_dec:
        return ctx.conforme("G5", **commun)
    classement = ctx.classify(
        "G5", ecart=ecart, tolerance=ZERO, seuil_certitude=s_deb,
        valeurs_cles=[ln.quantite, *vals_base], montant=ecart,
        confusion=[Confusion(ln.quantite, accepte=lambda v: v == base_dec)],
    )
    libelle = (
        f"{aides.maj(aides.ref_document(ft, ln.quantite))} refacture le forfait petits envois sur une base de "
        f"{format_nombre(n_tr)} × {format_montant(pu, 'EUR')} ; la base imprimée sur la ligne de forfait de la "
        f"déclaration est de {format_nombre(base_dec)} articles, soit une différence de "
        f"{format_montant(arrondi_centime(ecart), 'EUR')}."
    )
    return ctx.constat(
        "G5", classement, libelle=libelle, prochaine_action=ACTION_G_REFACTURATION, montant=ecart,
        composante=Composante.forfait_petits_envois,
        preuves=[preuve(ln.quantite, RolePreuve.valeur_b), preuve(ln.prix_unitaire, RolePreuve.operande),
                 *(preuve(v, RolePreuve.valeur_a) for v in vals_base)],
        **commun,
    )


@control("G5")
def g5_base_refacturation(ctx: ControlContext) -> list[ResultatControle]:
    """G5 — Si une ligne de forfait refacturé imprime une base (quantité × prix unitaire),
    ``écart = (n_transitaire − base_quantite_declaree) × montant unitaire refacturé``. ``ecart_certain`` si
    les deux nombres sont lus ≥ 0,90 et ``écart > S_DEBOURS``. Le moteur retire le montant si G4 constate
    le même excédent (``doublon_composantes``)."""
    decs = _decs_avec_forfait(ctx)
    if not decs:
        return _sans_forfait(ctx, "G5")
    fts = ctx.factures_transitaires()
    if not fts:
        return [ctx.non_applicable("G5", RaisonCode.facture_transitaire_absente)]
    par_prefixe = {d.dec.mrn_prefixe: d for d in ctx.declarations() if d.dec.mrn_prefixe}
    out: list[ResultatControle] = []
    for ft in fts:
        for g in aides.ventiler_debours(ft, list(par_prefixe), [NatureLigne.debours_forfait_petits_envois]):
            concernees = [par_prefixe[p] for p in g.prefixes if p in par_prefixe and par_prefixe[p] in decs]
            if not concernees:
                continue
            for i in g.lignes:
                if ft.ft.lignes[i].quantite is None:
                    continue  # aucune base imprimée sur la ligne : G5 ne s'applique pas
                out.append(_g5_ligne(ctx, ft, i, concernees))
    return out or [ctx.non_applicable("G5", RaisonCode.valeur_absente,
                                      details={"motif": "aucune base imprimée sur une ligne de forfait refacturé"})]


# =====================================================================================================
# G6 — Applicabilité (renvoi seulement)
# =====================================================================================================


def _g6_declaration(ctx: ControlContext, dec: Document) -> ResultatControle:
    p = ctx.parametres_petits_envois
    c = dec.dec
    unite = cle_unite(dec=dec.id)
    details: dict = {"declaration_id": dec.id, "date_debut": p.date_debut.isoformat(),
                     "date_fin": p.date_fin.isoformat(), "seuil_eur": str(p.seuil_valeur_eur)}
    signaux: list[str] = []
    preuves = []
    inconnu = False
    # Date d'acceptation contre la période configurée.
    d = aides.date_de(c.date_acceptation) if ctx.utilisable(c.date_acceptation) else None
    if d is None:
        inconnu = True
    elif d < p.date_debut or d > p.date_fin:
        signaux.append(
            f"la date d'acceptation imprimée ({d.strftime('%d/%m/%Y')}) est hors de la période configurée "
            f"pour le forfait ({p.date_debut.strftime('%d/%m/%Y')} au {p.date_fin.strftime('%d/%m/%Y')})"
        )
        preuves.append(preuve(c.date_acceptation, RolePreuve.valeur_b))
    # Montant facturé total de l'envoi, converti au taux imprimé de la déclaration (§8.7).
    montant = num(c.montant_total_facture) if ctx.utilisable(c.montant_total_facture) else None
    devise = (aides.texte(c.devise_facture) or "").upper() or None
    valeur_eur: Decimal | None = None
    if montant is not None and devise == "EUR":
        valeur_eur = montant
    elif montant is not None and devise:
        taux = num(c.taux_change) if ctx.utilisable(c.taux_change) else None
        sens = aides.texte(c.taux_change_sens)
        if taux and sens in ("eur_par_devise", "devise_par_eur"):
            valeur_eur = montant * eur_par_devise(taux, sens)
    if valeur_eur is None:
        inconnu = True
    elif valeur_eur > p.seuil_valeur_eur:
        conv = "" if devise == "EUR" else f", soit {format_montant(arrondi_centime(valeur_eur), 'EUR')} au taux imprimé"
        signaux.append(
            f"le montant total facturé imprimé ({format_montant(montant or ZERO, devise)}{conv}) dépasse le seuil "
            f"configuré de {format_montant(p.seuil_valeur_eur, 'EUR')}"
        )
        preuves.append(preuve(c.montant_total_facture, RolePreuve.valeur_b))
        if devise != "EUR":
            preuves.append(preuve(c.taux_change, RolePreuve.operande))
    commun = dict(unite=unite, documents=[dec.id], details={**details, "signaux": len(signaux)})
    if not signaux:
        if inconnu:
            return ctx.non_verifiable("G6", RaisonCode.valeur_absente, **commun)
        return ctx.conforme("G6", **commun)
    forfait = _forfaits(ctx, dec)[0][1]
    preuves.insert(0, preuve(forfait.montant or forfait.type_taxe, RolePreuve.contexte))
    classement = ctx.classify("G6", ecart=None, tolerance=None, seuil_certitude=None, valeurs_cles=[], renvoi=True)
    libelle = (
        f"{aides.maj(aides.ref_document(dec))} porte une ligne de forfait petits envois et "
        + " ; ".join(signaux) + "."
    )
    return ctx.constat("G6", classement, libelle=libelle, prochaine_action=ACTION_G_RENVOI, renvoi=True,
                       composante=Composante.forfait_petits_envois, preuves=preuves, **commun)


@control("G6")
def g6_applicabilite(ctx: ControlContext) -> list[ResultatControle]:
    """G6 — Ligne de forfait sur une déclaration acceptée hors de la période configurée, ou dont le montant
    facturé total converti au taux imprimé dépasse le seuil configuré. Note de renvoi : le texte constate
    les valeurs lues, il ne dit jamais si le forfait était applicable."""
    decs = _decs_avec_forfait(ctx)
    if not decs:
        return _sans_forfait(ctx, "G6")
    return [_g6_declaration(ctx, d) for d in decs]
