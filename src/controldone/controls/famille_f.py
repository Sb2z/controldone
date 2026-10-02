"""Famille F — Doublons entre dossiers (SPEC §15).

Recherche dans les **autres dossiers du même client** fournis par le contexte (``ctx.autres_dossiers``,
jamais entre clients), dans la fenêtre du profil (``fenetre_doublons_mois``, 24 mois par défaut ; une date
illisible ne fait pas sortir de la fenêtre). Un constat est porté par l'occurrence **la plus récente**
(date, puis numéro, puis identifiant) et cite l'autre dossier (``autres_dossiers``) et son document
(preuve). Le dossier qui porte l'occurrence la plus ancienne produit un résultat ``non_applicable``
(``couvert_par_autre_controle``), pour qu'un même doublon ne soit compté qu'une fois.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from controldone.controls import _aides_befg as aides
from controldone.controls._aides_befg import ZERO, DocAilleurs, num
from controldone.controls.framework import (
    ControlContext,
    arrondi_centime,
    cle_unite,
    control,
    eur_par_devise,
    montant_ecart_documentaire,
    preuve,
)
from controldone.formatage import format_montant
from controldone.model import (
    Composante,
    Document,
    RaisonCode,
    ResultatControle,
    RolePreuve,
    TypeDocument,
    ValeurSourcee,
)
from controldone.normalize.refs import mrn_prefixe, norm_ref, ref_compatibles, ref_transport_egales

__all__ = [
    "ACTION_F",
    "f1_document_en_double",
    "f2_numero_reutilise",
    "f3_declaration_refacturee_deux_fois",
    "f4_prestation_facturee_deux_fois",
    "f5_facture_sur_plusieurs_declarations",
]

ACTION_F = "Comparer les deux documents et, si le doublon est confirmé, demander un avoir au transitaire."
ACTION_F_INFO = "Vérifier qu'un seul exemplaire de ce document est pris en compte."
ACTION_F5 = (
    "Vérifier auprès du déclarant si la facture commerciale correspond à des envois partiels."
)


@dataclass(frozen=True, slots=True)
class _Occ:
    """Occurrence d'un document : ici (``dossier_id is None``) ou dans un autre dossier."""

    doc: Document
    dossier_id: str | None
    lien_solide: bool = True


def _pool(ctx: ControlContext, type_document: TypeDocument) -> list[_Occ]:
    ici = [_Occ(d, None) for d in ctx.documents_par_role(_ROLE[type_document]) if d.type is type_document and d.champs]
    ailleurs = [_Occ(x.doc, x.dossier_id, x.lien_solide) for x in aides.documents_autres(ctx, type_document)]
    return ici + ailleurs


_ROLE = {
    TypeDocument.facture_transitaire: "facture_transitaire",
    TypeDocument.avoir: "avoir",
    TypeDocument.declaration: "declaration",
    TypeDocument.facture_commerciale: "facture_commerciale",
}


def _fenetre(ctx: ControlContext, a: Document, b: Document) -> bool:
    return aides.dans_fenetre(aides.date_document(a), aides.date_document(b), ctx.profil.fenetre_doublons_mois)


def _raisons_ailleurs(occs: list[_Occ]) -> list[RaisonCode]:
    return [RaisonCode.rattachement_faible] if any(not o.lien_solide for o in occs) else []


def _ou(o: _Occ) -> str:
    return "dans ce dossier" if o.dossier_id is None else f"dans le dossier {o.dossier_id}"


# =====================================================================================================
# F1 — Document en double
# =====================================================================================================


def _tous_documents(ctx: ControlContext) -> list[_Occ]:
    ici = [_Occ(d, None) for d in ctx.documents.values()]
    vus = set(ctx.documents)
    for autre in ctx.autres_dossiers:
        for lien in autre.dossier.liens:
            d = autre.documents.get(lien.document_id)
            if d is not None and d.id not in vus:
                ici.append(_Occ(d, autre.dossier.id, lien.force.est_solide))
    return ici


