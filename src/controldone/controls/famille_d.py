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

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_CEILING, Decimal
from itertools import pairwise

from controldone.controls import _aides_befg as aides
from controldone.controls._aides_befg import ZERO
from controldone.controls._aides_befg import entre_parentheses as _par
from controldone.controls._aides_befg import num_utilisable as _dec
from controldone.controls._aides_befg import somme as _somme
from controldone.controls.famille_c import (
    assiette_debours,
    borner,
    declarations_couvertes,
    declarations_de_ligne,
    dossier_principal,
    excedent_debours,
    facture_multi_envois,
    grille_pour_facture,
    libelle_facture,
    ligne_evaluee_ici,
    mrns_cites,
    page_txt,
    reference_declaration,
    unites_c,
    unites_pour_ligne,
)
from controldone.controls.framework import (
    Confusion,
    ControlContext,
    arrondi_centime,
    arrondi_unite,
    cle_unite,
    control,
    preuve,
)
from controldone.formatage import format_montant, format_nombre, format_pourcentage
from controldone.model import (
    BasePourcentage,
    CategorieTaxe,
    Composante,
    Document,
    GrilleTarifaire,
    LigneFactureTransitaire,
    Methode,
    ModePoste,
    NatureLigne,
    Niveau,
    PosteGrille,
    PrestationsHorsGrille,
    RaisonCode,
    ResultatControle,
    RolePreuve,
    ValeurSourcee,
)
from controldone.normalize.natures import renvoie_a_une_annexe
from controldone.normalize.parties import identifier_transitaire
from controldone.normalize.refs import (
    cle_confusion_ocr,
    mrn_prefixe,
    norm_ref,
    norm_ref_transport,
)
from controldone.normalize.text import cle_texte
from controldone.recouvrement.imputation import choisir_par_paliers, montant_net_ligne

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

#: Natures dont seul le libellé désigne un poste de la grille (D-704, D-2203).
_NATURES_PAR_LIBELLE = frozenset({NatureLigne.autre_prestation, NatureLigne.surcharge})

#: Natures traitées par D3 lorsqu'elles sont rapprochées d'un poste.
_ROUTE_SPECIALE = {
    NatureLigne.frais_avance_fonds: "D4",
    NatureLigne.magasinage: "D6",
    NatureLigne.surcharge: "D7",
}


# =====================================================================================================
# Outils
# =====================================================================================================


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
    if ligne.nature in _NATURES_PAR_LIBELLE:
        # « tout le reste » (§5.3.3) : la nature n'identifie pas un poste, seul le libellé le fait (D-704).
        # Idem pour une surcharge : carburant, sûreté, haute saison… sont des surcharges distinctes ; une
        # surcharge dont le libellé ne figure dans aucun poste est « sans poste » (§13 D7), pas celle de la
        # grille de même nature (D-2203).
        m = par_libelle(candidats) if libelle else []
        if len(m) == 1:
            return m[0], False
        if len(m) > 1:
            return None, True
        candidats = []
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
            if lg.nature.est_debours or not ligne_evaluee_ici(ctx, f, lg):
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
    """Montant hors TVA de la ligne ; TVA comprise ou hors-taxe déduit du TTC : marqué, jamais certain (D-2701)."""
    return montant_net_ligne(lg, ctx.utilisable)


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


def _credits_ligne(ctx: ControlContext, lr: LigneRoutee) -> list[tuple[Document, ValeurSourcee, Decimal]]:
    """Lignes d'avoirs déjà reçus qui créditent cette ligne de prestation (§8.6 : montant net des avoirs
    déjà imputés), selon la règle unique de §17.2 (D-1210) : lignes d'avoir du dossier (E3, ``C_MIN_UTILE``),
    même émetteur, même nature, rattachement par paliers (facture d'origine, à défaut MRN de la ligne).
    Une ligne d'avoir n'est imputée qu'à une ligne de facture : parmi les lignes de même nature, celle dont
    le MRN correspond (à une confusion OCR près) s'il y en a plusieurs, sinon la première (D-703)."""
    f = lr.facture
    num = f.ft.numero.valeur if f.ft.numero is not None and f.ft.numero.valeur else None
    mrn_ligne = mrn_prefixe(lr.ligne.mrn.valeur) if ctx.utilisable(lr.ligne.mrn) and lr.ligne.mrn else None
    # Ligne sans MRN : MRN de l'en-tête de la facture (§12.2) ; référence de transport de la facture (§17.2,
    # troisième palier), D-2206.
    mrns = (mrn_ligne,) if mrn_ligne else tuple(x.valeur for x in f.ft.refs_mrn if x.valeur and ctx.utilisable(x))
    transports = tuple(x.valeur for x in f.ft.refs_transport if x.valeur and ctx.utilisable(x))
    emetteur = aides.emetteur_de(ctx, f)
    out: list[tuple[Document, ValeurSourcee, Decimal]] = []
    for lc in aides.lignes_credit_du_dossier(ctx):
        if lc.nature is not lr.ligne.nature or not aides.memes_emetteurs(lc.emetteur, emetteur):
            continue
        palier, _ = choisir_par_paliers(lc, [lr], factures=lambda _x: (num,), mrns=lambda _x: mrns,
                                        transports=lambda _x: transports)
        if not palier:
            continue
        memes = [i for i, lg in enumerate(f.ft.lignes) if lg.nature is lc.nature]
        if len(memes) > 1 and lc.mrns:
            cles = {cle_confusion_ocr(mrn_prefixe(m)) for m in lc.mrns}
            par_mrn = [
                i for i in memes
                if ctx.utilisable(f.ft.lignes[i].mrn) and f.ft.lignes[i].mrn is not None
                and cle_confusion_ocr(mrn_prefixe(f.ft.lignes[i].mrn.valeur)) in cles
            ]
            memes = par_mrn or memes
        avoir = ctx.document(lc.avoir_id)
        if not memes or memes[0] != lr.index or avoir is None or lc.valeur is None:
            continue
        out.append((avoir, lc.valeur, lc.montant))
    return out


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
    brut = facture - attendu - deduction
    credits = _credits_ligne(ctx, lr) if brut > 0 else []
    credit = _somme(m for _, _, m in credits)
    ecart = brut - credit
    tol, seuil = ctx.tol.t_tarif(), ctx.tol.s_tarif()
    poste = lr.poste.code_poste if lr.poste is not None else None
    docs = [lr.facture.id, *dict.fromkeys(a.id for a, _, _ in credits)]
    det = {"grille": lr.grille.id, "poste": poste, **(details or {})}
    if credits:
        det["avoirs_deduits"] = str(arrondi_centime(credit))
        det["ecart_brut_avant_avoirs"] = str(arrondi_centime(brut))
    commun = dict(
        unite=lr.unite, entrees={"montant": v}, attendu=arrondi_centime(attendu + deduction), constate=facture,
        ecart=arrondi_centime(ecart), tolerance=tol, seuil_certitude=seuil, documents=docs, details=det,
    )
    if ecart <= tol:
        return ctx.conforme(cid, **commun)
    devise = lr.facture.ft.devise
    if ctx.utilisable(devise) and devise is not None and (devise.valeur or "").strip().upper() not in ("", "EUR"):
        # Grille en euros, facture dans une autre devise : la comparaison suppose une conversion (D-2213).
        raisons = [*raisons, RaisonCode.devise_incertaine]
    classement = ctx.classify(
        cid, ecart=ecart, tolerance=tol, seuil_certitude=seuil,
        valeurs_cles=[*valeurs_cles, *(x for _, x, _ in credits)],
        confusion=[Confusion(v, accepte=lambda x: x - attendu - deduction - credit <= tol), *confusion],
        documents=docs, montant=ecart, raisons_supplementaires=raisons,
    )
    avoirs_txt = ""
    if credits:
        nums = ", ".join(dict.fromkeys(_numero_avoir(a) for a, _, _ in credits))
        avoirs_txt = f", après déduction de {format_montant(arrondi_centime(credit))} d'avoir déjà reçu ({nums})"
    libelle = (
        f"La ligne {_libelle_ligne(lr.ligne)} de {_la_facture(lr.facture)}"
        f"{_par(page_txt([v]))} est facturée {format_montant(facture)} ; {_ref_grille(lr.grille)} prévoit "
        f"pour le poste {poste} : {calcul_txt}{deduction_txt}. Écart avec le tarif{avoirs_txt} : "
        f"{format_montant(arrondi_centime(ecart))} (tolérance appliquée : {format_montant(tol)})."
    )
    return ctx.constat(
        cid, classement, libelle=libelle, prochaine_action=ACTION_D, montant=ecart,
        montant_brut=brut if credits else None, composante=Composante.prestation,
        preuves=[preuve(v, RolePreuve.valeur_b), *(preuve(x, RolePreuve.operande) for x in valeurs_cles if x is not v),
                 preuve(None, RolePreuve.valeur_a, calcul=calcul_txt),
                 *(preuve(x, RolePreuve.contexte) for _, x, _ in credits)],
        **commun,
    )


