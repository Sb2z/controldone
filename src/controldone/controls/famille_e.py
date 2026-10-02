"""Famille E — Avoirs (SPEC §14).

Tous les contrôles E sont ``a_verifier`` par construction (Annexe A). Unité : l'avoir
(``cle_unite(av=<id>)``), sauf E4 (sous-contrôles par ligne ou total) et E6 (l'écart à recouvrer,
``cle_unite(ecart=<id>)``). L'imputation des avoirs suit §17.2
(``controldone.recouvrement.imputation``) ; la seconde réception d'un même avoir (E3) n'est jamais imputée.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from controldone.controls import _aides_befg as aides
from controldone.controls._aides_befg import ZERO, num
from controldone.controls.framework import (
    Confusion,
    ControlContext,
    arrondi_centime,
    cle_unite,
    control,
    preuve,
)
from controldone.formatage import format_montant, format_nombre
from controldone.model import (
    Composante,
    Document,
    NatureLigne,
    NatureMontant,
    RaisonCode,
    ResultatControle,
    RolePreuve,
    StatutEcart,
    TypeDocument,
    ValeurSourcee,
)
from controldone.normalize.refs import ref_compatibles, ref_transport_compatibles
from controldone.recouvrement.imputation import (
    EcartImputable,
    ResultatImputation,
    imputer_avoirs,
    lignes_credit_depuis_avoir,
)

__all__ = [
    "ACTION_E",
    "e1_rattachement",
    "e2_avoir_superieur_origine",
    "e3_avoir_recu_deux_fois",
    "e4_arithmetique_avoir",
    "e5_avoir_sans_ecart",
    "e6_avoir_partiel",
    "factures_origine",
    "imputation_du_dossier",
]

ACTION_E = "Rapprocher cet avoir de la facture d'origine et, si besoin, demander une précision au transitaire."
ACTION_E6 = "Relancer le transitaire pour le reste de l'écart non couvert par les avoirs reçus."


def _sans_avoir(ctx: ControlContext, cid: str) -> list[ResultatControle]:
    return [ctx.non_applicable(cid, RaisonCode.document_manquant, details={"motif": "aucun avoir dans le dossier"})]


def _u(av: Document) -> str:
    return cle_unite(av=av.id)


def _numero(av: Document) -> ValeurSourcee | None:
    return av.av.numero


# =====================================================================================================
# Recherche des factures d'origine
# =====================================================================================================


def _factures_candidates(ctx: ControlContext) -> list[tuple[Document, str | None]]:
    """Factures transitaires du dossier (dossier ``None``) et des autres dossiers du client."""
    out: list[tuple[Document, str | None]] = [(d, None) for d in ctx.factures_transitaires()]
    out += [(x.doc, x.dossier_id) for x in aides.documents_autres(ctx, TypeDocument.facture_transitaire)]
    return out


def factures_origine(ctx: ControlContext, av: Document) -> list[tuple[Document, str | None, ValeurSourcee]]:
    """Factures d'origine citées par l'avoir et retrouvées chez le même émetteur (``ref_compatibles``)."""
    e_av = aides.emetteur_de(ctx, av)
    out = []
    for ref in av.av.refs_facture_origine:
        if not ref.valeur:
            continue
        for ft, dos in _factures_candidates(ctx):
            if not aides.memes_emetteurs(e_av, aides.emetteur_de(ctx, ft)):
                continue
            if ref_compatibles(ref.valeur, aides.texte(ft.ft.numero)) and all(ft.id != x[0].id for x in out):
                out.append((ft, dos, ref))
    return out


# =====================================================================================================
# E1 — Rattachement de l'avoir
# =====================================================================================================


def _rattachement_secondaire(ctx: ControlContext, av: Document) -> tuple[str, ValeurSourcee] | None:
    """Rattachement par MRN, puis par référence de transport, aux documents du dossier."""
    prefixes_dossier = set(ctx.mrn_prefixes())
    for ft in ctx.factures_transitaires():
        prefixes_dossier |= set(aides.mrn_cites(ft))
    for p, v in aides.mrn_cites(av).items():
        if p in prefixes_dossier:
            return "le MRN", v
    refs_dossier: list[str] = list(ctx.dossier.cles.ref_transport)
    for ft in ctx.factures_transitaires():
        refs_dossier += [x.valeur for x in ft.ft.refs_transport if x.valeur]
    for fc in ctx.factures_commerciales():
        if fc.fc.ref_transport is not None and fc.fc.ref_transport.valeur:
            refs_dossier.append(fc.fc.ref_transport.valeur)
    vals = list(av.av.refs_transport) + [ln.ref_transport for ln in av.av.lignes if ln.ref_transport is not None]
    for v in vals:
        if v.valeur and any(ref_transport_compatibles(v.valeur, r) for r in refs_dossier):
            return "la référence de transport", v
    return None


def _e1_avoir(ctx: ControlContext, av: Document) -> ResultatControle:
    unite = _u(av)
    origines = factures_origine(ctx, av)
    details: dict = {"avoir_id": av.id}
    if origines:
        return ctx.conforme(
            "E1", unite=unite, documents=[av.id, *(ft.id for ft, dos, _ in origines if dos is None)],
            details={**details, "factures_origine": [ft.id for ft, _, _ in origines]},
            entrees={"ref_facture_origine": origines[0][2]},
        )
    second = _rattachement_secondaire(ctx, av)
    num_v = _numero(av)
    cles = [v for v in (num_v, second[1] if second else None) if v is not None]
    classement = ctx.classify("E1", ecart=None, tolerance=None, seuil_certitude=None, valeurs_cles=cles,
                              raisons_supplementaires=[RaisonCode.rattachement_faible])
    cite = [x.valeur for x in av.av.refs_facture_origine if x.valeur]
    debut = (f"{aides.maj(aides.ref_document(av, num_v))} cite la facture d'origine {', '.join(cite)}, qui n'a pas "
             f"été retrouvée chez le même émetteur" if cite
             else f"{aides.maj(aides.ref_document(av, num_v))} ne cite aucune facture d'origine")
    if second is not None:
        quoi, v = second
        libelle = f"{debut} ; il est rattaché au dossier seulement par {quoi} {v.valeur} (page {v.page})."
        details["rattachement"] = "mrn" if quoi == "le MRN" else "transport"
    else:
        libelle = f"{debut} et ne partage ni MRN ni référence de transport avec les documents du dossier : avoir non rattaché."
        details["rattachement"] = "aucun"
    preuves = [preuve(v, RolePreuve.contexte) for v in cles] or [preuve(None, RolePreuve.contexte,
                                                                        calcul="aucune référence lue")]
    return ctx.constat("E1", classement, unite=unite, libelle=libelle, prochaine_action=ACTION_E,
                       preuves=preuves, documents=[av.id], details=details)


@control("E1")
def e1_rattachement(ctx: ControlContext) -> list[ResultatControle]:
    """E1 — L'avoir cite une facture d'origine trouvée chez le même émetteur -> ``conforme`` ; sinon
    rattachement par MRN ou référence de transport -> ``a_verifier`` (``rattachement_faible``) ; aucun ->
    ``a_verifier`` « avoir non rattaché »."""
    avoirs = ctx.avoirs()
    if not avoirs:
        return _sans_avoir(ctx, "E1")
    return [_e1_avoir(ctx, av) for av in avoirs]


# =====================================================================================================
# E2 — Avoir supérieur à l'origine
# =====================================================================================================


def _groupe(nature: NatureLigne, fusion_debours: bool) -> str:
    if nature.est_debours:
        return "debours" if fusion_debours else (nature.composante or Composante.droit).value
    return nature.value


_LIBELLE_GROUPE = {
    "debours": "débours (droits et taxes)",
    "droit": "droits de douane refacturés",
    "autre_taxe": "autres taxes refacturées",
    "tva": "TVA à l'importation refacturée",
    "forfait_petits_envois": "forfait petits envois refacturé",
}


def _sommes_par_groupe(docs: Iterable[Document], fusion: bool) -> tuple[dict[str, Decimal], int, bool]:
    """Σ montants HT par groupe de nature ; nombre de lignes ; toutes lisibles ?"""
    out: dict[str, Decimal] = {}
    n, ok = 0, True
    for d in docs:
        for ln in aides.lignes_ft(d):
            v = num(aides.montant_ht(ln))
            if v is None:
                ok = False
                continue
            g = _groupe(ln.nature, fusion)
            out[g] = out.get(g, ZERO) + abs(v)
            n += 1
    return out, n, ok


def _e2_avoir(ctx: ControlContext, av: Document, doubles: set[str]) -> ResultatControle:
    unite = _u(av)
    origines = factures_origine(ctx, av)
    if not origines:
        return ctx.non_verifiable("E2", RaisonCode.document_manquant, unite=unite, documents=[av.id],
                                  details={"motif": "facture d'origine non retrouvée"})
    ids_origine = {ft.id for ft, _, _ in origines}
    numeros = [aides.texte(ft.ft.numero) for ft, _, _ in origines]
    # Tous les avoirs (ici et ailleurs, hors secondes réceptions) qui citent l'une de ces factures.
    pool = [d for d in ctx.avoirs() if d.id not in doubles]
    pool += [x.doc for x in aides.documents_autres(ctx, TypeDocument.avoir)]
    avoirs = [d for d in pool if any(ref_compatibles(r.valeur, n) for r in d.av.refs_facture_origine
                                     if r.valeur for n in numeros if n)]
    if av.id not in {d.id for d in avoirs}:
        avoirs.append(av)
    fts = [ft for ft, _, _ in origines]
    fusion = any(ln.nature is NatureLigne.debours_combines for d in [*avoirs, *fts] for ln in aides.lignes_ft(d))
    credite, n_av, ok_av = _sommes_par_groupe(avoirs, fusion)
    facture, n_ft, ok_ft = _sommes_par_groupe(fts, fusion)
    details: dict = {"avoirs": sorted(d.id for d in avoirs), "factures_origine": sorted(ids_origine)}
    if not credite:
        # Avoir sans ventilation : comparaison des totaux HT.
        tot_av = sum((num(d.av.total_credite_ht) or ZERO for d in avoirs), ZERO)
        tot_ft = sum((num(ft.ft.total_ht) or ZERO for ft in fts), ZERO)
        if not tot_av or not tot_ft:
            return ctx.non_verifiable("E2", RaisonCode.valeur_absente, unite=unite, documents=[av.id], details=details)
        credite, facture, n_av, n_ft = {"total": tot_av}, {"total": tot_ft}, len(avoirs), len(fts)
    elif not (ok_av and ok_ft):
        return ctx.non_verifiable("E2", RaisonCode.valeur_absente, unite=unite, documents=[av.id], details=details)
    t = ctx.tol.t_somme(n_av + n_ft)
    depassements = {g: credite[g] - facture.get(g, ZERO) for g in sorted(credite)
                    if credite[g] > facture.get(g, ZERO) + t}
    ecart = max(depassements.values(), default=ZERO)
    commun = dict(unite=unite, attendu=None, constate=None, ecart=arrondi_centime(ecart), tolerance=t,
                  documents=[av.id], details={**details, "groupes": {g: str(arrondi_centime(x))
                                                                      for g, x in depassements.items()}})
    if not depassements:
        return ctx.conforme("E2", **commun)
    vals = [aides.montant_ht(ln) for d in avoirs for ln in aides.lignes_ft(d)]
    classement = ctx.classify("E2", ecart=ecart, tolerance=t, seuil_certitude=None,
                              valeurs_cles=[v for v in vals if v is not None])
    morceaux = [
        f"{_LIBELLE_GROUPE.get(g, 'total HT' if g == 'total' else 'lignes « ' + g.replace('_', ' ') + ' »')} : "
        f"{format_montant(arrondi_centime(credite[g]), 'EUR')} crédités pour "
        f"{format_montant(arrondi_centime(facture.get(g, ZERO)), 'EUR')} facturés"
        for g in depassements
    ]
    libelle = (
        f"Les avoirs reçus sur la facture d'origine {', '.join(n for n in numeros if n)} dépassent le montant "
        f"facturé ({' ; '.join(morceaux)})."
    )
    preuves = [preuve(v, RolePreuve.valeur_b) for v in vals if v is not None]
    preuves += [preuve(aides.montant_ht(ln), RolePreuve.valeur_a) for ft in fts for ln in ft.ft.lignes
                if aides.montant_ht(ln) is not None]
    autres = sorted({dos for _, dos, _ in origines if dos})
    return ctx.constat("E2", classement, libelle=libelle, prochaine_action=ACTION_E, preuves=preuves,
                       autres_dossiers=autres, **commun)


@control("E2")
def e2_avoir_superieur_origine(ctx: ControlContext) -> list[ResultatControle]:
    """E2 — Pour chaque nature (débours regroupés si une ligne combinée figure d'un côté), Σ avoirs reçus
    sur la facture d'origine ≤ montant facturé + ``T_SOMME``. ``a_verifier`` uniquement."""
    avoirs = ctx.avoirs()
    if not avoirs:
        return _sans_avoir(ctx, "E2")
    doubles = set(aides.avoirs_doubles(ctx))
    return [_e2_avoir(ctx, av, doubles) for av in avoirs]


# =====================================================================================================
# E3 — Avoir reçu deux fois
# =====================================================================================================


@control("E3")
def e3_avoir_recu_deux_fois(ctx: ControlContext) -> list[ResultatControle]:
    """E3 — Deux avoirs de même émetteur et même numéro normalisé, ou de même montant total et même facture
    d'origine à moins de 7 jours d'écart. Le constat est porté par la **seconde** réception (date, numéro,
    identifiant), qui n'est pas imputée. ``a_verifier`` uniquement."""
    avoirs = ctx.avoirs()
    if not avoirs:
        return _sans_avoir(ctx, "E3")
    doubles = aides.avoirs_doubles(ctx)
    out = []
    for av in avoirs:
        unite = _u(av)
        d = doubles.get(av.id)
        if d is None:
            out.append(ctx.conforme("E3", unite=unite, documents=[av.id]))
            continue
        classement = ctx.classify("E3", ecart=None, tolerance=None, seuil_certitude=None,
                                  valeurs_cles=[v for v in (_numero(av), _numero(d.premier)) if v is not None])
        ou = "dans ce dossier" if d.dossier_premier is None else f"dans le dossier {d.dossier_premier}"
        motif = ("même émetteur et même numéro" if d.motif == "meme_numero"
                 else "même montant total et même facture d'origine, à moins de 7 jours d'écart")
        libelle = (
            f"{aides.maj(aides.ref_document(av, _numero(av)))} correspond à {aides.ref_document(d.premier, _numero(d.premier))} "
            f"déjà reçu {ou} ({motif}) ; il n'est pas imputé une seconde fois."
        )
        preuves = [preuve(v, RolePreuve.valeur_b) for v in (_numero(av),) if v is not None]
        preuves += [preuve(v, RolePreuve.valeur_a) for v in (_numero(d.premier),) if v is not None]
        out.append(ctx.constat(
            "E3", classement, unite=unite, libelle=libelle, prochaine_action=ACTION_E, preuves=preuves,
            documents=[av.id], autres_dossiers=[d.dossier_premier] if d.dossier_premier else [],
            details={"avoir_id": av.id, "premier": d.premier.id, "motif": d.motif},
        ))
    return out


# =====================================================================================================
# E4 — Arithmétique interne de l'avoir
# =====================================================================================================


def _e4_comparer(
    ctx: ControlContext, av: Document, *, sous: str, unite: str, imprime: ValeurSourcee, v_imprime: Decimal,
    calcul: Decimal, tolerance: Decimal, operandes: list[ValeurSourcee], quoi: str, calcul_txt: str,
) -> ResultatControle:
    ecart = v_imprime - calcul
    commun = dict(unite=unite, sous_controle=sous, entrees={"imprime": imprime}, attendu=arrondi_centime(calcul),
                  constate=v_imprime, ecart=arrondi_centime(ecart), tolerance=tolerance,
                  seuil_certitude=ctx.tol.s_arith(), documents=[av.id], details={"avoir_id": av.id})
    if abs(ecart) <= tolerance:
        return ctx.conforme("E4", **commun)
    classement = ctx.classify("E4", ecart=ecart, tolerance=tolerance, seuil_certitude=ctx.tol.s_arith(),
                              valeurs_cles=[imprime, *operandes],
                              confusion=[Confusion(imprime, autre=calcul, tolerance=tolerance)])
    libelle = (
        f"Sur {aides.ref_document(av, imprime)}, {quoi} imprimé ({format_montant(v_imprime, 'EUR')}) diffère du "
        f"calcul à partir des montants imprimés ({calcul_txt})."
    )
    return ctx.constat("E4", classement, libelle=libelle, prochaine_action=ACTION_E,
                       preuves=[preuve(imprime, RolePreuve.valeur_b),
                                *(preuve(v, RolePreuve.operande) for v in operandes),
                                preuve(None, RolePreuve.valeur_a, calcul=calcul_txt)],
                       **commun)


def _e4_avoir(ctx: ControlContext, av: Document) -> list[ResultatControle]:
    c = av.av
    tol = ctx.tol
    out: list[ResultatControle] = []
    for i, ln in enumerate(c.lignes):
        q, pu, ht = ln.quantite, ln.prix_unitaire, ln.montant_ht
        if q is not None and pu is not None and ht is not None:
            if all(aides.utilisable_num(ctx, v) for v in (q, pu, ht)):
                vq, vpu, vht = num(q) or ZERO, num(pu) or ZERO, num(ht) or ZERO
                txt = f"{format_nombre(vq)} × {format_montant(vpu, 'EUR')} = {format_montant(arrondi_centime(vq * vpu), 'EUR')}"
                out.append(_e4_comparer(ctx, av, sous="ligne", unite=cle_unite(av=av.id, ligne=i), imprime=ht,
                                        v_imprime=vht, calcul=vq * vpu, tolerance=tol.t_ligne(), operandes=[q, pu],
                                        quoi=f"le montant HT de la ligne {i + 1}", calcul_txt=txt))
            else:
                out.append(ctx.non_verifiable("E4", RaisonCode.valeur_absente, unite=cle_unite(av=av.id, ligne=i),
                                              sous_controle="ligne", documents=[av.id]))
        tx, tva = ln.taux_tva, ln.montant_tva
        if ht is not None and tx is not None and tva is not None:
            if all(aides.utilisable_num(ctx, v) for v in (ht, tx, tva)):
                vht, vtx, vtva = num(ht) or ZERO, num(tx) or ZERO, num(tva) or ZERO
                calc = vht * vtx / Decimal(100)
                txt = f"{format_montant(vht, 'EUR')} × {format_nombre(vtx)} % = {format_montant(arrondi_centime(calc), 'EUR')}"
                out.append(_e4_comparer(ctx, av, sous="tva_ligne", unite=cle_unite(av=av.id, ligne=i), imprime=tva,
                                        v_imprime=vtva, calcul=calc, tolerance=tol.t_ligne(), operandes=[ht, tx],
                                        quoi=f"le montant de TVA de la ligne {i + 1}", calcul_txt=txt))
            else:
                out.append(ctx.non_verifiable("E4", RaisonCode.valeur_absente, unite=cle_unite(av=av.id, ligne=i),
                                              sous_controle="tva_ligne", documents=[av.id]))
    # total_ht : Σ montants HT des lignes contre le total crédité HT imprimé.
    hts = [ln.montant_ht for ln in c.lignes]
    if c.total_credite_ht is not None and hts:
        u = cle_unite(av=av.id)
        if aides.utilisable_num(ctx, c.total_credite_ht) and all(aides.utilisable_num(ctx, v) for v in hts):
            ops = [v for v in hts if v is not None]
            s = sum((num(v) or ZERO for v in ops), ZERO)
            out.append(_e4_comparer(
                ctx, av, sous="total_ht", unite=u, imprime=c.total_credite_ht, v_imprime=num(c.total_credite_ht) or ZERO,
                calcul=s, tolerance=tol.t_somme(len(ops)), operandes=ops, quoi="le total HT crédité",
                calcul_txt=f"somme des {len(ops)} lignes = {format_montant(arrondi_centime(s), 'EUR')}",
            ))
        else:
            out.append(ctx.non_verifiable("E4", RaisonCode.valeur_absente, unite=u, sous_controle="total_ht",
                                          documents=[av.id]))
    # total_ttc : total HT + total TVA = total TTC.
    if c.total_credite_ttc is not None and c.total_credite_ht is not None and c.total_tva is not None:
        u = cle_unite(av=av.id)
        vals = (c.total_credite_ht, c.total_tva, c.total_credite_ttc)
        if all(aides.utilisable_num(ctx, v) for v in vals):
            s = (num(c.total_credite_ht) or ZERO) + (num(c.total_tva) or ZERO)
            out.append(_e4_comparer(
                ctx, av, sous="total_ttc", unite=u, imprime=c.total_credite_ttc,
                v_imprime=num(c.total_credite_ttc) or ZERO, calcul=s, tolerance=tol.t_somme(2),
                operandes=[c.total_credite_ht, c.total_tva], quoi="le total TTC crédité",
                calcul_txt=f"total HT + total TVA = {format_montant(arrondi_centime(s), 'EUR')}",
            ))
        else:
            out.append(ctx.non_verifiable("E4", RaisonCode.valeur_absente, unite=u, sous_controle="total_ttc",
                                          documents=[av.id]))
    return out or [ctx.non_applicable("E4", RaisonCode.valeur_absente, unite=_u(av), documents=[av.id])]


@control("E4")
def e4_arithmetique_avoir(ctx: ControlContext) -> list[ResultatControle]:
    """E4 — Mêmes sous-contrôles que D1 appliqués à l'avoir (``ligne``, ``tva_ligne``, ``total_ht``,
    ``total_ttc``). ``a_verifier`` uniquement ; montant : aucun (un avoir mal additionné est signalé)."""
    avoirs = ctx.avoirs()
    if not avoirs:
        return _sans_avoir(ctx, "E4")
    return [r for av in avoirs for r in _e4_avoir(ctx, av)]


# =====================================================================================================
# Imputation du dossier (§17.2) — utilisée par E5 et E6
# =====================================================================================================


def _composante_constat(r: ResultatControle) -> Composante | None:
    c = r.constat
    if c is None:
        return None
    if c.composante is not None and c.composante is not Composante.valeur:
        return c.composante
    return {"C1": Composante.droit, "C2": Composante.autre_taxe, "C3": Composante.tva,
            "C4": Composante.tva}.get(r.controle_id)


def _ecarts_du_dossier(ctx: ControlContext) -> list[tuple[EcartImputable, str | None]]:
    """Écarts candidats : registre de recouvrement (reste recalculé depuis le montant initial, D-3xx) et
    constats ``recouvrable`` positifs des contrôles déjà exécutés (C, D). Retourne (écart, constat_id)."""
    out: list[tuple[EcartImputable, str | None]] = []
    vus: set[str] = set()
    for e in ctx.ecarts_recouvrement:
        if e.statut not in (StatutEcart.ouvert, StatutEcart.reclame, StatutEcart.partiellement_credite,
                            StatutEcart.conteste):
            continue
        ft = ctx.document(e.facture_transitaire_id) if e.facture_transitaire_id else None
        facture_ref = aides.texte(ft.ft.numero) if ft is not None and ft.type is TypeDocument.facture_transitaire else None
        emetteur = e.transitaire_id
        if ft is not None and ft.type is TypeDocument.facture_transitaire:
            emetteur = aides.emetteur_de(ctx, ft) or emetteur
        out.append((EcartImputable.depuis_ecart(e, facture_ref=facture_ref, emetteur=emetteur,
                                                reste=e.montant_initial), e.constat_id))
        vus.add(e.constat_id)
    for r in ctx.anterieurs():
        c = r.constat
        if c is None or c.nature_montant is not NatureMontant.recouvrable or c.id in vus:
            continue
        m = c.montant_brut if c.montant_brut is not None else c.montant_en_jeu
        comp = _composante_constat(r)
        if m is None or m <= 0 or comp is None:
            continue
        docs = [ctx.document(i) for i in c.documents_concernes]
        fts = [d for d in docs if d is not None and d.type is TypeDocument.facture_transitaire]
        decs = [d for d in docs if d is not None and d.type is TypeDocument.declaration]
        if len(fts) != 1:
            continue
        ft = fts[0]
        mrn = aides.texte(decs[0].dec.mrn) if len(decs) == 1 else None
        out.append((EcartImputable(
            id=f"constat:{c.id}", composante=comp, reste=m, emetteur=aides.emetteur_de(ctx, ft),
            constat_id=c.id, facture_ref=aides.texte(ft.ft.numero), mrn=mrn,
        ), c.id))
        vus.add(c.id)
    return out


def imputation_du_dossier(ctx: ControlContext) -> tuple[ResultatImputation, list[tuple[EcartImputable, str | None]]]:
    """Imputation §17.2 des avoirs du dossier (hors secondes réceptions, E3) sur les écarts candidats."""
    avoirs = aides.avoirs_imputables(ctx)
    lignes = [lc for a in avoirs for lc in lignes_credit_depuis_avoir(a, emetteur=aides.emetteur_de(ctx, a))]
    ecarts = _ecarts_du_dossier(ctx)
    return imputer_avoirs(lignes, [e for e, _ in ecarts], t_debours=ctx.tol.t_debours(0)), ecarts


# =====================================================================================================
# E5 — Avoir sans écart ouvert correspondant
# =====================================================================================================


@control("E5")
def e5_avoir_sans_ecart(ctx: ControlContext) -> list[ResultatControle]:
    """E5 — Après imputation (§17.2), un reliquat d'avoir > ``T_SOMME`` ne correspond à aucun écart ouvert.
    ``a_verifier`` uniquement (information : l'avoir peut régler un sujet non détecté)."""
    avoirs = ctx.avoirs()
    if not avoirs:
        return _sans_avoir(ctx, "E5")
    doubles = aides.avoirs_doubles(ctx)
    res, _ = imputation_du_dossier(ctx)
    out = []
    for av in avoirs:
        unite = _u(av)
        if av.id in doubles:
            out.append(ctx.non_applicable("E5", RaisonCode.couvert_par_autre_controle, unite=unite,
                                          documents=[av.id], details={"couvert_par": "E3"}))
            continue
        lignes = lignes_credit_depuis_avoir(av)
        if not lignes:
            out.append(ctx.non_verifiable("E5", RaisonCode.valeur_absente, unite=unite, documents=[av.id]))
            continue
        reliquat = res.reliquat_avoir(av.id)
        impute = arrondi_centime(sum((i.montant for i in res.imputations_avoir(av.id)), ZERO))
        t = ctx.tol.t_somme(len(lignes))
        commun = dict(unite=unite, attendu=impute, constate=arrondi_centime(sum((lc.montant for lc in lignes), ZERO)),
                      ecart=reliquat, tolerance=t, documents=[av.id],
                      details={"avoir_id": av.id, "impute": str(impute), "reliquat": str(reliquat),
                               "imputations": [(i.ecart_id, str(i.montant), i.palier)
                                               for i in res.imputations_avoir(av.id)]})
        if reliquat <= t:
            out.append(ctx.conforme("E5", **commun))
            continue
        vals = [aides.montant_ht(ln) for ln in av.av.lignes]
        vals = [v for v in vals if v is not None] or [v for v in (av.av.total_credite_ht,) if v is not None]
        classement = ctx.classify("E5", ecart=reliquat, tolerance=t, seuil_certitude=None, valeurs_cles=vals)
        sans_vent = any(lc.nature is None for lc in lignes)
        libelle = (
            f"Après rapprochement avec les écarts relevés, {aides.ref_document(av, _numero(av))} laisse un reliquat de "
            f"{format_montant(reliquat, 'EUR')} (sur {format_montant(commun['constate'], 'EUR')} crédités) qui ne "
            f"correspond à aucun écart ouvert"
            + (" ; l'avoir n'est pas ventilé par nature." if sans_vent else ".")
        )
        out.append(ctx.constat("E5", classement, libelle=libelle,
                               prochaine_action="Identifier le sujet réglé par cet avoir auprès du transitaire.",
                               preuves=[preuve(v, RolePreuve.valeur_b) for v in vals], **commun))
    return out


# =====================================================================================================
# E6 — Avoir partiel
# =====================================================================================================


_RECLAMES = (StatutEcart.reclame, StatutEcart.partiellement_credite, StatutEcart.conteste)


@control("E6")
def e6_avoir_partiel(ctx: ControlContext) -> list[ResultatControle]:
    """E6 — Un écart **réclamé** (registre de recouvrement) n'est couvert que partiellement par les avoirs
    imputés du dossier ; reste à recouvrer > ``T_DEBOURS``. ``a_verifier`` ; montant ``recouvrable`` = reste.

    Ce constat remplace le montant de l'écart d'origine dans les totaux : ``details.remplace_constat_id``
    désigne le constat d'origine (à exclure des totaux par le consommateur, D-3xx)."""
    avoirs = ctx.avoirs()
    if not avoirs:
        return _sans_avoir(ctx, "E6")
    res, ecarts = imputation_du_dossier(ctx)
    registre = {e.id: e for e in ctx.ecarts_recouvrement}
    out = []
    t = ctx.tol.t_debours(0)
    for e, constat_id in ecarts:
        origine = registre.get(e.id)
        if origine is None or origine.statut not in _RECLAMES:
            continue
        credit = res.credit_pour(e.id)
        if credit <= 0:
            continue
        etat = res.ecarts[e.id]
        unite = cle_unite(ecart=e.id)
        imputs = [i for i in res.imputations if i.ecart_id == e.id]
        av_ids = list(dict.fromkeys(i.avoir_id for i in imputs))
        commun = dict(unite=unite, attendu=etat.montant_initial, constate=credit, ecart=etat.reste, tolerance=t,
                      documents=av_ids,
                      details={"ecart_id": e.id, "remplace_constat_id": constat_id, "credite": str(credit),
                               "reste": str(etat.reste), "avoirs": av_ids})
        if etat.reste <= t:
            out.append(ctx.conforme("E6", **commun))
            continue
        classement = ctx.classify("E6", ecart=etat.reste, tolerance=t, seuil_certitude=None, valeurs_cles=[],
                                  montant=etat.reste)
        av_docs = [d for d in (ctx.document(i) for i in av_ids) if d is not None]
        libelle = (
            f"L'écart réclamé de {format_montant(etat.montant_initial, 'EUR')} "
            f"({(origine.composante.value).replace('_', ' ')}"
            + (f", MRN {origine.mrn}" if origine.mrn else "")
            + f") n'est couvert qu'à hauteur de {format_montant(credit, 'EUR')} par "
            + ", ".join(aides.ref_document(d, _numero(d)) for d in av_docs)
            + f" ; reste {format_montant(etat.reste, 'EUR')}."
        )
        preuves = [preuve(aides.montant_ht(d.av.lignes[i.ligne]), RolePreuve.valeur_b)
                   for i in imputs for d in av_docs if d.id == i.avoir_id and i.ligne is not None]
        out.append(ctx.constat("E6", classement, libelle=libelle, prochaine_action=ACTION_E6, montant=etat.reste,
                               montant_brut=etat.reste, composante=origine.composante, preuves=preuves, **commun))
    return out or [ctx.non_applicable("E6", RaisonCode.valeur_absente,
                                      details={"motif": "aucun écart réclamé couvert par un avoir du dossier"})]

