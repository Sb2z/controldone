"""Famille D — Facture du transitaire contre grille tarifaire ou devis (SPEC §13).

- D1 (arithmétique interne) s'exécute toujours, avec ou sans grille.
- D2 à D9 exigent une grille **validée**, valide à la date de la facture, pour le transitaire émetteur
  (``grille_pour_facture``) ; sinon ``non_applicable`` (raison ``aucune_grille_validee``) par facture.
- Rapprochement ligne ↔ poste : par ``nature`` puis par libellé normalisé (``libelles_reconnus``) ; une
  ligne qui correspond à plusieurs postes est ``a_verifier`` (raison ``confiance_insuffisante``).
- Aiguillage d'une ligne de prestation rapprochée : FAF -> D4, magasinage -> D6, surcharge -> D7, ligne
  supplémentaire par article -> D9, autres -> D3. Ligne sans poste : D2 (D7 pour une surcharge).

Le tarif est contractuel : la référence ``a`` est le prix de la grille, la valeur comparée ``b`` le montant
facturé ; ``écart = b − a``. Libellés comparatifs, jamais d'accusation du transitaire (§3.1 règle 3).
Unités : ``cle_unite(ft=<facture>, ligne=<index>)`` par ligne, ``cle_unite(ft=<facture>)`` par facture.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from controldone.controls.famille_c import (
    assiette_debours,
    borner,
    excedent_debours,
    grille_pour_facture,
    libelle_facture,
    page_txt,
    reference_declaration,
    unites_c,
    unites_pour_facture,
)
from controldone.controls.framework import (
    Confusion,
    ControlContext,
    arrondi_centime,
    cle_unite,
    control,
    preuve,
)
from controldone.formatage import format_montant, format_nombre, format_pourcentage
from controldone.model import (
    BasePourcentage,
    Composante,
    Document,
    GrilleTarifaire,
    LigneFactureTransitaire,
    ModePoste,
    NatureLigne,
    PosteGrille,
    PrestationsHorsGrille,
    RaisonCode,
    ResultatControle,
    RolePreuve,
    ValeurSourcee,
)
from controldone.normalize.refs import mrn_prefixe, norm_ref, norm_ref_transport
from controldone.normalize.text import cle_texte

__all__ = [
    "ACTION_D",
    "ACTION_D8",
    "LigneRoutee",
    "d1_arithmetique",
    "d2_hors_grille",
    "d3_prix_grille",
    "d4_faf_grille",
    "d5_ligne_double",
    "d6_magasinage",
    "d7_surcharges",
    "d8_tva_debours",
    "d9_lignes_supplementaires",
    "lignes_routees",
    "rapprocher_poste",
]

ZERO = Decimal(0)
_CENT = Decimal(100)

ACTION_D = (
    "Vérifier la ligne sur la facture et la grille tarifaire citées puis, si l'écart se confirme, demander au "
    "transitaire un avoir de la différence avec le tarif convenu, en joignant la grille."
)
ACTION_D_TOLEREE = (
    "Vérifier avec le transitaire si cette prestation était prévue pour cet envoi ; la grille tarifaire admet "
    "des prestations hors grille."
)
ACTION_D1 = (
    "Vérifier l'addition sur la facture citée puis, si l'écart se confirme, demander au transitaire une facture "
    "corrigée ou un avoir de la différence."
)
ACTION_D5 = (
    "Vérifier si la prestation a été rendue deux fois ; sinon, demander au transitaire un avoir de la ligne "
    "répétée."
)
ACTION_D8 = (
    "Faire confirmer le traitement de TVA de cette ligne de débours par votre expert-comptable avant toute "
    "démarche auprès du transitaire."
)
ACTION_D_AMBIGU = (
    "Préciser à quel poste de la grille tarifaire cette ligne correspond, puis relancer le contrôle."
)

#: Natures traitées par D3 lorsqu'elles sont rapprochées d'un poste.
_ROUTE_SPECIALE = {
    NatureLigne.frais_avance_fonds: "D4",
    NatureLigne.magasinage: "D6",
    NatureLigne.surcharge: "D7",
}


# =====================================================================================================
# Outils
# =====================================================================================================


def _dec(ctx: ControlContext, v: ValeurSourcee | None) -> Decimal | None:
    if not ctx.utilisable(v):
        return None
    assert v is not None
    try:
        return v.decimal_signe()
    except ValueError:
        return None


def _somme(xs: Iterable[Decimal]) -> Decimal:
    return sum(xs, ZERO)


def _par(*m: str) -> str:
    x = [s for s in m if s]
    return f" ({', '.join(x)})" if x else ""


def _libelle_ligne(ligne: LigneFactureTransitaire) -> str:
    v = ligne.libelle
    return f"« {v.valeur_brute or v.valeur} »" if v is not None and v.valeur else "sans libellé lu"


def _la_facture(f: Document) -> str:
    """« la facture du transitaire n° F-1 »."""
    return libelle_facture([f]).replace("La facture", "la facture", 1)


def _ref_grille(g: GrilleTarifaire) -> str:
    return f"la grille tarifaire validée {g.reference}"


def _cle(texte: str | None) -> str:
    return cle_texte(texte or "")


def _libelle_correspond(libelle: str, reconnu: str) -> bool:
    """Libellé de ligne normalisé égal à un libellé reconnu, ou l'un contenu dans l'autre (mots entiers,
    au moins 4 caractères pour le plus court)."""
    a, b = _cle(libelle), _cle(reconnu)
    if not a or not b:
        return False
    if a == b:
        return True
    court, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return len(court) >= 4 and f" {court} " in f" {long_} "


def rapprocher_poste(grille: GrilleTarifaire, ligne: LigneFactureTransitaire) -> tuple[PosteGrille | None, bool]:
    """(poste, ambigu) : par ``nature`` puis libellé (§13). Plusieurs postes possibles -> ambigu."""
    libelle = ligne.libelle.valeur if ligne.libelle is not None and ligne.libelle.valeur else ""

    def par_libelle(postes: Sequence[PosteGrille]) -> list[PosteGrille]:
        return [p for p in postes if any(_libelle_correspond(libelle, r) for r in p.libelles_reconnus)]

    candidats = [p for p in grille.postes if p.nature is ligne.nature]
    if len(candidats) == 1:
        return candidats[0], False
    if len(candidats) > 1:
        m = par_libelle(candidats)
        return (m[0], False) if len(m) == 1 else (None, True)
    m = par_libelle(grille.postes) if libelle else []
    if len(m) == 1:
        return m[0], False
    return None, len(m) > 1


@dataclass
class LigneRoutee:
    facture: Document
    grille: GrilleTarifaire
    index: int
    ligne: LigneFactureTransitaire
    poste: PosteGrille | None
    ambigu: bool
    controle: str

    @property
    def unite(self) -> str:
        return cle_unite(ft=self.facture.id, ligne=self.index)


def _route(ligne: LigneFactureTransitaire, poste: PosteGrille | None, ambigu: bool) -> str:
    nature = poste.nature if poste is not None else ligne.nature
    if poste is None and not ambigu:
        return "D7" if nature is NatureLigne.surcharge else "D2"
    if nature in _ROUTE_SPECIALE:
        return _ROUTE_SPECIALE[nature]
    if nature is NatureLigne.frais_ligne_supplementaire and (
        ambigu or (poste is not None and poste.mode is ModePoste.unitaire and poste.unite_base in (None, "article"))
    ):
        return "D9"
    return "D3"


def lignes_routees(ctx: ControlContext) -> tuple[list[LigneRoutee], list[Document]]:
    """Lignes de prestation des factures qui ont une grille applicable, et factures sans grille."""
    out: list[LigneRoutee] = []
    sans_grille: list[Document] = []
    for f in ctx.factures_transitaires():
        g = grille_pour_facture(ctx, f)
        if g is None:
            sans_grille.append(f)
            continue
        for i, lg in enumerate(f.ft.lignes):
            if lg.nature.est_debours:
                continue
            poste, ambigu = rapprocher_poste(g, lg)
            out.append(LigneRoutee(f, g, i, lg, poste, ambigu, _route(lg, poste, ambigu)))
    return out, sans_grille


def _prealable(ctx: ControlContext, cid: str) -> tuple[list[LigneRoutee], list[ResultatControle]] | list[
    ResultatControle
]:
    if not ctx.factures_transitaires():
        return [ctx.non_applicable(cid, RaisonCode.facture_transitaire_absente)]
    lignes, sans = lignes_routees(ctx)
    na = [
        ctx.non_applicable(cid, RaisonCode.aucune_grille_validee, unite=cle_unite(ft=f.id), documents=[f.id],
                           details={"motif": "aucune grille tarifaire validée pour ce transitaire"})
        for f in sans
    ]
    return lignes, na


def _montant(ctx: ControlContext, lg: LigneFactureTransitaire) -> ValeurSourcee | None:
    return lg.montant_ht if lg.montant_ht is not None else lg.montant_ttc


def _ambigu(ctx: ControlContext, cid: str, lr: LigneRoutee) -> ResultatControle:
    v = _montant(ctx, lr.ligne)
    cles = [x for x in (lr.ligne.libelle, v) if x is not None]
    classement = ctx.classify(cid, ecart=None, tolerance=None, seuil_certitude=None, valeurs_cles=cles,
                              documents=[lr.facture.id], raisons_supplementaires=[RaisonCode.confiance_insuffisante])
    libelle = (
        f"La ligne {_libelle_ligne(lr.ligne)} de la facture du transitaire{_par(page_txt(cles))} correspond à "
        f"plusieurs postes de {_ref_grille(lr.grille)} : la comparaison avec le tarif n'a pas pu être faite."
    )
    return ctx.constat(cid, classement, unite=lr.unite, libelle=libelle, prochaine_action=ACTION_D_AMBIGU,
                       composante=Composante.prestation, documents=[lr.facture.id],
                       preuves=[preuve(x, RolePreuve.valeur_b) for x in cles],
                       details={"grille": lr.grille.id, "motif": "plusieurs_postes"})


def _comparer_tarif(
    ctx: ControlContext,
    cid: str,
    lr: LigneRoutee,
    attendu: Decimal,
    calcul_txt: str,
    *,
    valeurs_cles: Sequence[ValeurSourcee],
    raisons: Sequence[RaisonCode] = (),
    confusion: Sequence[Confusion] = (),
    deduction: Decimal = ZERO,
    deduction_txt: str = "",
    details: dict | None = None,
) -> ResultatControle:
    """Comparaison commune D3, D4, D6, D7 : ``écart = facturé − attendu (− déduction)`` ; écart négatif ou
    sous ``T_TARIF`` : ``conforme`` ; ``ecart_certain`` si ``> S_TARIF`` et règle générale."""
    v = _montant(ctx, lr.ligne)
    assert v is not None
    facture = v.decimal_signe()
    ecart = facture - attendu - deduction
    tol, seuil = ctx.tol.t_tarif(), ctx.tol.s_tarif()
    poste = lr.poste.code_poste if lr.poste is not None else None
    commun = dict(
        unite=lr.unite, entrees={"montant": v}, attendu=arrondi_centime(attendu + deduction), constate=facture,
        ecart=arrondi_centime(ecart), tolerance=tol, seuil_certitude=seuil, documents=[lr.facture.id],
        details={"grille": lr.grille.id, "poste": poste, **(details or {})},
    )
    if ecart <= tol:
        return ctx.conforme(cid, **commun)
    classement = ctx.classify(
        cid, ecart=ecart, tolerance=tol, seuil_certitude=seuil, valeurs_cles=valeurs_cles,
        confusion=[Confusion(v, accepte=lambda x: x - attendu - deduction <= tol), *confusion],
        documents=[lr.facture.id], montant=ecart, raisons_supplementaires=raisons,
    )
    libelle = (
        f"La ligne {_libelle_ligne(lr.ligne)} de {_la_facture(lr.facture)}"
        f"{_par(page_txt([v]))} est facturée {format_montant(facture)} ; {_ref_grille(lr.grille)} prévoit "
        f"pour le poste {poste} : {calcul_txt}{deduction_txt}. Écart avec le tarif : "
        f"{format_montant(arrondi_centime(ecart))} (tolérance appliquée : {format_montant(tol)})."
    )
    return ctx.constat(
        cid, classement, libelle=libelle, prochaine_action=ACTION_D, montant=ecart, composante=Composante.prestation,
        preuves=[preuve(v, RolePreuve.valeur_b), *(preuve(x, RolePreuve.operande) for x in valeurs_cles if x is not v),
                 preuve(None, RolePreuve.valeur_a, calcul=calcul_txt)],
        **commun,
    )


def _quantite(ctx: ControlContext, lg: LigneFactureTransitaire) -> tuple[Decimal, ValeurSourcee | None]:
    q = _dec(ctx, lg.quantite)
    return (q, lg.quantite) if q is not None else (Decimal(1), None)


def _attendu_simple(ctx: ControlContext, lr: LigneRoutee) -> tuple[Decimal, str, list[ValeurSourcee], list[RaisonCode]] | None:
    """Attendu d'un poste ``forfait`` ou ``unitaire`` (D3, D6 hors dates, D7 hors pourcentage)."""
    p = lr.poste
    assert p is not None
    if p.prix is None:
        return None
    if p.mode is ModePoste.forfait:
        return p.prix, f"forfait de {format_montant(p.prix)}", [], []
    q, vq = _quantite(ctx, lr.ligne)
    attendu = borner(q * p.prix, p.minimum, p.maximum)
    unite = f" par {p.unite_base}" if p.unite_base else ""
    txt = f"{format_nombre(q)} × {format_montant(p.prix)}{unite} = {format_montant(arrondi_centime(attendu))}"
    raisons = [] if vq is not None else [RaisonCode.valeur_absente]
    return attendu, txt, [vq] if vq is not None else [], raisons