@control("F1")
def f1_document_en_double(ctx: ControlContext) -> list[ResultatControle]:
    """F1 — Même ``identite`` de document (§6.2.6 : sha256 du fichier ou clé type/numéro/émetteur/montant)
    présente deux fois (ici ou dans un autre dossier du client), ou document marqué ``doublon_de``. Le
    constat est porté par la seconde occurrence (identifiant le plus grand, UUID v7 : la plus récente).
    ``a_verifier`` (information) ; montant : aucun."""
    tous = _tous_documents(ctx)
    out: list[ResultatControle] = []
    for d in ctx.documents.values():
        unite = cle_unite(doc=d.id)
        premier: _Occ | None = None
        if d.doublon_de:
            premier = next((o for o in tous if o.doc.id == d.doublon_de), _Occ(d, None))
            if premier.doc.id == d.id:
                premier = None
        if premier is None and d.identite:
            anterieurs = [o for o in tous if o.doc.id != d.id and o.doc.identite == d.identite and o.doc.id < d.id
                          and _fenetre(ctx, o.doc, d)]
            premier = min(anterieurs, key=lambda o: o.doc.id) if anterieurs else None
        if premier is None and not d.doublon_de:
            out.append(ctx.conforme("F1", unite=unite, documents=[d.id]))
            continue
        classement = ctx.classify("F1", ecart=None, tolerance=None, seuil_certitude=None, valeurs_cles=[],
                                  documents=[d.id], raisons_supplementaires=_raisons_ailleurs([premier] if premier else []))
        cible = (f"{aides.ref_document(premier.doc)} déjà présent {_ou(premier)}" if premier
                 else f"le document {d.doublon_de} déjà reçu")
        libelle = (
            f"{aides.maj(aides.ref_document(d))} est identique à {cible} : une seule occurrence est prise en compte "
            f"dans les contrôles."
        )
        out.append(ctx.constat(
            "F1", classement, unite=unite, libelle=libelle, prochaine_action=ACTION_F_INFO,
            preuves=[preuve(None, RolePreuve.contexte, calcul=f"identité du document : {d.identite or d.doublon_de}")],
            documents=[d.id], autres_dossiers=[premier.dossier_id] if premier and premier.dossier_id else [],
            details={"document_id": d.id, "premier": premier.doc.id if premier else d.doublon_de},
        ))
    return out or [ctx.non_applicable("F1", RaisonCode.document_manquant)]


# =====================================================================================================
# F2 — Numéro de facture transitaire réutilisé
# =====================================================================================================


def _total_ft(doc: Document) -> ValeurSourcee | None:
    c = doc.ft
    for v in (c.total_ttc, c.net_a_payer, c.total_ht):
        if v is not None and num(v) is not None:
            return v
    return None


@control("F2")
def f2_numero_reutilise(ctx: ControlContext) -> list[ResultatControle]:
    """F2 — Même émetteur, même ``norm_ref(numero)``, montant total différent de plus de ``T_SOMME``.
    Constat sur la facture la plus récente. ``a_verifier`` uniquement ; montant : aucun."""
    fts = ctx.factures_transitaires()
    if not fts:
        return [ctx.non_applicable("F2", RaisonCode.facture_transitaire_absente)]
    pool = _pool(ctx, TypeDocument.facture_transitaire)
    out = []
    for ft in fts:
        unite = cle_unite(ft=ft.id)
        n = norm_ref(aides.texte(ft.ft.numero))
        tot = _total_ft(ft)
        if not n:
            out.append(ctx.non_verifiable("F2", RaisonCode.valeur_absente, unite=unite, documents=[ft.id]))
            continue
        e = aides.emetteur_de(ctx, ft)
        memes = [
            o for o in pool
            if o.doc.id != ft.id
            and norm_ref(aides.texte(o.doc.ft.numero)) == n
            and not (ft.identite and o.doc.identite == ft.identite)  # document identique : F1
            and e is not None and aides.emetteur_de(ctx, o.doc) == e
            and _fenetre(ctx, o.doc, ft)
        ]
        differents = []
        for o in memes:
            to = _total_ft(o.doc)
            if tot is None or to is None:
                continue
            if abs((num(tot) or ZERO) - (num(to) or ZERO)) > ctx.tol.t_somme(1):
                differents.append((o, to))
        if not differents:
            out.append(ctx.conforme("F2", unite=unite, documents=[ft.id]))
            continue
        plus_recente = max([ft, *(o.doc for o, _ in differents)], key=aides.cle_chrono)
        if plus_recente.id != ft.id:
            out.append(ctx.non_applicable("F2", RaisonCode.couvert_par_autre_controle, unite=unite, documents=[ft.id],
                                          details={"porte_par": plus_recente.id}))
            continue
        o, to = differents[0]
        assert tot is not None
        classement = ctx.classify("F2", ecart=None, tolerance=None, seuil_certitude=None,
                                  valeurs_cles=[v for v in (ft.ft.numero, tot) if v is not None],
                                  raisons_supplementaires=_raisons_ailleurs([x for x, _ in differents]))
        libelle = (
            f"{aides.maj(aides.ref_document(ft, ft.ft.numero))} porte le même numéro que "
            f"{aides.ref_document(o.doc, o.doc.ft.numero)} reçue {_ou(o)}, du même émetteur, pour un montant total "
            f"différent ({format_montant(num(tot) or ZERO, 'EUR')} contre {format_montant(num(to) or ZERO, 'EUR')})."
        )
        out.append(ctx.constat(
            "F2", classement, unite=unite, libelle=libelle, prochaine_action=ACTION_F,
            preuves=[preuve(tot, RolePreuve.valeur_b), preuve(to, RolePreuve.valeur_a),
                     *(preuve(v, RolePreuve.contexte) for v in (ft.ft.numero, o.doc.ft.numero) if v is not None)],
            documents=[ft.id], autres_dossiers=sorted({x.dossier_id for x, _ in differents if x.dossier_id}),
            details={"facture_transitaire_id": ft.id, "autres": [x.doc.id for x, _ in differents]},
        ))
    return out