def _numero_avoir(a: Document) -> str:
    n = a.av.numero
    return f"n° {n.valeur_brute or n.valeur}" if n is not None and n.valeur else "sans numéro lu"


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


#: Raisons de classement qui disent qu'une lecture (OCR) ne suffit pas à trancher (D-3703).
_RAISONS_LECTURE = frozenset({RaisonCode.confiance_insuffisante, RaisonCode.lecture_non_corroboree})


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
    ligne_non_lue: bool = False,
    produit: bool = False,
    somme_de_lignes: bool = False,
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
    if ligne_non_lue and ecart > 0:
        # Les totaux imprimés se confirment entre eux : une ligne non lue explique l'écart (D-706).
        return ctx.non_verifiable("D1", RaisonCode.valeur_absente, **{
            **commun, "details": {"motif": "ligne_probablement_non_lue"}})
    montant = ecart if avec_montant and ecart > 0 else None

    def acc_operande(o: ValeurSourcee):
        d = o.decimal_signe()
        if produit:
            # D-2311 : facteur d'un produit (quantité, prix, taux) : la variante remplace le facteur, elle ne
            # s'ajoute pas (la forme additive ne valait que pour une somme).
            return lambda x: d != 0 and any(abs(v_imp - c * x / d) <= tol for c in candidats)
        return lambda x: any(abs(v_imp - (c - d + x)) <= tol for c in candidats)

    classement = ctx.classify(
        "D1", ecart=ecart, tolerance=tol, seuil_certitude=seuil, valeurs_cles=[imprime, *operandes],
        confusion=[Confusion(imprime, accepte=lambda x: any(abs(x - c) <= tol for c in candidats)),
                   *(Confusion(o, accepte=acc_operande(o)) for o in operandes)],
        documents=[f.id], montant=ecart,
    )
    if (somme_de_lignes and ecart > 0 and classement.niveau is Niveau.a_verifier
            and set(classement.raisons) & _RAISONS_LECTURE):
        # D-3703 : total imprimé supérieur à la somme des lignes lues, lecture sous le seuil (scan) : des lignes
        # non lues expliquent l'écart dans le sens observé, et aucune identité ne prouve que la lecture est
        # complète (elle aurait rendu le classement certain). Comme D-2307 pour B2/B3.
        return ctx.non_verifiable("D1", RaisonCode.confiance_insuffisante, **{
            **commun, "details": {"motif": "lignes_possiblement_non_lues"}})
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