# =====================================================================================================
# D1 — Arithmétique interne
# =====================================================================================================


def _d1_resultat(
    ctx: ControlContext,
    f: Document,
    sous: str,
    unite: str,
    imprime: ValeurSourcee,
    calcul: Decimal,
    operandes: Sequence[ValeurSourcee],
    tol: Decimal,
    objet: str,
    calcul_txt: str,
    *,
    avec_montant: bool,
    alternatives: Sequence[Decimal] = (),
) -> ResultatControle:
    v_imp = imprime.decimal_signe()
    candidats = [calcul, *alternatives]
    calcul = min(candidats, key=lambda c: abs(v_imp - c))
    ecart = v_imp - calcul
    seuil = ctx.tol.s_arith()
    commun = dict(
        unite=unite, sous_controle=sous,
        entrees={"imprime": imprime, **{f"operande_{i}": v for i, v in enumerate(operandes)}},
        attendu=arrondi_centime(calcul), constate=v_imp, ecart=arrondi_centime(ecart), tolerance=tol,
        seuil_certitude=seuil, documents=[f.id],
    )
    if abs(ecart) <= tol:
        return ctx.conforme("D1", **commun)
    montant = ecart if avec_montant and ecart > 0 else None

    def acc_operande(o: ValeurSourcee):
        d = o.decimal_signe()
        return lambda x: any(abs(v_imp - (c - d + x)) <= tol for c in candidats)

    classement = ctx.classify(
        "D1", ecart=ecart, tolerance=tol, seuil_certitude=seuil, valeurs_cles=[imprime, *operandes],
        confusion=[Confusion(imprime, accepte=lambda x: any(abs(x - c) <= tol for c in candidats)),
                   *(Confusion(o, accepte=acc_operande(o)) for o in operandes)],
        documents=[f.id], montant=ecart,
    )
    libelle = (
        f"Sur {_la_facture(f)}{_par(page_txt([imprime]))}, {objet} "
        f"({format_montant(v_imp)}) diffère du calcul des valeurs imprimées ({calcul_txt} = "
        f"{format_montant(arrondi_centime(calcul))}) : écart de {format_montant(arrondi_centime(ecart))} "
        f"(tolérance appliquée : {format_montant(tol)})."
    )
    return ctx.constat(
        "D1", classement, libelle=libelle, prochaine_action=ACTION_D1, montant=montant,
        composante=Composante.prestation if montant is not None else None,
        preuves=[preuve(imprime, RolePreuve.valeur_b), *(preuve(o, RolePreuve.operande) for o in operandes),
                 preuve(None, RolePreuve.valeur_a, calcul=calcul_txt)],
        **commun,
    )