# =====================================================================================================
# F3 — Même déclaration refacturée deux fois
# =====================================================================================================


@dataclass(frozen=True, slots=True)
class _Debours:
    occ: _Occ
    montant: Decimal
    valeurs: tuple[ValeurSourcee, ...]
    mrn: tuple[ValeurSourcee, ...]


def _debours_mrn(ctx: ControlContext, o: _Occ, prefixe: str, prefixes_dossier: list[str]) -> _Debours | None:
    """Débours refacturés par la facture ``o`` pour ``prefixe`` (§12.2) ; ``None`` si aucun."""
    for g in aides.ventiler_debours(o.doc, prefixes_dossier if o.dossier_id is None else []):
        if g.prefixes != (prefixe,) or not g.lignes:
            continue
        vals = [aides.montant_ht(o.doc.ft.lignes[i]) for i in g.lignes]
        if any(num(v) is None for v in vals):
            return None
        return _Debours(o, sum((num(v) or ZERO for v in vals), ZERO), tuple(v for v in vals if v is not None),
                        g.mrn_valeurs)
    return None


def _annulee(ctx: ControlContext, ft: Document, montant: Decimal, t: Decimal) -> bool:
    """Un avoir (ici ou ailleurs) cite la facture et couvre ses débours pour ce MRN dans la tolérance."""
    numero = aides.texte(ft.ft.numero)
    for o in _pool(ctx, TypeDocument.avoir):
        if not any(ref_compatibles(r.valeur, numero) for r in o.doc.av.refs_facture_origine if r.valeur):
            continue
        credit = sum((num(aides.montant_ht(ln)) or ZERO for ln in o.doc.av.lignes if ln.nature.est_debours), ZERO)
        if credit == 0:
            credit = num(o.doc.av.total_credite_ht) or ZERO
        if credit >= montant - t:
            return True
    return False


def _liquide_mrn(ctx: ControlContext, prefixe: str) -> Decimal | None:
    decs = [d for d in ctx.declarations() if d.dec.mrn_prefixe == prefixe]
    if not decs:
        decs = [x.doc for x in aides.documents_autres(ctx, TypeDocument.declaration) if x.doc.dec.mrn_prefixe == prefixe]
        decs = [max(decs, key=lambda d: (num(d.dec.version) or ZERO, aides.texte(d.dec.date_acceptation) or ""))] if decs else []
    return aides.liquide_total(ctx, decs[0]) if decs else None