def _tva_confirme_total(
    ctx: ControlContext, ft, total_ht: Decimal, s_deb: Decimal, s_prest: Decimal,
    prestations: Sequence[ValeurSourcee],
) -> bool:
    """Le total de TVA imprimé correspond au total HT imprimé (prestations taxées à un taux unique) et non à
    la somme des lignes lues : les totaux imprimés sont cohérents entre eux et une ligne de prestation a
    échappé à la lecture (§8.5.1 conditions 4 et 6, D-706)."""
    tva = _dec(ctx, ft.total_tva)
    if tva is None or tva <= 0 or not prestations:
        return False
    taux = {t for lg in ft.lignes if not lg.nature.est_debours
            for t in [_dec(ctx, lg.taux_tva)] if t is not None and t > 0}
    if len(taux) != 1:
        return False
    r = taux.pop() / _CENT
    tol = ctx.tol.t_somme(2)
    bases = {total_ht - s_deb, total_ht}
    explique = any(abs(arrondi_centime(r * b) - tva) <= tol for b in bases if b > 0)
    return explique and abs(arrondi_centime(r * s_prest) - tva) > tol


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
            if Methode.derive in (lg.quantite.methode, lg.prix_unitaire.methode):
                # D-2311 : quantité implicite (« 1 » non imprimé) ou prix déduit : le produit n'est pas imprimé,
                # il n'y a pas d'identité à vérifier sur cette ligne.
                out.append(ctx.non_verifiable("D1", RaisonCode.valeur_absente, unite=unite, sous_controle="ligne",
                                              documents=[f.id], details={"motif": "facteur_non_imprime"}))
            else:
                out.append(_d1_resultat(
                    ctx, f, "ligne", unite, lg.montant_ht, q * pu, [lg.quantite, lg.prix_unitaire], tol.t_ligne(),
                    f"le montant de la ligne {_libelle_ligne(lg)}",
                    f"{format_nombre(q)} × {format_montant(pu)}", avec_montant=False, produit=True,
                ))
        taux, mtva = _dec(ctx, lg.taux_tva), _dec(ctx, lg.montant_tva)
        if m is not None and taux is not None and mtva is not None:
            assert lg.montant_ht is not None and lg.taux_tva is not None and lg.montant_tva is not None
            out.append(_d1_resultat(
                ctx, f, "tva_ligne", unite, lg.montant_tva, m * taux / _CENT, [lg.montant_ht, lg.taux_tva],
                tol.t_ligne(), f"la TVA de la ligne {_libelle_ligne(lg)}",
                f"{format_montant(m)} × {format_pourcentage(taux)}", avec_montant=False, produit=True,
            ))
    toutes_lisibles = len(montants) == len([lg for lg in ft.lignes if lg.montant_ht is not None])
    unite_f = cle_unite(ft=f.id)
    debours = [v for lg, v in montants if lg.nature.est_debours]
    prestations = [v for lg, v in montants if not lg.nature.est_debours]
    s_deb = _somme(v.decimal_signe() for v in debours)
    s_tout = _somme(v.decimal_signe() for _, v in montants)
    s_prest = _somme(v.decimal_signe() for v in prestations)

    td = ft.total_debours
    tht = ft.total_ht
    v_td = _dec(ctx, td) if td is not None and not td.est_reconstruite else None
    v_tht = _dec(ctx, tht)
    # Même écart positif sur deux totaux imprimés indépendants (total des débours et total HT débours
    # compris) : une ligne de débours non lue, pas une erreur d'addition (D-706).
    meme_ecart = (
        v_td is not None and v_tht is not None and debours
        and v_td - s_deb > tol.t_somme(len(debours))
        and abs((v_tht - s_tout) - (v_td - s_deb)) <= tol.t_somme(len(montants))
    )
    if toutes_lisibles and debours and v_td is not None and td is not None:
        out.append(_d1_resultat(
            ctx, f, "total_debours", unite_f, td, s_deb, debours, tol.t_somme(len(debours)),
            "le total des débours imprimé", f"somme des {len(debours)} lignes de débours", avec_montant=True,
            ligne_non_lue=bool(meme_ecart), somme_de_lignes=True,
        ))
    if toutes_lisibles and montants and v_tht is not None and tht is not None:
        alternatives = [s_prest] if debours and prestations else []
        out.append(_d1_resultat(
            ctx, f, "total_ht", unite_f, tht, s_tout, [v for _, v in montants], tol.t_somme(len(montants)),
            "le total HT imprimé", f"somme des {len(montants)} montants HT", avec_montant=True,
            alternatives=alternatives,
            ligne_non_lue=bool(meme_ecart) or _tva_confirme_total(ctx, ft, v_tht, s_deb, s_prest, prestations),
            somme_de_lignes=True,
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
        # Un acompte est une déduction, qu'il soit imprimé en positif ou précédé d'un signe moins.
        acompte = abs(_dec(ctx, ft.acomptes) or ZERO)
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
        if not dossier_principal(ctx, f.id):
            out.append(ctx.non_applicable("D1", RaisonCode.couvert_par_autre_controle, unite=cle_unite(ft=f.id),
                                          documents=[f.id], details={"motif": "facture_evaluee_dans_un_autre_dossier"}))
            continue
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
    details = {"grille": lr.grille.id, "prestations_hors_grille": lr.grille.prestations_hors_grille.value}
    commun = dict(unite=lr.unite, entrees={"montant": v}, attendu=ZERO, constate=m, ecart=arrondi_centime(m),
                  tolerance=tol, seuil_certitude=seuil, documents=[lr.facture.id], details=details)
    if m <= tol:
        return ctx.conforme(cid, **commun)
    if lr.ligne.libelle is None or not lr.ligne.libelle.valeur:
        # D-2306 : sans libellé lu, « aucun poste ne correspond » n'est pas établi (le poste se reconnaît au
        # libellé) : impossible de conclure, jamais conforme (P8).
        return ctx.non_verifiable(cid, RaisonCode.valeur_absente, unite=lr.unite, documents=[lr.facture.id],
                                  details={**details, "motif": "libelle_absent"})
    if renvoie_a_une_annexe(lr.ligne.libelle.valeur):
        # D-2306 : ligne qui reprend le total d'une annexe (« Suplidos según anexo ») dont le détail n'a pas été
        # ventilé : ce n'est pas une prestation hors grille ; sa nature n'est pas établie.
        return ctx.non_verifiable(cid, RaisonCode.valeur_absente, unite=lr.unite, documents=[lr.facture.id],
                                  details={**details, "motif": "renvoi_annexe"})
    cles = [x for x in (lr.ligne.libelle, v) if x is not None]
    raisons: list[RaisonCode] = []
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


def _copie_de(ctx: ControlContext, lr: LigneRoutee, vues: dict[tuple, int]) -> int | None:
    """D-2705 : rang de la première ligne identique (même facture, nature, libellé normalisé, montant et
    référence d'envoi, clé de D5) déjà évaluée, ``None`` pour la première. Une prestation imprimée deux fois
    n'est qu'une prestation hors grille ; la répétition relève de D5."""
    lg = lr.ligne
    m = _dec(ctx, _montant(ctx, lg))
    if m is None or lg.libelle is None or not lg.libelle.valeur:
        return None
    cle = (lr.facture.id, lg.nature.value, _cle(lg.libelle.valeur), m, _ref_ligne(ctx, lg))
    if cle in vues:
        return vues[cle]
    vues[cle] = lr.index
    return None


def _hors_grille_une_fois(ctx: ControlContext, cid: str, lr: LigneRoutee, vues: dict[tuple, int]
                          ) -> ResultatControle:
    premiere = _copie_de(ctx, lr, vues)
    if premiere is not None:
        return ctx.non_applicable(cid, RaisonCode.couvert_par_autre_controle, unite=lr.unite,
                                  documents=[lr.facture.id],
                                  details={"couvert_par": "D5", "copie_de_la_ligne": premiere})
    return _hors_grille(ctx, cid, lr)


@control("D2")
def d2_hors_grille(ctx: ControlContext) -> list[ResultatControle]:
    """D2 — Ligne de prestation sans poste dans la grille. ``interdites`` : ``ecart_certain`` possible ;
    ``tolerees`` : ``a_verifier``. Montant = HT de la ligne (TVA en ``montant_tva_associee``). Une ligne imprimée
    deux fois à l'identique n'est relevée qu'une fois (la répétition est l'objet de D5, D-2705)."""
    vues: dict[tuple, int] = {}
    return _par_controle(
        ctx, "D2", lambda lr: _hors_grille_une_fois(ctx, "D2", lr, vues) if lr.controle == "D2" else None)


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


@dataclass
class _Assiette:
    """Assiette d'un pourcentage de débours (D4, C6) : montant facturé, excédent constaté par C, valeurs lues,
    motifs de rattachement non établi ; unités C et factures dont viennent les débours (D-2801)."""

    montant: Decimal
    excedent: Decimal
    valeurs: list[ValeurSourcee]
    motifs: list[str]
    unites: list = field(default_factory=list)
    factures: list[Document] = field(default_factory=list)


def _assiette(ctx: ControlContext, f: Document, ligne: LigneFactureTransitaire, base: BasePourcentage | None
              ) -> _Assiette | None:
    """Assiette facturée d'un pourcentage de débours : débours des déclarations de la ligne (MRN cité sur la ligne,
    sinon déclarations couvertes par la facture)."""
    decs = ctx.declarations()
    unites = unites_c(ctx) if decs else []
    concernees = unites_pour_ligne(ctx, f, ligne, unites)
    if concernees:
        refs = {d.id: reference_declaration(ctx, d) for d in decs}
        excedents = [excedent_debours(u, refs, base) for u in concernees]
        excedent = _somme(e for e in excedents if e is not None)
        assiette = _somme(assiette_debours(u, base) for u in concernees)
        vals = [x.valeur for u in concernees for x in u.lignes if x.valeur is not None]
        motifs = ["debours_rattaches_sans_certitude"] if any(u.attribution_incertaine for u in concernees) else []
        factures = list({x.facture.id: x.facture for u in concernees for x in u.lignes}.values())
        return _Assiette(assiette, excedent, vals, motifs, list(concernees), factures)
    # Pas de déclaration rapprochée : débours de la facture elle-même (même MRN que la ligne s'il est cité),
    # sans correction. Sur une facture qui couvre plusieurs envois, ce choix des débours n'est pas établi
    # (MRN de ligne mal lu, déclaration absente) : jamais certain (D-2703).
    p_ligne = mrn_prefixe(ligne.mrn.valeur) if ligne.mrn is not None and ctx.utilisable(ligne.mrn) else None
    lignes = [lg for lg in f.ft.lignes if lg.nature.est_debours and (
        p_ligne is None or lg.mrn is None or not ctx.utilisable(lg.mrn) or mrn_prefixe(lg.mrn.valeur) == p_ligne)]
    if not lignes:
        return None
    exclure = {
        BasePourcentage.debours_hors_tva: {NatureLigne.debours_tva},
        BasePourcentage.droits: {n for n in NatureLigne if n is not NatureLigne.debours_droits},
    }.get(base, set()) if base is not None else set()
    vals = [v for lg in lignes if lg.nature not in exclure and (v := _montant(ctx, lg)) is not None]
    if any(_dec(ctx, v) is None for v in vals):
        return None
    motifs = ["debours_de_la_ligne_non_rattaches"] if facture_multi_envois(ctx, f) else []
    return _Assiette(_somme(v.decimal_signe() for v in vals), ZERO, vals, motifs, [], [f])


def _debours_complets(ctx: ControlContext, f: Document) -> bool:
    """Les lignes de débours lues de la facture sont toutes là (D-2703) : leur somme redonne le total des débours
    imprimé ; à défaut de ce total, la somme de toutes les lignes redonne le total HT imprimé. Sans l'une de ces
    preuves, une ligne de débours perdue (télécopie, rangée illisible, nature non reconnue) fausserait l'assiette."""
    lignes = f.ft.lignes
    tot = f.ft.total_debours
    if tot is not None and not tot.est_reconstruite and _dec(ctx, tot) is not None:
        vals = [_dec(ctx, _montant(ctx, lg)) for lg in lignes if lg.nature.est_debours]
        if not vals or any(v is None for v in vals):
            return False
        return abs(_somme(v for v in vals if v is not None) - (_dec(ctx, tot) or ZERO)) <= ctx.tol.t_somme(len(vals))
    ht = f.ft.total_ht
    if ht is not None and not ht.est_reconstruite and _dec(ctx, ht) is not None:
        vals = [_dec(ctx, _montant(ctx, lg)) for lg in lignes]
        if not vals or any(v is None for v in vals):
            return False
        if abs(_somme(v for v in vals if v is not None) - (_dec(ctx, ht) or ZERO)) > ctx.tol.t_somme(len(vals)):
            return False
        # D-2801 : Σ lignes = total HT prouve que toutes les lignes sont lues, pas qu'une ligne de débours n'a pas été
        # prise pour une prestation (libellé mal lu, nature non reconnue). Le total de TVA imprimé le prouve : une
        # ligne de débours (sans TVA) comptée comme prestation (taux normal) romprait Σ HT × taux = total TVA.
        return _tva_concorde(ctx, f)
    return False


def _tva_concorde(ctx: ControlContext, f: Document) -> bool:
    """Σ (HT × taux de la ligne, lu ou déduit selon la nature) = total de TVA imprimé (D-2801)."""
    total = _dec(ctx, f.ft.total_tva)
    if total is None or f.ft.total_tva is None or f.ft.total_tva.est_reconstruite:
        return False
    calcul = ZERO
    n = 0
    for lg in f.ft.lignes:
        ht = _dec(ctx, _montant(ctx, lg))
        taux = lg.taux_tva.decimal_ou_none() if lg.taux_tva is not None and ctx.utilisable(lg.taux_tva) else None
        if ht is None or (taux is None and not lg.nature.est_debours):
            return False
        if taux:
            calcul += ht * taux / _CENT
            n += 1
    return abs(calcul - total) <= ctx.tol.t_somme(n + 1)


#: Assiettes d'un pourcentage de débours essayées comme explication d'un FAF (D-2213).
_BASES_ALTERNATIVES = (
    BasePourcentage.debours_total,
    BasePourcentage.debours_hors_tva,
    BasePourcentage.droits,
    BasePourcentage.droits_et_autres_taxes,
)


def _assiettes_alternatives(ctx: ControlContext, f: Document, ligne: LigneFactureTransitaire,
                            factures: Sequence[Document] = ()) -> list[list[Decimal]]:
    """Autres assiettes plausibles d'un FAF, chacune comme liste de bases **par envoi** (D-2213) : débours
    refacturés des unités de la ligne selon chaque composante (avec ou sans l'excédent constaté), montants
    liquidés des déclarations, débours imprimés sur la facture elle-même. Le minimum et le maximum de la
    grille s'appliquent à la facture (somme) ou à chaque envoi (bases séparées)."""
    out: list[list[Decimal]] = []
    decs = ctx.declarations()
    unites = unites_c(ctx) if decs else []
    concernees = unites_pour_ligne(ctx, f, ligne, unites) if unites else []
    if concernees:
        refs = {d.id: reference_declaration(ctx, d) for d in decs}
        for b in _BASES_ALTERNATIVES:
            brutes = [assiette_debours(u, b) for u in concernees]
            out.append(brutes)
            exc = [excedent_debours(u, refs, b) for u in concernees]
            if all(e is not None for e in exc):
                out.append([x - (e or ZERO) for x, e in zip(brutes, exc, strict=True)])
        cats = {
            BasePourcentage.debours_total: list(CategorieTaxe),
            BasePourcentage.debours_hors_tva: [c for c in CategorieTaxe if c is not CategorieTaxe.tva],
            BasePourcentage.droits: [CategorieTaxe.droit],
        }
        vues: set[str] = set()
        liquides: dict[BasePourcentage, list[Decimal]] = {b: [] for b in cats}
        for u in concernees:
            for d in u.declarations:
                if d.id in vues:
                    continue
                vues.add(d.id)
                r = refs[d.id]
                for b, cs in cats.items():
                    liquides[b].append(_somme(r.liquide.get(c, ZERO) for c in cs))
        out.extend(v for v in liquides.values() if v)
    propres = [lg for lg in f.ft.lignes if lg.nature.est_debours and lg.montant_ht is not None]
    if propres and all(_dec(ctx, lg.montant_ht) is not None for lg in propres):
        for exclues in ((), (NatureLigne.debours_tva,)):
            out.append([_somme(lg.montant_ht.decimal_signe() for lg in propres
                               if lg.nature not in exclues and lg.montant_ht is not None)])
        out.append([_somme(lg.montant_ht.decimal_signe() for lg in propres
                           if lg.nature is NatureLigne.debours_droits and lg.montant_ht is not None)])
    # Total des débours imprimé (D-2703) : il reprend aussi une ligne de débours perdue à la lecture. Débours
    # portés par d'autres factures (facture de débours séparée, D-2801) : leurs totaux imprimés aussi.
    totaux: list[Decimal] = []
    tvas: list[Decimal] = []
    tva_complete = True
    for x in {d.id: d for d in (f, *factures)}.values():
        total = _dec(ctx, x.ft.total_debours)
        if total is None or (x is not f and x.ft.total_debours is not None and x.ft.total_debours.est_reconstruite):
            continue
        totaux.append(total)
        tva = [_dec(ctx, _montant(ctx, lg)) for lg in x.ft.lignes if lg.nature is NatureLigne.debours_tva]
        if tva and all(t is not None for t in tva):
            tvas.append(_somme(t for t in tva if t is not None))
        elif tva:
            tva_complete = False
        if x is f and total is not None:
            out.append([total])
            if tva and all(t is not None for t in tva):
                out.append([total - _somme(t for t in tva if t is not None)])
    if len(totaux) > 1:
        out.append([_somme(totaux)])
        if tva_complete and tvas:
            out.append([_somme(totaux) - _somme(tvas)])
    return out


def _faf_explique(ctx: ControlContext, p: PosteGrille, facture: Decimal, attendu: Decimal,
                  alternatives: Sequence[Sequence[Decimal]]) -> str | None:
    """Motif quand le FAF facturé est le calcul de la grille sur une autre assiette, avec le minimum ou le maximum
    appliqué par envoi, ou avec un arrondi à l'unité ; ``None`` sinon (D-2213)."""
    tol = ctx.tol.t_tarif()

    def egal(x: Decimal) -> bool:
        return abs(facture - x) <= tol or facture == arrondi_unite(x) or facture == x.to_integral_value(rounding=ROUND_CEILING)

    if facture != attendu and egal(attendu):
        return "arrondi_a_l_unite"
    assert p.pourcentage is not None
    for bases in alternatives:
        candidats = [borner(arrondi_centime(p.pourcentage * sum(bases, ZERO) / _CENT), p.minimum, p.maximum)]
        if len(bases) > 1:
            candidats.append(_somme(borner(arrondi_centime(p.pourcentage * x / _CENT), p.minimum, p.maximum)
                                    for x in bases))
        for c in candidats:
            if c != attendu and egal(c):
                return "autre_assiette_ou_bornes_par_envoi"
    return None


def _borne_faf(p: PosteGrille, base: Decimal) -> Decimal:
    assert p.pourcentage is not None
    return borner(arrondi_centime(p.pourcentage * base / _CENT), p.minimum, p.maximum)


def _lignes_faf(ctx: ControlContext, f: Document) -> int:
    """Nombre de lignes de FAF de la facture évaluées dans ce dossier."""
    return sum(1 for lg in f.ft.lignes
               if lg.nature is NatureLigne.frais_avance_fonds and ligne_evaluee_ici(ctx, f, lg))


def _d4_ambiguites(ctx: ControlContext, lr: LigneRoutee, p: PosteGrille, base: BasePourcentage | None,
                   a: _Assiette, attendu: Decimal) -> tuple[list[str], list[ValeurSourcee]]:
    """Situations où l'assiette (et donc l'attendu, ou le montant de l'écart) dépend d'une convention que les
    documents ne fixent pas (D-2801). Retourne les motifs et les débours TVA comprise de l'assiette (valeurs clés
    même quand l'attendu est borné : leur montant net n'est pas établi).

    1. ``faf_par_envoi_non_ventile`` : l'assiette couvre plusieurs déclarations, la ligne de FAF ne cite pas de
       MRN et la facture porte plusieurs lignes de FAF : chacune est calculée sur les débours d'un envoi, lequel
       n'est pas établi ;
    2. ``bornes_par_envoi_ou_par_facture`` : une seule ligne de FAF pour plusieurs déclarations ; le minimum ou le
       maximum appliqué par envoi donne un autre attendu qu'appliqué à la somme (ou la ventilation par envoi
       n'est pas connue alors que la grille a des bornes) ;
    3. ``avoirs_dans_les_debours`` : l'assiette contient des montants négatifs (lignes d'avoir mêlées au relevé)
       ou des avoirs de débours déjà reçus ; l'attendu calculé sur les débours bruts et sur les débours nets
       diffère."""
    motifs: list[str] = []
    tol = ctx.tol.t_tarif()
    decs = {d.id for u in a.unites for d in u.declarations}
    ventilee = lr.ligne.mrn is not None and ctx.utilisable(lr.ligne.mrn) and bool(mrn_prefixe(lr.ligne.mrn.valeur))
    if len(decs) > 1 and not ventilee:
        if _lignes_faf(ctx, lr.facture) > 1:
            motifs.append("faf_par_envoi_non_ventile")
        elif all(len(u.declarations) == 1 for u in a.unites):
            refs = {d.id: reference_declaration(ctx, d) for d in ctx.declarations()}
            par_envoi: dict[str, Decimal] = {}
            for u in a.unites:
                e = excedent_debours(u, refs, base) or ZERO
                k = u.declarations[0].id
                par_envoi[k] = par_envoi.get(k, ZERO) + assiette_debours(u, base) - e
            if abs(_somme(_borne_faf(p, x) for x in par_envoi.values()) - attendu) > tol:
                motifs.append("bornes_par_envoi_ou_par_facture")
        elif p.minimum is not None or p.maximum is not None:
            motifs.append("bornes_par_envoi_ou_par_facture")
    negatifs = [x for x in a.valeurs if (d := _dec(ctx, x)) is not None and d < 0]
    credits = _somme(c.montant for u in a.unites for c in u.credits)
    if negatifs or credits:
        retenue = a.montant - a.excedent
        brute = retenue + _somme(abs(x.decimal_signe()) for x in negatifs)
        nette = retenue - abs(credits)
        if any(abs(_borne_faf(p, x) - attendu) > tol for x in (brute, nette)):
            motifs.append("avoirs_dans_les_debours")
    marquees = [x for x in a.valeurs if RaisonCode.montant_tva_comprise in x.raisons]
    return motifs, marquees


def _grille_attestee(ctx: ControlContext, lr: LigneRoutee) -> str | None:
    """D-2802 : la grille appliquée est celle du transitaire du dossier ; l'émetteur lu sur la facture elle-même
    doit désigner ce transitaire (numéro de TVA ou nom). Sinon (émetteur illisible ou inconnu), le tarif comparé
    n'est pas établi : motif ``emetteur_non_identifie``."""
    em = lr.facture.ft.emetteur
    tva = em.tva.valeur if em.tva is not None and ctx.utilisable(em.tva) else None
    nom = em.nom.valeur if em.nom is not None and ctx.utilisable(em.nom) else None
    tid = identifier_transitaire(tva, nom, ctx.transitaires)
    if tid == lr.grille.transitaire_id:
        return None
    return "emetteur_non_identifie" if tid is None else "autre_transitaire"


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
        assiette, excedent, motifs = _somme(x.decimal_signe() for x in vals), ZERO, []
        a_obj: _Assiette | None = None
    elif base in (BasePourcentage.valeur_marchandise, BasePourcentage.autre):
        return ctx.non_verifiable(cid, RaisonCode.valeur_absente, unite=lr.unite, documents=[lr.facture.id],
                                  details={"motif": "assiette_non_calculable"})
    else:
        a_obj = _assiette(ctx, lr.facture, lr.ligne, base)
        if a_obj is None:
            return ctx.non_verifiable(cid, RaisonCode.valeur_absente, unite=lr.unite, documents=[lr.facture.id],
                                      details={"motif": "assiette_non_calculable"})
        assiette, excedent, vals, motifs = a_obj.montant, a_obj.excedent, a_obj.valeurs, a_obj.motifs
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
    raisons: list[RaisonCode] = []
    cles = [v]
    calcule = arrondi_centime(p.pourcentage * retenue / _CENT)
    if cid == "D4" and calcule == attendu:
        # Ni minimum ni maximum : l'attendu dépend de chaque débours lu de l'assiette (D-2213).
        cles += [x for x in vals if x is not v]
    if cid == "D4" and motifs:
        # D-2703 : débours de l'assiette rattachés à la ligne sans certitude (MRN de ligne mal lu, relevé).
        raisons.append(RaisonCode.attribution_non_univoque)
        details["attribution_non_univoque"] = motifs
    # D-2703, D-2801 : une ligne de débours non lue augmenterait l'assiette ; sans total qui prouve que toutes les
    # lignes sont lues, l'attendu n'est pas établi (sauf au maximum de la grille). La preuve est exigée de chaque
    # facture dont viennent les débours de l'assiette (facture de débours séparée de la facture de prestations),
    # pas seulement de la facture qui porte le FAF.
    factures_assiette = [lr.facture, *(x for x in (a_obj.factures if a_obj is not None else [])
                                       if x.id != lr.facture.id)]
    incompletes = [x.id for x in factures_assiette if not _debours_complets(ctx, x)]
    if cid == "D4" and (p.maximum is None or attendu < p.maximum) and incompletes:
        raisons.append(RaisonCode.valeur_absente)
        details["assiette_non_confirmee"] = "total_des_debours_non_retrouve"
        if any(i != lr.facture.id for i in incompletes):
            details["factures_de_debours_non_confirmees"] = [i for i in incompletes if i != lr.facture.id]
    if cid == "D4" and a_obj is not None:
        ambigu, marquees = _d4_ambiguites(ctx, lr, p, base, a_obj, attendu)
        cles += [x for x in marquees if x not in cles]
        if ambigu:
            raisons.append(RaisonCode.assiette_non_etablie)
            details["assiette_non_etablie"] = ambigu
    devise = lr.facture.ft.devise
    if cid == "D4" and devise is not None and not ctx.utilisable(devise):
        # D-2802 : devise de la facture lue mais illisible ; la grille est en euros (« EUR » non établi).
        raisons.append(RaisonCode.devise_incertaine)
    if cid == "D4":
        attestation = _grille_attestee(ctx, lr)
        if attestation is not None:
            raisons.append(RaisonCode.grille_non_attestee)
            details["grille_non_attestee"] = attestation
    if cid == "D4" and v.decimal_signe() - attendu - deduction > ctx.tol.t_tarif():
        motif = _faf_explique(ctx, p, v.decimal_signe() - deduction, attendu,
                              _assiettes_alternatives(ctx, lr.facture, lr.ligne, factures_assiette))
        if motif is not None:
            raisons.append(RaisonCode.assiette_alternative)
            details["assiette_alternative"] = motif
    return _comparer_tarif(ctx, cid, lr, attendu, calcul_txt, valeurs_cles=cles, deduction=deduction,
                           deduction_txt=deduction_txt, details=details, raisons=raisons)


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


#: Natures facturées par contenant, véhicule ou envoi physique : répétées légitimement pour plusieurs contenants.
_NATURES_PAR_CONTENANT = frozenset({
    NatureLigne.transport, NatureLigne.manutention, NatureLigne.magasinage, NatureLigne.surcharge,
})


def _ref_ligne(ctx: ControlContext, lg: LigneFactureTransitaire) -> str:
    """Référence d'envoi propre à la ligne (MRN, à défaut transport), vide si aucune."""
    if lg.mrn is not None and lg.mrn.valeur:
        return "mrn:" + mrn_prefixe(lg.mrn.valeur)
    if lg.ref_transport is not None and lg.ref_transport.valeur:
        return "transport:" + (norm_ref_transport(lg.ref_transport.valeur) or norm_ref(lg.ref_transport.valeur))
    return ""


def _envois_de_facture(ctx: ControlContext, f: Document) -> tuple[int, int]:
    """(nombre de MRN distincts, nombre de références de transport distinctes) cités par la facture. Deux
    lectures d'un même MRN qui ne diffèrent que par des confusions OCR comptent pour un."""
    mrns = {cle_confusion_ocr(mrn_prefixe(v.valeur)) for v in mrns_cites(ctx, f) if v.valeur}
    trs = [v for v in f.ft.refs_transport if v.valeur and ctx.utilisable(v)]
    trs += [lg.ref_transport for lg in f.ft.lignes if lg.ref_transport is not None and lg.ref_transport.valeur
            and ctx.utilisable(lg.ref_transport)]
    transports = {cle_confusion_ocr(norm_ref_transport(v.valeur) or norm_ref(v.valeur)) for v in trs if v.valeur}
    return len(mrns), len(transports)


def _d5_motifs(ctx: ControlContext, f: Document, g: Sequence[LigneRoutee], ref: str, copies: int,
               toutes_refs: int = 0) -> list[str]:
    """Pourquoi des lignes identiques ne prouvent pas une prestation facturée deux fois (D-2212) ; liste vide :
    la répétition est établie.

    1. Aucune référence d'envoi sur les lignes alors que la facture couvre plusieurs envois (plusieurs MRN,
       titres de transport ou déclarations) : une ligne par envoi est attendue.
    2. Prestation facturée par contenant (transport, manutention, magasinage, surcharge) sur une facture qui
       cite au moins autant de titres de transport que de lignes répétées : un par contenant ou livraison.
    3. Deux lignes consécutives sur deux pages : ligne reportée en haut de la page suivante.
    4. Le total HT imprimé reprend les lignes **sans** la répétition : elle n'est pas facturée (lecture).
    5. Facture de plusieurs envois : la référence d'envoi commune n'est lue sous la confiance de certitude que
       sur l'une des lignes (MRN de ligne mal lu ou recopié d'un intertitre) — D-2706.
    6. En plus de 1 ou 5 : les lignes identiques, toutes références confondues (``toutes_refs``), ne sont pas plus
       nombreuses que les envois cités — une par envoi (D-2706)."""
    motifs: list[str] = []
    n_mrn, n_tr = _envois_de_facture(ctx, f)
    n_decs = len(declarations_couvertes(ctx, f))
    plusieurs = n_mrn > 1 or n_tr > 1 or n_decs > 1
    if not ref and plusieurs:
        motifs.append("plusieurs_envois_sans_reference_sur_la_ligne")
    if ref and plusieurs:
        champ = "mrn" if ref.startswith("mrn:") else "ref_transport"
        refs = [getattr(lr.ligne, champ) for lr in g]
        if any(v is None or v.confiance < ctx.profil.c_min_certain for v in refs):
            motifs.append("reference_d_envoi_non_etablie")
    if (plusieurs and motifs and toutes_refs and toutes_refs <= max(n_mrn, n_tr, n_decs)):
        # Seulement si la référence commune n'est pas établie : deux lignes qui portent le même MRN lu sûrement
        # restent deux prestations du même envoi.
        motifs.append("une_ligne_par_envoi")
    natures = {lr.ligne.nature for lr in g}
    if natures <= _NATURES_PAR_CONTENANT and n_tr >= copies and not ref.startswith("transport:"):
        motifs.append("plusieurs_titres_de_transport")
    idx = sorted(lr.index for lr in g)
    lignes = f.ft.lignes
    for a, b in pairwise(idx):
        va, vb = _montant(ctx, lignes[a]), _montant(ctx, lignes[b])
        if b == a + 1 and va is not None and vb is not None and va.page and vb.page and va.page != vb.page:
            motifs.append("ligne_reportee_sur_la_page_suivante")
            break
    total = _dec(ctx, f.ft.total_ht)
    montants = [_dec(ctx, _montant(ctx, lg)) for lg in lignes]
    if total is not None and montants and all(m is not None for m in montants):
        somme = _somme(m for m in montants if m is not None)
        m0 = _dec(ctx, _montant(ctx, g[0].ligne)) or ZERO
        tol = ctx.tol.t_somme(len(montants))
        if abs(somme - total) > tol and abs(somme - m0 * (copies - 1) - total) <= tol:
            motifs.append("repetition_absente_du_total")
    return motifs


#: Longueur minimale d'un libellé dont deux lectures identiques se confirment (D-2316).
_LONGUEUR_LIBELLE_CONCORDANT = 8
#: Confiance minimale de chacune de ces lectures (D-2316).
C_LIBELLE_CONCORDANT = 0.8


def _libelles_concordants(
    ctx: ControlContext, libelles: Sequence[ValeurSourcee | None], vals: Sequence[ValeurSourcee]
) -> list[ValeurSourcee]:
    """D-2316 : les libellés des lignes répétées sont lus **indépendamment** à des endroits distincts de la
    facture ; s'ils sont identiques caractère pour caractère (texte brut, au moins 8 caractères), chacun lu au
    moins à 0,80, ces lectures se confirment l'une l'autre (une erreur d'OCR ne produit pas deux fois le même
    libellé) : la condition de confiance (§8.5.1 condition 3) est remplie pour ces libellés."""
    lus = [v for v in libelles if v is not None]
    if len(lus) < 2:
        return list(vals)
    textes = {(v.valeur_brute or v.valeur or "").strip() for v in lus}
    zones = {(v.page, v.zone.y0 if v.zone is not None else None) for v in lus}
    if (len(textes) != 1 or len(next(iter(textes))) < _LONGUEUR_LIBELLE_CONCORDANT or len(zones) != len(lus)
            or any(v.confiance < C_LIBELLE_CONCORDANT for v in lus)):
        return list(vals)
    seuil = ctx.profil.c_min_certain
    ids = {v.id for v in lus}
    return [v.model_copy(update={"confiance": max(v.confiance, seuil)}) if v.id in ids else v for v in vals]


@control("D5")
def d5_ligne_double(ctx: ControlContext) -> list[ResultatControle]:
    """D5 — Deux lignes de prestation de même nature, même libellé normalisé, même montant et même MRN ou
    référence de transport (ou aucune) sur une même facture. Les débours en double sont comptés par C.
    Une ligne annulée par une ligne opposée (même nature, même libellé, montant opposé) ne compte pas ;
    ``ecart_certain`` seulement si la répétition est établie (``_d5_motifs``, D-2212)."""
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
        sans_ref: dict[tuple, int] = {}
        for lr in lrs:
            lg = lr.ligne
            m = _dec(ctx, _montant(ctx, lg))
            if m is None or lg.libelle is None or not lg.libelle.valeur:
                continue
            groupes.setdefault((lg.nature.value, _cle(lg.libelle.valeur), m, _ref_ligne(ctx, lg)), []).append(lr)
            k = (lg.nature.value, _cle(lg.libelle.valeur), m)
            sans_ref[k] = sans_ref.get(k, 0) + 1
        doubles = []
        for (nature, cle, m, ref), g in groupes.items():
            # Ligne de correction : même nature, même libellé, montant opposé (une ligne annule l'autre).
            annulees = len(groupes.get((nature, cle, -m, ref), [])) if m > 0 else 0
            copies = len(g) - annulees
            if copies > 1:
                doubles.append((g, ref, copies))
        if not doubles:
            out.append(ctx.conforme("D5", unite=cle_unite(ft=fid), documents=[fid]))
            continue
        for g, ref, copies in doubles:
            unite = cle_unite(ft=fid, lignes=[lr.index for lr in g])
            vals = [x for lr in g for x in (lr.ligne.libelle, _montant(ctx, lr.ligne)) if x is not None]
            cles_d5 = _libelles_concordants(ctx, [lr.ligne.libelle for lr in g], vals)
            m = _montant(ctx, g[0].ligne)
            assert m is not None
            montant = m.decimal_signe() * (copies - 1)
            multiple = any(lr.poste is not None and lr.poste.mode in (ModePoste.unitaire, ModePoste.par_jour)
                           for lr in g)
            lg0 = g[0].ligne
            assert lg0.libelle is not None
            toutes = sans_ref.get((lg0.nature.value, _cle(lg0.libelle.valeur), m.decimal_signe()), 0)
            motifs = _d5_motifs(ctx, f, g, ref, copies, toutes)
            raisons = [RaisonCode.controle_signal_seulement] if multiple else []
            if motifs:
                raisons.append(RaisonCode.doublon_non_etabli)
            classement = ctx.classify(
                "D5", ecart=montant, tolerance=ctx.tol.t_tarif(), seuil_certitude=ctx.tol.s_tarif(),
                valeurs_cles=cles_d5, documents=[fid], montant=montant, raisons_supplementaires=raisons,
            )
            libelle = (
                f"{libelle_facture([f])} porte {len(g)} lignes identiques {_libelle_ligne(g[0].ligne)} de "
                f"{format_montant(m.decimal_signe())} chacune{_par(page_txt(vals))} (même nature, même libellé, "
                f"même montant, même référence d'envoi)."
            )
            details: dict = {"lignes": [lr.index for lr in g], "poste_quantite_multiple": multiple}
            if motifs:
                details["doublon_non_etabli"] = motifs
            out.append(ctx.constat(
                "D5", classement, unite=unite, libelle=libelle, prochaine_action=ACTION_D5, montant=montant,
                composante=Composante.prestation, documents=[fid],
                preuves=[preuve(_montant(ctx, lr.ligne), RolePreuve.valeur_b) for lr in g],
                entrees={f"ligne_{lr.index}": _montant(ctx, lr.ligne) for lr in g if _montant(ctx, lr.ligne)},
                attendu=m.decimal_signe(), constate=m.decimal_signe() * copies, ecart=arrondi_centime(montant),
                tolerance=ctx.tol.t_tarif(), seuil_certitude=ctx.tol.s_tarif(), details=details,
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


def _d7_ligne(ctx: ControlContext, lr: LigneRoutee, vues: dict[tuple, int]) -> ResultatControle:
    if lr.poste is None and not lr.ambigu:
        return _hors_grille_une_fois(ctx, "D7", lr, vues)
    return _d3_ligne(ctx, "D7", lr)


@control("D7")
def d7_surcharges(ctx: ControlContext) -> list[ResultatControle]:
    """D7 — Surcharge sans poste : comme D2 ; surcharge en pourcentage : ``pourcentage × assiette`` (débours
    selon ``base_pourcentage``, sinon lignes de transport de la facture) ; forfait/unitaire : comme D3."""
    vues: dict[tuple, int] = {}
    return _par_controle(ctx, "D7", lambda lr: _d7_ligne(ctx, lr, vues) if lr.controle == "D7" else None)


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
            if not lg.nature.est_debours or not ligne_evaluee_ici(ctx, f, lg):
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


def _nombre_articles(ctx: ControlContext, f: Document, ligne: LigneFactureTransitaire) -> tuple[
    int, list[ValeurSourcee], bool
] | None:
    """(nombre d'articles des déclarations de la ligne, valeurs, imprimé ?) : déclaration dont la ligne cite
    le MRN, à défaut déclarations couvertes par la facture (le forfait et ses articles inclus s'appliquent
    par déclaration)."""
    decs = declarations_de_ligne(ctx, f, ligne)
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
    na = _nombre_articles(ctx, lr.facture, lr.ligne)
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