def _d1_facture(ctx: ControlContext, f: Document) -> list[ResultatControle]:
    ft = f.ft
    tol = ctx.tol
    out: list[ResultatControle] = []
    montants: list[tuple[LigneFactureTransitaire, ValeurSourcee]] = []
    for i, lg in enumerate(ft.lignes):
        unite = cle_unite(ft=f.id, ligne=i)
        q, pu, m = _dec(ctx, lg.quantite), _dec(ctx, lg.prix_unitaire), _dec(ctx, lg.montant_ht)
        if m is not None and lg.montant_ht is not None:
            montants.append((lg, lg.montant_ht))
        if q is not None and pu is not None and m is not None:
            assert lg.quantite is not None and lg.prix_unitaire is not None and lg.montant_ht is not None
            out.append(_d1_resultat(
                ctx, f, "ligne", unite, lg.montant_ht, q * pu, [lg.quantite, lg.prix_unitaire], tol.t_ligne(),
                f"le montant de la ligne {_libelle_ligne(lg)}",
                f"{format_nombre(q)} × {format_montant(pu)}", avec_montant=False,
            ))
        taux, mtva = _dec(ctx, lg.taux_tva), _dec(ctx, lg.montant_tva)
        if m is not None and taux is not None and mtva is not None:
            assert lg.montant_ht is not None and lg.taux_tva is not None and lg.montant_tva is not None
            out.append(_d1_resultat(
                ctx, f, "tva_ligne", unite, lg.montant_tva, m * taux / _CENT, [lg.montant_ht, lg.taux_tva],
                tol.t_ligne(), f"la TVA de la ligne {_libelle_ligne(lg)}",
                f"{format_montant(m)} × {format_pourcentage(taux)}", avec_montant=False,
            ))
    toutes_lisibles = len(montants) == len([lg for lg in ft.lignes if lg.montant_ht is not None])
    unite_f = cle_unite(ft=f.id)
    debours = [v for lg, v in montants if lg.nature.est_debours]
    prestations = [v for lg, v in montants if not lg.nature.est_debours]
    s_deb = _somme(v.decimal_signe() for v in debours)
    s_tout = _somme(v.decimal_signe() for _, v in montants)
    s_prest = _somme(v.decimal_signe() for v in prestations)

    td = ft.total_debours
    if toutes_lisibles and debours and _dec(ctx, td) is not None and td is not None and not td.est_reconstruite:
        out.append(_d1_resultat(
            ctx, f, "total_debours", unite_f, td, s_deb, debours, tol.t_somme(len(debours)),
            "le total des débours imprimé", f"somme des {len(debours)} lignes de débours", avec_montant=True,
        ))
    tht = ft.total_ht
    if toutes_lisibles and montants and _dec(ctx, tht) is not None and tht is not None:
        alternatives = [s_prest] if debours and prestations else []
        out.append(_d1_resultat(
            ctx, f, "total_ht", unite_f, tht, s_tout, [v for _, v in montants], tol.t_somme(len(montants)),
            "le total HT imprimé", f"somme des {len(montants)} montants HT", avec_montant=True,
            alternatives=alternatives,
        ))
    ttc, ht, tva = _dec(ctx, ft.total_ttc), _dec(ctx, ft.total_ht), _dec(ctx, ft.total_tva)
    if ttc is not None and ht is not None and tva is not None:
        assert ft.total_ttc is not None and ft.total_ht is not None and ft.total_tva is not None
        alternatives = [ht + tva + s_deb] if debours and toutes_lisibles and abs(ht - s_prest) <= tol.t_somme(
            max(1, len(prestations))) else []
        out.append(_d1_resultat(
            ctx, f, "total_ttc", unite_f, ft.total_ttc, ht + tva, [ft.total_ht, ft.total_tva], tol.t_somme(2),
            "le total TTC imprimé", "total HT + total TVA", avec_montant=True, alternatives=alternatives,
        ))
    net = _dec(ctx, ft.net_a_payer)
    if net is not None and ttc is not None:
        assert ft.net_a_payer is not None and ft.total_ttc is not None
        acompte = _dec(ctx, ft.acomptes) or ZERO
        ops = [ft.total_ttc] + ([ft.acomptes] if ft.acomptes is not None and _dec(ctx, ft.acomptes) is not None else [])
        out.append(_d1_resultat(
            ctx, f, "net_a_payer", unite_f, ft.net_a_payer, ttc - acompte, ops, tol.t_somme(len(ops)),
            "le net à payer imprimé", "total TTC − acomptes imprimés", avec_montant=True,
        ))
    return out