def _f3_unite(ctx: ControlContext, ft: Document, prefixe: str, pool: list[_Occ]) -> ResultatControle | None:
    prefixes_dossier = list(ctx.mrn_prefixes())
    ici = _debours_mrn(ctx, _Occ(ft, None), prefixe, prefixes_dossier)
    if ici is None:
        return None
    unite = cle_unite(ft=ft.id, mrn=prefixe)
    n_ft = norm_ref(aides.texte(ft.ft.numero))
    autres: list[_Debours] = []
    for o in pool:
        if o.doc.id == ft.id or (n_ft and norm_ref(aides.texte(o.doc.ft.numero)) == n_ft):
            continue  # même facture, ou même numéro (F1/F2)
        if not _fenetre(ctx, o.doc, ft):
            continue
        deb = _debours_mrn(ctx, o, prefixe, prefixes_dossier)
        if deb is not None and deb.montant > 0:
            autres.append(deb)
    details: dict = {"facture_transitaire_id": ft.id, "mrn_prefixe": prefixe}
    if not autres:
        return ctx.conforme("F3", unite=unite, documents=[ft.id], details=details)
    if all(a.occ.dossier_id is None for a in autres):
        return ctx.non_applicable("F3", RaisonCode.couvert_par_autre_controle, unite=unite, documents=[ft.id],
                                  details={**details, "couvert_par": "C5"})
    autres = [a for a in autres if a.occ.dossier_id is not None]
    tous = [ici, *autres]
    recent = max(tous, key=lambda x: aides.cle_chrono(x.occ.doc))
    if recent.occ.doc.id != ft.id:
        return ctx.non_applicable("F3", RaisonCode.couvert_par_autre_controle, unite=unite, documents=[ft.id],
                                  details={**details, "porte_par": recent.occ.doc.id,
                                           "dossier": recent.occ.dossier_id})
    autre = max(autres, key=lambda x: aides.cle_chrono(x.occ.doc))
    tol = ctx.tol
    t_deb, s_deb = tol.t_debours(0), tol.s_debours()
    commun = dict(unite=unite, attendu=arrondi_centime(autre.montant), constate=arrondi_centime(ici.montant),
                  ecart=arrondi_centime(ici.montant), tolerance=t_deb, seuil_certitude=s_deb, documents=[ft.id],
                  details={**details, "autre_facture": autre.occ.doc.id, "autre_dossier": autre.occ.dossier_id})
    # Une facture annulée par un avoir, ou une facture complémentaire, n'est pas un doublon.
    if _annulee(ctx, ft, ici.montant, t_deb) or _annulee(ctx, autre.occ.doc, autre.montant, t_deb):
        return ctx.conforme("F3", **{**commun, "details": {**commun["details"], "annulee_par_avoir": True}})
    liq = _liquide_mrn(ctx, prefixe)
    if liq is not None and abs(ici.montant + autre.montant - liq) <= t_deb:
        return ctx.conforme("F3", **{**commun, "details": {**commun["details"], "complementaire": True}})
    # Déclaration absente : la complémentarité n'est pas testable ; le critère de certitude de §15 F3
    # (MRN lus, débours égaux dans T_DEBOURS et > S_DEBOURS) est appliqué tel quel (D-308).
    raisons = _raisons_ailleurs([autre.occ])
    egaux = abs(ici.montant - autre.montant) <= t_deb
    if not egaux:
        raisons.append(RaisonCode.controle_signal_seulement)  # débours différents : refacturation partielle ?
    mrn_vals = [*ici.mrn, *autre.mrn]
    if not ici.mrn or not autre.mrn:
        raisons.append(RaisonCode.confiance_insuffisante)
    classement = ctx.classify(
        "F3", ecart=ici.montant, tolerance=None, seuil_certitude=s_deb,
        valeurs_cles=[*mrn_vals, *ici.valeurs, *autre.valeurs], montant=ici.montant, raisons_supplementaires=raisons,
    )
    libelle = (
        f"{aides.maj(aides.ref_document(ft, ici.valeurs[0]))} refacture {format_montant(arrondi_centime(ici.montant), 'EUR')} "
        f"de débours pour le MRN {aides.texte(mrn_vals[0]) if mrn_vals else prefixe} ; "
        f"{aides.ref_document(autre.occ.doc, autre.valeurs[0])}, {_ou(autre.occ)}, refacture déjà "
        f"{format_montant(arrondi_centime(autre.montant), 'EUR')} de débours pour la même déclaration."
    )
    return ctx.constat(
        "F3", classement, libelle=libelle, prochaine_action=ACTION_F, montant=ici.montant,
        composante=None,
        preuves=[*(preuve(v, RolePreuve.valeur_b) for v in ici.valeurs),
                 *(preuve(v, RolePreuve.valeur_a) for v in autre.valeurs),
                 *(preuve(v, RolePreuve.contexte) for v in mrn_vals)],
        autres_dossiers=[autre.occ.dossier_id] if autre.occ.dossier_id else [], **commun,
    )