@control("D1")
def d1_arithmetique(ctx: ControlContext) -> list[ResultatControle]:
    """D1 — Arithmétique interne de chaque facture transitaire (sous-contrôles ``ligne``, ``tva_ligne``,
    ``total_debours``, ``total_ht``, ``total_ttc``, ``net_a_payer``). S'exécute sans grille.

    Montant (``recouvrable``) : total imprimé − total recalculé pour les sous-contrôles de total, quand il est
    positif ; ``null`` sinon. ``total_ht`` admet les deux présentations (débours inclus ou non) ; ``total_ttc``
    admet un TTC qui ajoute les débours hors taxes à un total HT de prestations.
    """
    factures = ctx.factures_transitaires()
    if not factures:
        return [ctx.non_applicable("D1", RaisonCode.facture_transitaire_absente)]
    out: list[ResultatControle] = []
    for f in factures:
        rs = _d1_facture(ctx, f)
        out.extend(rs or [ctx.non_verifiable("D1", RaisonCode.valeur_absente, unite=cle_unite(ft=f.id),
                                             documents=[f.id], details={"motif": "aucun calcul vérifiable"})])
    return out


# =====================================================================================================
# D2 — Ligne hors grille (et D7 pour une surcharge sans poste)
# =====================================================================================================


def _hors_grille(ctx: ControlContext, cid: str, lr: LigneRoutee) -> ResultatControle:
    v = _montant(ctx, lr.ligne)
    m = _dec(ctx, v)
    if m is None:
        return ctx.non_verifiable(cid, ctx.raison_inutilisable(v), unite=lr.unite, documents=[lr.facture.id])
    assert v is not None
    interdites = lr.grille.prestations_hors_grille is PrestationsHorsGrille.interdites
    tol, seuil = ctx.tol.t_tarif(), ctx.tol.s_tarif()
    commun = dict(unite=lr.unite, entrees={"montant": v}, attendu=ZERO, constate=m, ecart=arrondi_centime(m),
                  tolerance=tol, seuil_certitude=seuil, documents=[lr.facture.id],
                  details={"grille": lr.grille.id, "prestations_hors_grille": lr.grille.prestations_hors_grille.value})
    if m <= tol:
        return ctx.conforme(cid, **commun)
    cles = [x for x in (lr.ligne.libelle, v) if x is not None]
    raisons = [] if lr.ligne.libelle is not None and lr.ligne.libelle.valeur else [RaisonCode.valeur_absente]
    classement = ctx.classify(cid, ecart=m, tolerance=tol, seuil_certitude=seuil, valeurs_cles=cles,
                              documents=[lr.facture.id], eligible=interdites, montant=m,
                              raisons_supplementaires=raisons)
    regle = ("La grille indique que les prestations hors grille ne sont pas prévues." if interdites
             else "La grille admet des prestations hors grille : la ligne est signalée pour vérification.")
    libelle = (
        f"La ligne {_libelle_ligne(lr.ligne)} de {_la_facture(lr.facture)}"
        f"{_par(page_txt(cles))}, facturée {format_montant(m)}, ne correspond à aucun poste de "
        f"{_ref_grille(lr.grille)}. {regle}"
    )
    tva = _dec(ctx, lr.ligne.montant_tva)
    return ctx.constat(
        cid, classement, libelle=libelle, prochaine_action=ACTION_D if interdites else ACTION_D_TOLEREE, montant=m,
        montant_tva_associee=arrondi_centime(tva) if tva else None, composante=Composante.prestation,
        preuves=[preuve(x, RolePreuve.valeur_b) for x in cles], **commun,
    )


def _par_controle(ctx: ControlContext, cid: str, traiter) -> list[ResultatControle]:
    d = _prealable(ctx, cid)
    if isinstance(d, list):
        return d
    lignes, na = d
    out = list(na)
    for lr in lignes:
        r = traiter(lr)
        if r is not None:
            out.append(r)
    return out


@control("D2")
def d2_hors_grille(ctx: ControlContext) -> list[ResultatControle]:
    """D2 — Ligne de prestation sans poste dans la grille. ``interdites`` : ``ecart_certain`` possible ;
    ``tolerees`` : ``a_verifier``. Montant = HT de la ligne (TVA en ``montant_tva_associee``)."""
    return _par_controle(ctx, "D2", lambda lr: _hors_grille(ctx, "D2", lr) if lr.controle == "D2" else None)


# =====================================================================================================
# D3 — Prix supérieur à la grille
# =====================================================================================================


def _d3_ligne(ctx: ControlContext, cid: str, lr: LigneRoutee) -> ResultatControle:
    if lr.ambigu:
        return _ambigu(ctx, cid, lr)
    v = _montant(ctx, lr.ligne)
    if _dec(ctx, v) is None:
        return ctx.non_verifiable(cid, ctx.raison_inutilisable(v), unite=lr.unite, documents=[lr.facture.id])
    assert v is not None and lr.poste is not None
    if lr.poste.mode is ModePoste.pourcentage:
        return _pourcentage(ctx, cid, lr)
    a = _attendu_simple(ctx, lr)
    if a is None:
        return ctx.non_verifiable(cid, RaisonCode.valeur_absente, unite=lr.unite, documents=[lr.facture.id],
                                  details={"motif": "prix_du_poste_absent"})
    attendu, txt, ops, raisons = a
    return _comparer_tarif(ctx, cid, lr, attendu, txt, valeurs_cles=[v, *ops], raisons=raisons)


@control("D3")
def d3_prix_grille(ctx: ControlContext) -> list[ResultatControle]:
    """D3 — ``forfait`` : ``montant_ht − prix`` ; ``unitaire`` : ``montant_ht − quantité × prix`` (bornés par
    minimum et maximum). Écart négatif : ``conforme``."""
    return _par_controle(ctx, "D3", lambda lr: _d3_ligne(ctx, "D3", lr) if lr.controle == "D3" else None)


# =====================================================================================================
# D4 — Frais d'avance de fonds contre la grille ; pourcentages (D7)
# =====================================================================================================


def _assiette(ctx: ControlContext, f: Document, base: BasePourcentage | None) -> tuple[Decimal, Decimal, list[
    ValeurSourcee
]] | None:
    """(assiette facturée, excédent constaté par C, valeurs) pour un pourcentage de débours."""
    decs = ctx.declarations()
    unites = unites_c(ctx) if decs else []
    concernees = unites_pour_facture(ctx, f, unites)
    if concernees:
        refs = {d.id: reference_declaration(ctx, d) for d in decs}
        excedents = [excedent_debours(u, refs, base) for u in concernees]
        excedent = _somme(e for e in excedents if e is not None)
        assiette = _somme(assiette_debours(u, base) for u in concernees)
        vals = [x.valeur for u in concernees for x in u.lignes if x.valeur is not None]
        return assiette, excedent, vals
    # Pas de déclaration rapprochée : débours de la facture elle-même, sans correction.
    lignes = [lg for lg in f.ft.lignes if lg.nature.est_debours]
    if not lignes:
        return None
    exclure = {
        BasePourcentage.debours_hors_tva: {NatureLigne.debours_tva},
        BasePourcentage.droits: {n for n in NatureLigne if n is not NatureLigne.debours_droits},
    }.get(base, set()) if base is not None else set()
    vals = [lg.montant_ht for lg in lignes if lg.nature not in exclure and lg.montant_ht is not None]
    if any(_dec(ctx, v) is None for v in vals):
        return None
    return _somme(v.decimal_signe() for v in vals), ZERO, vals


def _pourcentage(ctx: ControlContext, cid: str, lr: LigneRoutee) -> ResultatControle:
    """Poste en pourcentage (FAF, surcharge) : ``attendu = borner(pourcentage × assiette)``."""
    p = lr.poste
    assert p is not None
    v = _montant(ctx, lr.ligne)
    assert v is not None
    if p.pourcentage is None:
        return ctx.non_verifiable(cid, RaisonCode.valeur_absente, unite=lr.unite, documents=[lr.facture.id],
                                  details={"motif": "pourcentage_du_poste_absent"})
    base = p.base_pourcentage
    if base in (None, BasePourcentage.autre, BasePourcentage.valeur_marchandise) and cid == "D7":
        # Surcharge en pourcentage : assiette = lignes de transport de la facture.
        vals = [lg.montant_ht for lg in lr.facture.ft.lignes if lg.nature is NatureLigne.transport
                and lg.montant_ht is not None]
        if not vals or any(_dec(ctx, x) is None for x in vals):
            return ctx.non_verifiable(cid, RaisonCode.valeur_absente, unite=lr.unite, documents=[lr.facture.id],
                                      details={"motif": "assiette_de_la_surcharge_absente"})
        assiette, excedent = _somme(x.decimal_signe() for x in vals), ZERO
    elif base in (BasePourcentage.valeur_marchandise, BasePourcentage.autre):
        return ctx.non_verifiable(cid, RaisonCode.valeur_absente, unite=lr.unite, documents=[lr.facture.id],
                                  details={"motif": "assiette_non_calculable"})
    else:
        a = _assiette(ctx, lr.facture, base)
        if a is None:
            return ctx.non_verifiable(cid, RaisonCode.valeur_absente, unite=lr.unite, documents=[lr.facture.id],
                                      details={"motif": "assiette_non_calculable"})
        assiette, excedent, vals = a
    retenue = assiette - excedent
    attendu = borner(arrondi_centime(p.pourcentage * retenue / _CENT), p.minimum, p.maximum)
    bornes = []
    if p.minimum is not None:
        bornes.append(f"minimum {format_montant(p.minimum)}")
    if p.maximum is not None:
        bornes.append(f"maximum {format_montant(p.maximum)}")
    calcul_txt = (f"{format_pourcentage(p.pourcentage)} × {format_montant(arrondi_centime(retenue))}"
                  f"{_par(*bornes)} = {format_montant(attendu)}")
    details = {"assiette_facturee": str(arrondi_centime(assiette)), "excedent_debours": str(arrondi_centime(excedent))}
    deduction, deduction_txt = ZERO, ""
    if excedent > 0:
        calcul_txt += " (débours retenus : débours refacturés moins l'excédent constaté sur la déclaration)"
        if cid == "D4":
            c6 = [r for r in ctx.anterieurs("C6", unite=lr.unite)
                  if r.constat is not None and r.constat.montant_en_jeu is not None and r.constat.montant_en_jeu > 0]
            if c6:
                assert c6[0].constat is not None and c6[0].constat.montant_en_jeu is not None
                deduction = c6[0].constat.montant_en_jeu
                deduction_txt = (f", plus {format_montant(deduction)} déjà relevés sur l'excédent de débours "
                                 f"par le contrôle C6")
                details["deduit_c6"] = str(deduction)
    return _comparer_tarif(ctx, cid, lr, attendu, calcul_txt, valeurs_cles=[v], deduction=deduction,
                           deduction_txt=deduction_txt, details=details)