@control("F3")
def f3_declaration_refacturee_deux_fois(ctx: ControlContext) -> list[ResultatControle]:
    """F3 — Deux factures transitaires distinctes (numéros différents) refacturent des débours pour le même
    ``mrn_prefixe``, aucun avoir n'annule l'une d'elles et la seconde n'est pas une facture complémentaire
    (somme des deux = ``liquide_total`` dans ``T_DEBOURS`` -> ``conforme``). ``ecart_certain`` si le MRN est
    lu ≥ 0,90 sur les deux factures, débours égaux dans ``T_DEBOURS`` et ``> S_DEBOURS``. Montant
    ``recouvrable`` = débours de la facture la plus récente ; constat porté par le dossier de celle-ci.
    Deux factures du même dossier : ``non_applicable`` (déjà compté par C5)."""
    fts = ctx.factures_transitaires()
    if not fts:
        return [ctx.non_applicable("F3", RaisonCode.facture_transitaire_absente)]
    pool = _pool(ctx, TypeDocument.facture_transitaire)
    out: list[ResultatControle] = []
    prefixes_dossier = list(ctx.mrn_prefixes())
    for ft in fts:
        prefixes = sorted({p for g in aides.ventiler_debours(ft, prefixes_dossier) if len(g.prefixes) == 1
                           for p in g.prefixes})
        for p in prefixes:
            r = _f3_unite(ctx, ft, p, pool)
            if r is not None:
                out.append(r)
    return out or [ctx.non_applicable("F3", RaisonCode.valeur_absente,
                                      details={"motif": "aucun débours rattaché à un MRN"})]


# =====================================================================================================
# F4 — Même prestation facturée deux fois
# =====================================================================================================


def _refs_ligne(doc: Document, i: int) -> tuple[set[str], set[str]]:
    """(préfixes MRN, références de transport) d'une ligne ; à défaut ceux de l'en-tête s'ils sont uniques."""
    ln = doc.ft.lignes[i]
    mrns = {mrn_prefixe(ln.mrn.valeur)} if ln.mrn is not None and ln.mrn.valeur else set()
    refs = {ln.ref_transport.valeur} if ln.ref_transport is not None and ln.ref_transport.valeur else set()
    if not mrns and not refs:
        tete_m = set(aides.mrn_cites(doc))
        tete_r = {v.valeur for v in doc.ft.refs_transport if v.valeur}
        if len(tete_m) == 1:
            mrns = tete_m
        if len(tete_r) == 1:
            refs = tete_r
    return {m for m in mrns if len(m) == 15}, refs