def _d4_ligne(ctx: ControlContext, lr: LigneRoutee) -> ResultatControle:
    if lr.ambigu:
        return _ambigu(ctx, "D4", lr)
    v = _montant(ctx, lr.ligne)
    if _dec(ctx, v) is None:
        return ctx.non_verifiable("D4", ctx.raison_inutilisable(v), unite=lr.unite, documents=[lr.facture.id])
    assert lr.poste is not None
    if lr.poste.mode is ModePoste.pourcentage:
        return _pourcentage(ctx, "D4", lr)
    return _d3_ligne(ctx, "D4", lr)


@control("D4")
def d4_faf_grille(ctx: ControlContext) -> list[ResultatControle]:
    """D4 — FAF contre la grille : ``attendu = borner(pourcentage × assiette retenue, minimum, maximum)``,
    l'assiette retenue étant les débours refacturés moins l'excédent constaté par la famille C. La part déjà
    chiffrée par C6 sur la même ligne est déduite (aucun double comptage)."""
    return _par_controle(ctx, "D4", lambda lr: _d4_ligne(ctx, lr) if lr.controle == "D4" else None)


# =====================================================================================================
# D5 — Ligne en double
# =====================================================================================================


@control("D5")
def d5_ligne_double(ctx: ControlContext) -> list[ResultatControle]:
    """D5 — Deux lignes de prestation de même nature, même libellé normalisé, même montant et même MRN ou
    référence de transport (ou aucune) sur une même facture. Les débours en double sont comptés par C."""
    d = _prealable(ctx, "D5")
    if isinstance(d, list):
        return d
    lignes, na = d
    out = list(na)
    par_facture: dict[str, list[LigneRoutee]] = {}
    for lr in lignes:
        par_facture.setdefault(lr.facture.id, []).append(lr)
    for fid, lrs in par_facture.items():
        f = lrs[0].facture
        groupes: dict[tuple, list[LigneRoutee]] = {}
        for lr in lrs:
            lg = lr.ligne
            m = _dec(ctx, _montant(ctx, lg))
            if m is None or lg.libelle is None or not lg.libelle.valeur:
                continue
            ref = ""
            if lg.mrn is not None and lg.mrn.valeur:
                ref = "mrn:" + mrn_prefixe(lg.mrn.valeur)
            elif lg.ref_transport is not None and lg.ref_transport.valeur:
                ref = "transport:" + (norm_ref_transport(lg.ref_transport.valeur) or norm_ref(lg.ref_transport.valeur))
            groupes.setdefault((lg.nature.value, _cle(lg.libelle.valeur), m, ref), []).append(lr)
        doubles = [g for g in groupes.values() if len(g) > 1]
        if not doubles:
            out.append(ctx.conforme("D5", unite=cle_unite(ft=fid), documents=[fid]))
            continue
        for g in doubles:
            unite = cle_unite(ft=fid, lignes=[lr.index for lr in g])
            vals = [x for lr in g for x in (lr.ligne.libelle, _montant(ctx, lr.ligne)) if x is not None]
            m = _montant(ctx, g[0].ligne)
            assert m is not None
            montant = m.decimal_signe() * (len(g) - 1)
            multiple = any(lr.poste is not None and lr.poste.mode in (ModePoste.unitaire, ModePoste.par_jour)
                           for lr in g)
            classement = ctx.classify(
                "D5", ecart=montant, tolerance=ctx.tol.t_tarif(), seuil_certitude=ctx.tol.s_tarif(),
                valeurs_cles=vals, documents=[fid], montant=montant,
                raisons_supplementaires=[RaisonCode.controle_signal_seulement] if multiple else [],
            )
            libelle = (
                f"{libelle_facture([f])} porte {len(g)} lignes identiques {_libelle_ligne(g[0].ligne)} de "
                f"{format_montant(m.decimal_signe())} chacune{_par(page_txt(vals))} (même nature, même libellé, "
                f"même montant, même référence d'envoi)."
            )
            out.append(ctx.constat(
                "D5", classement, unite=unite, libelle=libelle, prochaine_action=ACTION_D5, montant=montant,
                composante=Composante.prestation, documents=[fid],
                preuves=[preuve(_montant(ctx, lr.ligne), RolePreuve.valeur_b) for lr in g],
                entrees={f"ligne_{lr.index}": _montant(ctx, lr.ligne) for lr in g if _montant(ctx, lr.ligne)},
                attendu=m.decimal_signe(), constate=m.decimal_signe() * len(g), ecart=arrondi_centime(montant),
                tolerance=ctx.tol.t_tarif(), seuil_certitude=ctx.tol.s_tarif(),
                details={"lignes": [lr.index for lr in g], "poste_quantite_multiple": multiple},
            ))
    return out


# =====================================================================================================
# D6 — Magasinage
# =====================================================================================================


def _date(ctx: ControlContext, v: ValeurSourcee | None) -> date | None:
    if not ctx.utilisable(v):
        return None
    assert v is not None
    try:
        return v.date_iso()
    except ValueError:
        return None


def _d6_ligne(ctx: ControlContext, lr: LigneRoutee) -> ResultatControle:
    if lr.ambigu:
        return _ambigu(ctx, "D6", lr)
    v = _montant(ctx, lr.ligne)
    if _dec(ctx, v) is None:
        return ctx.non_verifiable("D6", ctx.raison_inutilisable(v), unite=lr.unite, documents=[lr.facture.id])
    assert v is not None and lr.poste is not None
    p, lg = lr.poste, lr.ligne
    if p.mode is ModePoste.pourcentage:
        return _pourcentage(ctx, "D6", lr)
    if p.mode is ModePoste.forfait or p.prix is None:
        a = _attendu_simple(ctx, lr)
        if a is None:
            return ctx.non_verifiable("D6", RaisonCode.valeur_absente, unite=lr.unite, documents=[lr.facture.id],
                                      details={"motif": "prix_du_poste_absent"})
        attendu, txt, ops, raisons = a
        return _comparer_tarif(ctx, "D6", lr, attendu, txt, valeurs_cles=[v, *ops], raisons=raisons)
    debut, fin = _date(ctx, lg.date_debut), _date(ctx, lg.date_fin)
    franchise = p.franchise_jours or 0
    if debut is None or fin is None or fin < debut:
        # Sans période lisible : prix unitaire contre quantité facturée (comme D3).
        q = _dec(ctx, lg.quantite)
        if q is None:
            return ctx.non_verifiable("D6", RaisonCode.valeur_absente, unite=lr.unite, documents=[lr.facture.id],
                                      details={"motif": "periode_et_quantite_absentes"})
        assert lg.quantite is not None
        attendu = borner(q * p.prix, p.minimum, p.maximum)
        txt = f"{format_nombre(q)} jour(s) × {format_montant(p.prix)} = {format_montant(arrondi_centime(attendu))}"
        return _comparer_tarif(ctx, "D6", lr, attendu, txt, valeurs_cles=[v, lg.quantite],
                               raisons=[RaisonCode.valeur_absente] if franchise else [],
                               details={"motif": "periode_absente"})
    assert lg.date_debut is not None and lg.date_fin is not None
    jours_periode = (fin - debut).days + 1
    jours = max(0, jours_periode - franchise)
    attendu = borner(jours * p.prix, p.minimum, p.maximum) if jours else ZERO
    txt = (f"({jours_periode} jour(s) du {debut.strftime('%d/%m/%Y')} au {fin.strftime('%d/%m/%Y')} − "
           f"{franchise} jour(s) de franchise) × {format_montant(p.prix)} = {format_montant(arrondi_centime(attendu))}")
    return _comparer_tarif(ctx, "D6", lr, attendu, txt, valeurs_cles=[v, lg.date_debut, lg.date_fin],
                           details={"jours_periode": jours_periode, "franchise_jours": franchise,
                                    "jours_attendus": jours})


@control("D6")
def d6_magasinage(ctx: ControlContext) -> list[ResultatControle]:
    """D6 — ``jours_attendus = max(0, (fin − début + 1) − franchise_jours)`` ; ``attendu = jours × prix`` ;
    ``écart = facturé − attendu``. Certain si dates et montant lus ≥ 0,90 et ``écart > S_TARIF``."""
    return _par_controle(ctx, "D6", lambda lr: _d6_ligne(ctx, lr) if lr.controle == "D6" else None)


# =====================================================================================================
# D7 — Surcharges
# =====================================================================================================


def _d7_ligne(ctx: ControlContext, lr: LigneRoutee) -> ResultatControle:
    if lr.poste is None and not lr.ambigu:
        return _hors_grille(ctx, "D7", lr)
    return _d3_ligne(ctx, "D7", lr)


@control("D7")
def d7_surcharges(ctx: ControlContext) -> list[ResultatControle]:
    """D7 — Surcharge sans poste : comme D2 ; surcharge en pourcentage : ``pourcentage × assiette`` (débours
    selon ``base_pourcentage``, sinon lignes de transport de la facture) ; forfait/unitaire : comme D3."""
    return _par_controle(ctx, "D7", lambda lr: _d7_ligne(ctx, lr) if lr.controle == "D7" else None)


# =====================================================================================================
# D8 — TVA facturée sur une ligne de débours
# =====================================================================================================


@control("D8")
def d8_tva_debours(ctx: ControlContext) -> list[ResultatControle]:
    """D8 — Ligne ``debours_*`` portant une TVA (> 0) : toujours ``a_verifier`` (raison ``point_fiscal``),
    renvoi vers l'expert-comptable ; montant informatif = TVA de la ligne (jamais additionné aux totaux
    certains). Exige une grille validée (§13)."""
    if not ctx.factures_transitaires():
        return [ctx.non_applicable("D8", RaisonCode.facture_transitaire_absente)]
    out: list[ResultatControle] = []
    for f in ctx.factures_transitaires():
        g = grille_pour_facture(ctx, f)
        if g is None:
            out.append(ctx.non_applicable("D8", RaisonCode.aucune_grille_validee, unite=cle_unite(ft=f.id),
                                          documents=[f.id],
                                          details={"motif": "aucune grille tarifaire validée pour ce transitaire"}))
            continue
        for i, lg in enumerate(f.ft.lignes):
            if not lg.nature.est_debours:
                continue
            unite = cle_unite(ft=f.id, ligne=i)
            tva = _dec(ctx, lg.montant_tva)
            source: list[ValeurSourcee] = []
            if tva is not None and lg.montant_tva is not None:
                source = [lg.montant_tva]
            else:
                taux, ht = _dec(ctx, lg.taux_tva), _dec(ctx, lg.montant_ht)
                if taux is not None and ht is not None and lg.taux_tva is not None and lg.montant_ht is not None:
                    tva, source = arrondi_centime(ht * taux / _CENT), [lg.taux_tva, lg.montant_ht]
            if tva is None or tva <= ctx.tol.t_ligne():
                out.append(ctx.conforme("D8", unite=unite, documents=[f.id],
                                        entrees={f"tva_{k}": v for k, v in enumerate(source)}))
                continue
            # Toujours a_verifier : la raison point_fiscal est une raison de doute (§13 D8) ; eligible=True
            # évite d'y ajouter « contrôle de signal », sans permettre un ecart_certain.
            classement = ctx.classify("D8", ecart=tva, tolerance=ctx.tol.t_ligne(), seuil_certitude=None,
                                      valeurs_cles=source, documents=[f.id], montant=tva, eligible=True,
                                      raisons_supplementaires=[RaisonCode.point_fiscal])
            libelle = (
                f"La ligne de débours {_libelle_ligne(lg)} de "
                f"{_la_facture(f)}{_par(page_txt(source))} porte "
                f"{format_montant(tva)} de TVA (montant de TVA facturé sur un débours, indiqué pour information)."
            )
            out.append(ctx.constat(
                "D8", classement, unite=unite, libelle=libelle, prochaine_action=ACTION_D8, montant=tva,
                composante=Composante.tva, documents=[f.id],
                preuves=[preuve(v, RolePreuve.valeur_b) for v in source],
                entrees={f"tva_{k}": v for k, v in enumerate(source)}, attendu=ZERO, constate=tva, ecart=tva,
                tolerance=ctx.tol.t_ligne(), details={"informatif": True},
            ))
    return out