@control("F4")
def f4_prestation_facturee_deux_fois(ctx: ControlContext) -> list[ResultatControle]:
    """F4 — Deux factures distinctes du même émetteur portent une ligne de prestation de même nature, même
    référence de transport ou MRN, même montant. Constat sur la ligne de la facture la plus récente.
    ``a_verifier`` uniquement ; montant ``recouvrable`` = montant de cette ligne."""
    fts = ctx.factures_transitaires()
    if not fts:
        return [ctx.non_applicable("F4", RaisonCode.facture_transitaire_absente)]
    pool = _pool(ctx, TypeDocument.facture_transitaire)
    out: list[ResultatControle] = []
    for ft in fts:
        e = aides.emetteur_de(ctx, ft)
        n_ft = norm_ref(aides.texte(ft.ft.numero))
        for i, ln in enumerate(ft.ft.lignes):
            if not ln.nature.est_prestation:
                continue
            unite = cle_unite(ft=ft.id, ligne=i)
            v = aides.montant_ht(ln)
            m = num(v)
            if m is None or m == 0:
                continue
            mrns, refs = _refs_ligne(ft, i)
            if not mrns and not refs:
                continue
            doublons: list[tuple[_Occ, int]] = []
            for o in pool:
                if o.doc.id == ft.id or (n_ft and norm_ref(aides.texte(o.doc.ft.numero)) == n_ft):
                    continue
                if not aides.memes_emetteurs(e, aides.emetteur_de(ctx, o.doc)) or not _fenetre(ctx, o.doc, ft):
                    continue
                for j, lo in enumerate(o.doc.ft.lignes):
                    if lo.nature is not ln.nature or num(aides.montant_ht(lo)) != m:
                        continue
                    m2, r2 = _refs_ligne(o.doc, j)
                    if (mrns & m2) or any(ref_transport_egales(a, b) for a in refs for b in r2):
                        doublons.append((o, j))
            details: dict = {"facture_transitaire_id": ft.id, "ligne": i}
            if not doublons:
                out.append(ctx.conforme("F4", unite=unite, documents=[ft.id], details=details))
                continue
            recent = max([ft, *(o.doc for o, _ in doublons)], key=aides.cle_chrono)
            if recent.id != ft.id:
                out.append(ctx.non_applicable("F4", RaisonCode.couvert_par_autre_controle, unite=unite,
                                              documents=[ft.id], details={**details, "porte_par": recent.id}))
                continue
            o, j = max(doublons, key=lambda x: aides.cle_chrono(x[0].doc))
            v_autre = aides.montant_ht(o.doc.ft.lignes[j])
            assert v is not None
            classement = ctx.classify("F4", ecart=m, tolerance=None, seuil_certitude=None, valeurs_cles=[v],
                                      montant=m, raisons_supplementaires=_raisons_ailleurs([o]))
            libelle = (
                f"La ligne « {aides.texte(ln.libelle) or ln.nature.value.replace('_', ' ')} » de "
                f"{aides.ref_document(ft, v)} ({format_montant(m, 'EUR')}) figure avec la même nature, la même "
                f"référence et le même montant sur {aides.ref_document(o.doc, v_autre)} reçue {_ou(o)}."
            )
            out.append(ctx.constat(
                "F4", classement, unite=unite, libelle=libelle, prochaine_action=ACTION_F, montant=m,
                composante=Composante.prestation,
                preuves=[preuve(v, RolePreuve.valeur_b), preuve(v_autre, RolePreuve.valeur_a)],
                documents=[ft.id], autres_dossiers=[o.dossier_id] if o.dossier_id else [],
                details={**details, "autre_facture": o.doc.id, "autre_ligne": j}, ecart=arrondi_centime(m),
            ))
    return out or [ctx.non_applicable("F4", RaisonCode.valeur_absente,
                                      details={"motif": "aucune ligne de prestation avec référence"})]


# =====================================================================================================
# F5 — Même facture commerciale sur plusieurs déclarations
# =====================================================================================================


def _refs_declaration(dec: Document) -> list[ValeurSourcee]:
    c = dec.dec
    vals = [r.reference for r in c.documents_references if r.reference is not None
            and (r.type_code is None or not (r.type_code.valeur or "").startswith(("1008", "N7", "N740", "N741")))]
    vals += [v for a in c.articles for v in a.references_facture]
    return [v for v in vals if v.valeur]