# =====================================================================================================
# D9 — Lignes supplémentaires
# =====================================================================================================


def _nombre_articles(ctx: ControlContext, f: Document) -> tuple[int, list[ValeurSourcee], bool] | None:
    """(nombre d'articles des déclarations couvertes par la facture, valeurs, imprimé ?)."""
    from controldone.controls.famille_c import declarations_couvertes

    decs = declarations_couvertes(ctx, f)
    if not decs:
        return None
    total, vals, imprime = 0, [], True
    for d in decs:
        c = d.dec
        n = None
        if ctx.utilisable(c.nombre_articles):
            assert c.nombre_articles is not None
            try:
                n = c.nombre_articles.entier()
                vals.append(c.nombre_articles)
            except ValueError:
                n = None
        if n is None:
            if not c.articles:
                return None
            n, imprime = len(c.articles), False
            vals.extend(a.numero_article for a in c.articles if a.numero_article is not None)
        total += n
    return total, vals, imprime


def _d9_ligne(ctx: ControlContext, lr: LigneRoutee) -> ResultatControle:
    if lr.ambigu:
        return _ambigu(ctx, "D9", lr)
    v = _montant(ctx, lr.ligne)
    m = _dec(ctx, v)
    if m is None:
        return ctx.non_verifiable("D9", ctx.raison_inutilisable(v), unite=lr.unite, documents=[lr.facture.id])
    assert v is not None and lr.poste is not None
    p = lr.poste
    if p.prix is None or p.prix == 0:
        return ctx.non_verifiable("D9", RaisonCode.valeur_absente, unite=lr.unite, documents=[lr.facture.id],
                                  details={"motif": "prix_du_poste_absent"})
    inclus = p.inclus
    if inclus is None:
        ded = [x for x in lr.grille.postes if x.nature is NatureLigne.frais_dedouanement and x.inclus is not None]
        inclus = ded[0].inclus if len(ded) == 1 else 0
    assert inclus is not None
    na = _nombre_articles(ctx, lr.facture)
    if na is None:
        return ctx.non_verifiable("D9", RaisonCode.document_manquant if not ctx.declarations()
                                  else RaisonCode.valeur_absente, unite=lr.unite, documents=[lr.facture.id],
                                  details={"motif": "nombre_articles_absent"})
    n, vals_n, imprime = na
    q = _dec(ctx, lr.ligne.quantite)
    raisons: list[RaisonCode] = [] if imprime else [RaisonCode.total_reconstruit]
    cles = [v, *vals_n]
    if q is None:
        q = m / p.prix
        if q != q.to_integral_value():
            return ctx.non_verifiable("D9", RaisonCode.valeur_absente, unite=lr.unite, documents=[lr.facture.id],
                                      details={"motif": "quantite_absente"})
    else:
        assert lr.ligne.quantite is not None
        cles.append(lr.ligne.quantite)
    attendu_qte = max(0, n - inclus)
    ecart = (q - attendu_qte) * p.prix
    tol, seuil = ctx.tol.t_tarif(), ctx.tol.s_tarif()
    docs = [lr.facture.id, *dict.fromkeys(x.document_id for x in vals_n if x.document_id)]
    commun = dict(unite=lr.unite, entrees={"montant": v, **{f"articles_{k}": x for k, x in enumerate(vals_n)}},
                  attendu=attendu_qte, constate=q, ecart=arrondi_centime(ecart), tolerance=tol, seuil_certitude=seuil,
                  documents=docs, details={"grille": lr.grille.id, "poste": p.code_poste, "nombre_articles": n,
                                           "inclus": inclus})
    if ecart <= tol:
        return ctx.conforme("D9", **commun)
    classement = ctx.classify("D9", ecart=ecart, tolerance=tol, seuil_certitude=seuil, valeurs_cles=cles,
                              documents=docs, montant=ecart, raisons_supplementaires=raisons)
    libelle = (
        f"La ligne {_libelle_ligne(lr.ligne)} de {_la_facture(lr.facture)}"
        f"{_par(page_txt([v]))} facture {format_nombre(q)} article(s) supplémentaire(s) ; la déclaration "
        f"compte {n} article(s){_par(page_txt(vals_n))} et {_ref_grille(lr.grille)} inclut {inclus} article(s) "
        f"dans le forfait, soit {attendu_qte} article(s) supplémentaire(s) à {format_montant(p.prix)}. "
        f"Écart avec le tarif : {format_montant(arrondi_centime(ecart))} (tolérance appliquée : "
        f"{format_montant(tol)})."
    )
    return ctx.constat(
        "D9", classement, libelle=libelle, prochaine_action=ACTION_D, montant=ecart, composante=Composante.prestation,
        preuves=[preuve(v, RolePreuve.valeur_b), *(preuve(x, RolePreuve.valeur_a) for x in vals_n)], **commun,
    )


@control("D9")
def d9_lignes_supplementaires(ctx: ControlContext) -> list[ResultatControle]:
    """D9 — ``attendu_qte = max(0, nombre_articles − inclus)`` ; ``écart = (qte_facturée − attendu_qte) × prix``.
    Certain si le nombre d'articles est imprimé (ou structuré) et lu ≥ 0,90 et ``écart > S_TARIF``."""
    return _par_controle(ctx, "D9", lambda lr: _d9_ligne(ctx, lr) if lr.controle == "D9" else None)