def _f5_facture(ctx: ControlContext, fc: Document) -> ResultatControle:
    unite = cle_unite(fc=fc.id)
    numero = aides.texte(fc.fc.numero)
    details: dict = {"facture_commerciale_id": fc.id}
    if not numero:
        return ctx.non_verifiable("F5", RaisonCode.valeur_absente, unite=unite, documents=[fc.id], details=details)
    # Déclarations (dernière version par préfixe) qui citent cette facture, ici et ailleurs.
    candidates: list[tuple[Document, str | None]] = [(d, None) for d in ctx.declarations()]
    ailleurs: dict[str, DocAilleurs] = {}
    for x in aides.documents_autres(ctx, TypeDocument.declaration):
        p = x.doc.dec.mrn_prefixe or x.doc.id
        if p not in ailleurs or (num(x.doc.dec.version) or ZERO) > (num(ailleurs[p].doc.dec.version) or ZERO):
            ailleurs[p] = x
    prefixes_ici = {d.dec.mrn_prefixe for d, _ in candidates}
    candidates += [(x.doc, x.dossier_id) for p, x in ailleurs.items() if p not in prefixes_ici]
    citantes: dict[str, tuple[Document, str | None, ValeurSourcee]] = {}
    for d, dos in candidates:
        if not _fenetre(ctx, d, fc):
            continue
        refs = _refs_declaration(d)
        hit = next((r for r in refs if ref_compatibles(r.valeur, numero)), None)
        if hit is None:
            continue
        p = d.dec.mrn_prefixe or d.id
        citantes.setdefault(p, (d, dos, hit))
    if len(citantes) < 2:
        return ctx.conforme("F5", unite=unite, documents=[fc.id], details={**details, "declarations": len(citantes)})
    # Le constat est porté par le dossier de la déclaration la plus récente.
    recente = max(citantes.values(), key=lambda x: aides.cle_chrono(x[0]))
    if recente[1] is not None:
        return ctx.non_applicable("F5", RaisonCode.couvert_par_autre_controle, unite=unite, documents=[fc.id],
                                  details={**details, "porte_par_dossier": recente[1]})
    total = fc.fc.total_facture
    devise = (aides.texte(fc.fc.devise) or "").upper()
    if not aides.utilisable_num(ctx, total) or not devise:
        return ctx.non_verifiable("F5", RaisonCode.valeur_absente, unite=unite, documents=[fc.id], details=details)
    v_total = num(total) or ZERO
    declares: list[ValeurSourcee] = []
    for d, _, _ in citantes.values():
        v = d.dec.montant_total_facture
        dv = (aides.texte(d.dec.devise_facture) or "").upper()
        if not aides.utilisable_num(ctx, v) or dv != devise:
            return ctx.non_verifiable("F5", RaisonCode.valeur_absente, unite=unite, documents=[fc.id],
                                      details={**details, "motif": "montant déclaré absent ou en autre devise"})
        assert v is not None
        declares.append(v)
    somme = sum((num(v) or ZERO for v in declares), ZERO)
    t = ctx.tol.t_valeur(v_total, somme)
    ecart = somme - v_total
    commun = dict(unite=unite, attendu=v_total, constate=somme, ecart=ecart, tolerance=t, documents=[fc.id],
                  details={**details, "declarations": sorted(d.id for d, _, _ in citantes.values())})
    if ecart <= t:
        return ctx.conforme("F5", **commun)
    dec_ici = recente[0]
    taux = num(dec_ici.dec.taux_change)
    sens = aides.texte(dec_ici.dec.taux_change_sens)
    eur = eur_par_devise(taux, sens) if taux and sens in ("eur_par_devise", "devise_par_eur") else None
    montant = montant_ecart_documentaire(somme, v_total, devise=devise, taux_eur_par_devise=eur)
    classement = ctx.classify("F5", ecart=ecart, tolerance=t, seuil_certitude=None, valeurs_cles=[total, *declares],
                              raisons_supplementaires=_raisons_ailleurs(
                                  [_Occ(d, dos, True) for d, dos, _ in citantes.values()]))
    mrns = ", ".join(aides.texte(d.dec.mrn) or "?" for d, _, _ in sorted(citantes.values(), key=lambda x: x[0].id))
    libelle = (
        f"{aides.maj(aides.ref_document(fc, total))} ({format_montant(v_total, devise)}) est citée par "
        f"{len(citantes)} déclarations (MRN {mrns}) dont les montants facturés déclarés totalisent "
        f"{format_montant(somme, devise)}, soit {format_montant(ecart, devise)} de plus que le total de la facture."
    )
    return ctx.constat(
        "F5", classement, libelle=libelle, prochaine_action=ACTION_F5, montant=montant, composante=Composante.valeur,
        preuves=[preuve(total, RolePreuve.valeur_a), *(preuve(v, RolePreuve.valeur_b) for v in declares),
                 *(preuve(h, RolePreuve.contexte) for _, _, h in citantes.values())],
        autres_dossiers=sorted({dos for _, dos, _ in citantes.values() if dos}), **commun,
    )


@control("F5")
def f5_facture_sur_plusieurs_declarations(ctx: ControlContext) -> list[ResultatControle]:
    """F5 — Une facture commerciale citée par plusieurs déclarations de préfixes MRN différents dont la
    somme des montants déclarés dépasse le total facture de plus de ``T_VALEUR``. ``a_verifier`` uniquement ;
    montant ``ecart_documentaire`` (en EUR au taux imprimé de la déclaration, sinon ``null``)."""
    fcs = ctx.factures_commerciales()
    if not fcs:
        return [ctx.non_applicable("F5", RaisonCode.document_manquant)]
    return [_f5_facture(ctx, fc) for fc in fcs]
