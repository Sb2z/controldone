"""Calcul mécanique de la vérité : conséquences, imputation des avoirs, niveaux attendus,
montants en jeu, pièges, liens attendus et valeurs vraies (SPEC §8.6, §19.3)."""

from __future__ import annotations

from decimal import Decimal

from .build import faf_amount, faf_base
from .clients import grid_poste
from .common import D, D0, q2, s2, sdec
from .inject import _explicit, _ref_compatible
from .model import composante_of
from .plan import CERTAIN_ELIGIBLE

ACCEPTED = {
    "P1": ["P1"], "P2": ["P2", "P1"], "P4": ["P4"],
    "A1": ["A1"], "A2": ["A2"], "A3": ["A3", "A6"], "A4": ["A4", "A5"], "A5": ["A5", "A4"], "A6": ["A6", "A3", "A5"],
    "A7": ["A7", "A6"], "A8": ["A8"], "A9": ["A9"], "A10": ["A10"], "A11": ["A11", "B5"], "A12": ["A12"],
    "A13": ["A13"], "A14": ["A14"], "A15": ["A15"],
    "B1": ["B1", "B2"], "B2": ["B2", "B1"], "B3": ["B3"], "B4": ["B4", "A10"], "B5": ["B5", "A11"],
    "C1": ["C1", "C5"], "C2": ["C2", "C5"], "C3": ["C3", "C5"], "C4": ["C4", "C5"], "C5": ["C5", "C1", "C2", "C3", "C4"],
    "C6": ["C6", "D4"], "C7": ["C7"], "C8": ["C8"],
    "D1": ["D1"], "D2": ["D2", "D7"], "D3": ["D3"], "D4": ["D4", "C6"], "D5": ["D5"], "D6": ["D6", "D3"],
    "D7": ["D7", "D2", "D3"], "D8": ["D8"], "D9": ["D9", "D3"],
    "E1": ["E1"], "E2": ["E2"], "E3": ["E3", "F1"], "E4": ["E4"], "E5": ["E5"], "E6": ["E6"],
    "F1": ["F1", "E3"], "F2": ["F2"], "F3": ["F3", "C5"], "F4": ["F4", "D5"], "F5": ["F5", "A4"],
    "G1": ["G1", "B1"], "G2": ["G2"], "G3": ["G3", "G2"], "G4": ["G4", "G5", "C1", "C5"], "G5": ["G5", "G4"],
    "G6": ["G6"],
}

AMOUNT_NATURE = {
    "A4": "ecart_documentaire", "A5": "ecart_documentaire", "A6": "ecart_documentaire", "F5": "ecart_documentaire",
    "B1": "arithmetique_declaration", "B2": "arithmetique_declaration", "B3": "arithmetique_declaration",
    "G1": "arithmetique_declaration", "G2": "arithmetique_declaration",
    "A12": "renvoi", "A13": "renvoi", "G3": "renvoi", "G6": "renvoi",
}
for _c in ("C1", "C2", "C3", "C4", "C5", "C6", "D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9", "E6", "F3", "F4",
           "G4", "G5"):
    AMOUNT_NATURE[_c] = "recouvrable"


def t_debours(n_articles: int) -> Decimal:
    return max(Decimal("0.05"), min(Decimal("0.01") * n_articles, Decimal("0.50")))


def t_somme(n: int) -> Decimal:
    return max(Decimal("0.01"), min(Decimal("0.01") * n, Decimal("0.50")))


CAT_OF_NATURE = {"debours_droits": "droit", "debours_autres_taxes": "autre_taxe", "debours_tva": "tva",
                 "debours_forfait_petits_envois": "forfait_petits_envois", "debours_combines": "combine"}


def _refacture(dm, d):
    out = {"droit": D0, "autre_taxe": D0, "tva": D0, "forfait_petits_envois": D0, "combine": D0}
    for ft in dm.fts:
        if ft.kind == "rebill":
            continue
        for l in ft.lines:
            if l.is_debours and (l.mrn == d.mrn):
                out[CAT_OF_NATURE[l.nature]] += l.montant_ht
    return out


def _debours_ft(dm, d):
    for ft in dm.fts:
        if ft.kind != "rebill" and any(l.is_debours and l.mrn == d.mrn for l in ft.lines):
            return ft
    return dm.fts[0]


def compute_consequences(dm):
    """Montants C, conséquences C5/C6/G4, imputation des avoirs (E5/E6)."""
    if dm.plan["p_error"] == "declaration_manquante":
        return
    excess_by_decl = {}
    for d in dm.final_decls:
        liq = d.liquide()
        ref = _refacture(dm, d)
        n_art = len(d.articles)
        tol = t_debours(n_art)
        ex = {k: ref[k] - liq.get(k, D0) for k in ("droit", "autre_taxe", "tva", "forfait_petits_envois")}
        if dm.plan["template"] == "T3":
            tot = sum(ref.values(), D0) - sum(liq.values(), D0)
            ex = {"combine": tot}
        if d.autoliq:
            ex["tva_autoliq"] = ref["tva"]
            ex["tva"] = D0
        excess_by_decl[d.doc_id] = (ex, tol)
        ft = _debours_ft(dm, d)
        for e in dm.errors:
            k = e.get("key") or ""
            if k == f"C1:{d.doc_id}":
                e["amount"] = q2(ex["droit"])
            elif k == f"C2:{d.doc_id}":
                e["amount"] = q2(ex["autre_taxe"])
            elif k == f"C4:{d.doc_id}":
                e["amount"] = q2(ex["tva"])
            elif k == f"C3:{d.doc_id}":
                e["amount"] = q2(ex.get("tva_autoliq", D0))
            elif k == f"C5:{d.doc_id}":
                e["amount"] = q2(ex["combine"])
            elif k == f"G4:{d.doc_id}":
                e["amount"] = q2(ex["forfait_petits_envois"])
            else:
                continue
            e["gap"] = abs(e["amount"])
        # G5 -> G4 porte le montant
        if any(e["key"] == f"G5:{d.doc_id}" for e in dm.errors) and not any(
                e["key"] == f"G4:{d.doc_id}" for e in dm.errors):
            amt = q2(ex["forfait_petits_envois"])
            dm.add_error("G4", "forfait_surfacture", [ft.doc_id, d.doc_id], amount=amt, nature="recouvrable",
                         composante="forfait_petits_envois", gap=abs(amt), thr=Decimal(1), consequence_of="G5",
                         description="Conséquence de G5 : forfait refacturé supérieur au forfait liquidé.",
                         key=f"G4G5:{d.doc_id}")
            for e in dm.errors:
                if e["key"] == f"G5:{d.doc_id}":
                    e["exclude_totals"] = True
        # C5 conséquence
        if dm.plan["template"] != "T3":
            tot = sum((v for k, v in ex.items() if k not in ("tva_autoliq",)), D0)
            if abs(tot) > tol and not any(e["key"] == f"C5:{d.doc_id}" for e in dm.errors):
                dm.add_error("C5", "debours_combines_surfactures", [ft.doc_id, d.doc_id], amount=q2(tot),
                             nature="recouvrable", composante=None, gap=abs(q2(tot)), thr=Decimal(1),
                             consequence_of="C", exclude_totals=True,
                             description="Conséquence : le total des débours refacturés dépasse le total liquidé.",
                             key=f"C5c:{d.doc_id}")
    # C6 : frais d'avance de fonds calculés sur l'excédent
    grid = dm.grid
    pst = grid_poste(grid, "AVANCE_FONDS")
    planned_c6 = any(e["control"] == "C6" for e in dm.plan["errors"])
    for ft in dm.fts:
        if ft.kind == "rebill":
            continue
        for l in ft.lines:
            if l.code != "AVANCE_FONDS":
                continue
            decls = [d for d in dm.final_decls if l.mrn is None or d.mrn == l.mrn]
            deb_lines = [x for f2 in dm.fts if f2.kind != "rebill" for x in f2.lines
                         if x.is_debours and any(x.mrn == d.mrn for d in decls)]
            base = faf_base(grid, deb_lines)
            excess = D0
            dep = []
            for d in decls:
                ex, tol = excess_by_decl[d.doc_id]
                for k, v in ex.items():
                    if k in ("tva", "tva_autoliq") and pst["base_pourcentage"] == "debours_hors_tva":
                        continue
                    if v > tol:
                        excess += v
                        dep.append(d.doc_id)
            if excess <= 0:
                continue
            att = faf_amount(grid, base - excess)
            exc = q2(l.montant_ht - att)
            if exc > Decimal("0.01"):
                deps = [e["key"] for e in dm.errors if e["control"] in ("C1", "C2", "C3", "C4", "C5", "G4")
                        and any(e["key"].endswith(":" + did) for did in dep)]
                docs = [ft.doc_id] + sorted({_debours_ft(dm, d).doc_id for d in decls} - {ft.doc_id}) + \
                    [d.doc_id for d in decls]
                dm.add_error("C6", "faf_sur_excedent", docs, amount=exc, nature="recouvrable",
                             composante="prestation", gap=exc, thr=Decimal(1),
                             consequence_of=None if planned_c6 else "C", depends_on=deps,
                             description=f"Frais d'avance de fonds {l.montant_ht} calculés sur des débours "
                                         f"incluant un excédent de {q2(excess)} (attendu {att}).",
                             key=f"C6:{ft.doc_id}:{l.mrn}")
    _impute_avoirs(dm)


def _impute_avoirs(dm):
    if not dm.avoirs:
        return
    av = dm.avoirs[0]
    origin_ids = {ft.doc_id for ft in dm.fts}
    gaps = [e for e in dm.errors if e["nature"] == "recouvrable" and e["amount"] is not None and e["amount"] > 0
            and e["control"] in ("C1", "C2", "C3", "C4", "C5", "C6", "D2", "D3", "D4", "D5", "D6", "D7", "D9", "G4")
            and not e.get("exclude_totals") and any(doc in origin_ids for doc in e["documents"])]
    comp_of_err = {"C1": "droit", "C2": "autre_taxe", "C3": "tva", "C4": "tva", "C5": "combine", "G4":
                   "forfait_petits_envois"}
    rest = {id(e): e["amount"] for e in gaps}
    imputed = {id(e): D0 for e in gaps}
    leftover = D0
    for l in av.lines:
        comp = composante_of(l.nature)
        remaining = l.montant_ht
        for e in gaps:
            c = comp_of_err.get(e["control"], "prestation")
            if c != comp or remaining <= 0:
                continue
            take = min(remaining, rest[id(e)])
            rest[id(e)] -= take
            imputed[id(e)] += take
            remaining -= take
        leftover += remaining
    for e in gaps:
        if imputed[id(e)] > 0:
            net = q2(rest[id(e)])
            e["amount_brut"] = e["amount"]
            e["amount"] = net
            e["gap"] = abs(net)
            e["replaced_by_e6"] = True
            if net > t_debours(1):
                dm.add_error("E6", "avoir_partiel", [av.doc_id] + [x for x in e["documents"] if x.startswith("ft")],
                             amount=net, nature="recouvrable", composante=e["composante"], eligible=False,
                             description=f"Avoir {av.numero} imputé {q2(imputed[id(e)])} sur un écart de "
                                         f"{e['amount_brut']} ({e['control']}) : reste {net}.",
                             key=f"E6:{e['key']}")
            else:
                dm.warnings.append(f"écart {e['key']} entièrement couvert par l'avoir")
    if leftover > t_somme(len(av.lines)):
        dm.add_error("E5", "avoir_sans_ecart", [av.doc_id], eligible=False,
                     description=f"Reliquat d'avoir {q2(leftover)} sans écart ouvert correspondant.", key="E5")


# ======================================================================
# Pièges
# ======================================================================

def compute_traps(dm):
    p = dm.plan
    ex = dm.absent
    present_cis = [c for c in dm.cis if c.doc_id not in ex]
    present_decls = [d for d in dm.final_decls if d.doc_id not in ex]
    ctl = {e["control"] for e in dm.errors}
    d0 = present_decls[0] if present_decls else None
    ci0 = present_cis[0] if present_cis else None
    ft0 = dm.fts[0] if dm.fts else None
    value_err = ctl & {"A3", "A4", "A5", "A6", "A7", "F5", "B3"}
    if getattr(dm, "trap_round", False) and d0 and ft0:
        dm.add_trap("C1", "conforme", [ft0.doc_id, d0.doc_id],
                    "Écart d'arrondi de 0,03 EUR entre droits liquidés et droits refacturés (sous T_DEBOURS).")
    if d0 and d0.euro_round and "B1" not in ctl:
        dm.add_trap("B1", "conforme", [d0.doc_id], "Droits arrondis à l'euro par le système déclarant.")
    if ci0 and d0 and ci0.currency != "EUR" and d0.currency == "EUR" and d0.rate_printed is not None and not value_err:
        dm.add_trap("A5", "conforme", [ci0.doc_id, d0.doc_id], "Conversion légitime en EUR au taux imprimé.")
        dm.add_trap("A3", "conforme", [ci0.doc_id, d0.doc_id], "Devises différentes : montant converti au taux imprimé.")
    if d0 and d0.autoliq and "C3" not in ctl and ft0:
        dm.add_trap("C3", "conforme", [ft0.doc_id, d0.doc_id], "TVA autoliquidée non refacturée.")
    if "facture_complementaire" in dm.tags and d0:
        dm.add_trap("F3", "conforme", [dm.fts[0].doc_id, dm.fts[1].doc_id],
                    "Facture complémentaire légitime : la somme des deux factures égale le montant liquidé.")
        dm.add_trap("C4", "conforme", [dm.fts[0].doc_id, dm.fts[1].doc_id, d0.doc_id],
                    "Débours répartis entre facture initiale et complémentaire.")
    if p["freight_trap"] and ci0 and d0 and not (ctl & {"A3", "A4", "A5", "A6", "A7", "F5"}):
        dm.add_trap("A4", "a_verifier", [ci0.doc_id, d0.doc_id],
                    "Le fret en pied de facture explique l'écart entre total facture et montant déclaré.")
    if ci0 and d0 and "A13" not in ctl and any(l.hs_printed and len("".join(ch for ch in l.hs_printed if ch.isdigit())) == 6
                                              for l in ci0.lines):
        dm.add_trap("A13", "conforme", [ci0.doc_id, d0.doc_id],
                    "Codes à 6 chiffres sur la facture, 10 chiffres sur la déclaration.")
    if ci0 and ci0.sous_type == "pro_forma":
        dm.add_trap("P1", "conforme", [ci0.doc_id], "Facture pro forma acceptée comme facture commerciale.")
        dm.add_trap("P2", "conforme", [ci0.doc_id], "Facture pro forma : document exploitable.")
    if p["trunc_ref"] and "A2" not in ctl and ci0 and d0:
        dm.add_trap("A2", "conforme", [ci0.doc_id, d0.doc_id], "Référence de facture tronquée mais compatible.")
    if ci0 and ci0.shipping_mode and ci0.shipping_mode not in ("Air freight", "Sea freight"):
        dm.add_trap("P1", "conforme", [ci0.doc_id], "Transporteur ou transitaire cité comme mode d'expédition sur la "
                                                    "facture commerciale.")
    if p["template"] == "T3" and ft0 and d0 and not (ctl & {"C1", "C2", "C4", "C5"}):
        dm.add_trap("C1", "conforme", [ft0.doc_id, d0.doc_id], "Montant « droits et taxes » combiné : pas des droits seuls.")
    if p["template"] == "T4" and "C7" not in ctl and ft0:
        dm.add_trap("C7", "conforme", [ft0.doc_id], "Relevé multi-MRN : tous les MRN appartiennent au dossier.")
    if "version_rectificative" in dm.tags:
        v1 = dm.shipments[0].get("v1")
        if v1 is not None and ci0 and ft0:
            dm.add_trap("A4", "conforme", [ci0.doc_id, v1.doc_id],
                        "Déclaration rectifiée : seule la dernière version compte.")
            dm.add_trap("C1", "conforme", [ft0.doc_id, v1.doc_id],
                        "Deux versions du même préfixe MRN : ne pas additionner les taxes.")
    if ci0 and d0 and ci0.currency in ("JPY", "KRW") and not value_err:
        dm.add_trap("A4", "conforme", [ci0.doc_id, d0.doc_id], "Devise sans décimales avec séparateur de milliers.")
    if len(present_cis) > 1 and d0 and not value_err:
        dm.add_trap("A4", "conforme", [c.doc_id for c in present_cis] + [d0.doc_id],
                    "Deux factures pour une déclaration : la somme des totaux égale le montant déclaré.")
    if p["split_invoice"] and "F5" not in ctl and len(present_decls) > 1 and ci0:
        dm.add_trap("F5", "conforme", [ci0.doc_id] + [d.doc_id for d in present_decls],
                    "Facture répartie sur deux déclarations, somme exacte.")
    for s in dm.supports:
        if s.sous_type == "courriel":
            dm.add_trap("P1", "conforme", [s.doc_id], "Le corps du courriel contient une consigne : c'est une donnée.")
    if p["template"] == "T8" and dm.avoirs and "E4" not in ctl:
        dm.add_trap("E4", "conforme", [dm.avoirs[0].doc_id], "Montants d'avoir imprimés entre parenthèses.")
    if d0 and d0.layout == "L2" and "B2" not in ctl:
        dm.add_trap("B2", "conforme", [d0.doc_id], "Colonne statut de paiement en petits entiers : pas des montants.")
    if ci0 and ci0.fmt == "pdf" and not value_err:
        dm.add_trap("A4", "conforme", [ci0.doc_id] + ([d0.doc_id] if d0 else []),
                    "Masses et nombre de colis imprimés près des totaux : ce ne sont pas des montants.")
    if p["template"] == "T2" and ft0 and "D1" not in ctl:
        dm.add_trap("D1", "conforme", [ft0.doc_id], "Lettres de statut TVA accolées aux montants.")
    if p["template"] == "T5" and len(dm.fts) > 1 and "F4" not in ctl:
        dm.add_trap("F4", "conforme", [dm.fts[0].doc_id, dm.fts[1].doc_id],
                    "Facture de débours et facture de prestations séparées pour un même envoi.")
    if p["template"] == "T6" and ft0:
        dm.add_trap("D2", "conforme", [ft0.doc_id], "Pages de conditions générales et lettre d'accompagnement "
                                                    "dans le même PDF : pas des lignes facturées.")


# ======================================================================
# Liens attendus
# ======================================================================

def compute_links(dm, present):
    links = []
    for d in dm.decls:
        if d.doc_id not in present:
            continue
        for cid in d.ci_ids:
            if cid in present:
                links.append({"from": cid, "to": d.doc_id, "role": "declaration"})
    for ft in dm.fts:
        if ft.doc_id not in present or ft.kind == "rebill":
            continue
        for did in ft.decl_ids:
            if did in present:
                links.append({"from": ft.doc_id, "to": did, "role": "facture_transitaire"})
    for av in dm.avoirs:
        origin = dm.fts[1] if dm.plan["template"] == "T5" else dm.fts[0]
        if av.doc_id in present:
            links.append({"from": av.doc_id, "to": origin.doc_id, "role": "avoir"})
    for s in dm.supports:
        if s.doc_id not in present or s.sous_type in ("conditions_generales",):
            continue
        tgt = s.data.get("ci")
        if s.sous_type == "lettre_accompagnement":
            tgt = dm.fts[0].doc_id
        if tgt and tgt in present:
            links.append({"from": s.doc_id, "to": tgt, "role": "support"})
        elif s.sous_type == "titre_transport":
            decl = next((d for d in dm.final_decls if d.shipment == s.data.get("shipment") and d.doc_id in present), None)
            if decl:
                links.append({"from": s.doc_id, "to": decl.doc_id, "role": "support"})
    return links


# ======================================================================
# Valeurs vraies
# ======================================================================

def _taux_str(t):
    return str(D(t).normalize()) if D(t) != D(t).to_integral_value() else str(D(t).quantize(Decimal(1)))


def tv_ci(ci):
    return {
        "numero": ci.numero, "date": ci.date.isoformat(), "devise": ci.currency,
        "total_facture": sdec(ci.total, ci.currency), "total_imprime": ci.total_printed,
        "acheteur.tva": ci.buyer.vat, "acheteur.nom": ci.buyer.name, "vendeur.nom": ci.seller.name,
        "incoterm": ci.incoterm, "incoterm_lieu": ci.incoterm_place, "ref_transport": ci.transport_ref,
        "sous_type": ci.sous_type,
        "sous_totaux": {k: sdec(v, ci.currency) for k, v in sorted(ci.footer.items())},
        "masse_brute_totale": str(ci.gross_total), "masse_nette_totale": str(ci.net_total),
        "nombre_colis": ci.packages,
        "lignes": [{"numero_ligne": l.no, "reference_article": l.ref, "description": l.desc,
                    "code_marchandise_imprime": l.hs_printed, "quantite": _qty(l.qty), "unite": l.unit,
                    "prix_unitaire": sdec(l.price, ci.currency), "montant_ligne": sdec(l.amount, ci.currency),
                    "pays_origine": l.origin, "masse_nette": str(l.net), "masse_brute": str(l.gross)}
                   for l in ci.lines],
    }


def _qty(q):
    q = D(q)
    return str(q.quantize(Decimal(1))) if q == q.to_integral_value() else str(q.normalize())


def tv_decl(d):
    ov = d.printed_totals_override
    return {
        "mrn": d.mrn, "lrn": d.lrn, "version": d.version, "date_acceptation": d.date.isoformat(),
        "sous_type": d.sous_type,
        "importateur.tva": d.importer.vat, "importateur.nom": d.importer.name, "declarant.tva": d.declarant.vat,
        "devise_facture": d.currency, "montant_total_facture": sdec(d.total_invoiced, d.currency),
        "taux_change": None if d.rate_printed is None else f"{d.rate_printed:.5f}",
        "taux_change_sens": d.rate_sens, "incoterm": d.incoterm, "incoterm_lieu": d.incoterm_place,
        "pays_expedition": d.pays_exp,
        "nombre_articles": d.n_articles_printed or len(d.articles),
        "masse_brute_totale": str(d.gross_total), "nombre_colis_total": d.packages_total,
        "documents_references": [{"type_code": c, "reference": r} for c, r in d.doc_refs],
        "indices_autoliquidation": bool(d.autoliq),
        "articles": [{"numero_article": a.no, "code_marchandise": a.hs10, "description": a.desc,
                      "pays_origine": a.origin, "montant_facture_article": sdec(a.amount, d.currency),
                      "valeur_statistique": s2(a.stat_value), "masse_nette": str(a.net), "masse_brute": str(a.gross),
                      "quantite_unite_supplementaire": None if a.qty_sup is None else _qty(a.qty_sup),
                      "unite": a.unit_sup, "nombre_colis": a.packages} for a in d.articles],
        "taxations": [{"article": t.article, "type_taxe": t.code, "categorie": t.categorie,
                       "base_montant": None if t.base_montant is None else s2(t.base_montant),
                       "base_quantite": None if t.base_quantite is None else _qty(t.base_quantite),
                       "base_unite": t.base_unite, "taux": _taux_str(t.taux), "taux_nature": t.taux_nature,
                       "montant": s2(t.montant), "mode_paiement": t.mp, "paiement_normalise": t.paiement}
                      for t in d.taxes],
        "totaux_par_type": {k: s2(ov.get(f"cat:{k}", v)) for k, v in sorted(d.cat_totals.items())},
        "total_droits_taxes": s2(ov.get("total_droits_taxes", d.total_droits_taxes)),
        "total_a_payer": s2(ov.get("total_a_payer", d.total_a_payer)),
    }


def _ftline(l):
    out = {"nature": l.nature, "libelle": l.libelle, "quantite": _qty(l.qty), "prix_unitaire": s2(l.unit_price),
           "montant_ht": s2(l.montant_ht), "taux_tva": _taux_str(l.taux_tva), "montant_tva": s2(l.montant_tva),
           "marqueur_tva": l.marker, "mrn": l.mrn}
    if l.hs:
        out["code_marchandise"] = l.hs
    if l.base_droit is not None:
        out["base_droit"] = s2(l.base_droit)
    if l.base_tva is not None:
        out["base_tva"] = s2(l.base_tva)
    if l.date_debut:
        out["date_debut"] = l.date_debut.isoformat()
        out["date_fin"] = l.date_fin.isoformat()
    return out


def tv_ft(ft):
    return {
        "numero": ft.numero, "date": ft.date.isoformat(), "emetteur.tva": ft.emetteur.vat,
        "emetteur.nom": ft.emetteur.name, "client_facture.tva": ft.client.vat, "client_facture.nom": ft.client.name,
        "refs_mrn": list(ft.refs_mrn), "refs_transport": list(ft.refs_transport), "devise": "EUR",
        "lignes": [_ftline(l) for l in ft.lines],
        "total_debours": s2(ft.total_debours), "total_debours_imprime": ft.total_debours_printed,
        "total_ht": s2(ft.printed("total_ht")), "total_tva": s2(ft.printed("total_tva")),
        "total_ttc": s2(ft.printed("total_ttc")), "acompte": s2(ft.acompte),
        "net_a_payer": s2(ft.printed("net_a_payer")), "est_releve": ft.est_releve,
    }


def tv_av(av):
    return {
        "numero": av.numero, "date": av.date.isoformat(), "emetteur.tva": av.emetteur.vat,
        "refs_facture_origine": list(av.refs_origin), "refs_mrn": list(av.refs_mrn),
        "lignes": [{"nature": l.nature, "libelle": l.libelle, "montant_ht": s2(l.montant_ht),
                    "taux_tva": _taux_str(l.taux_tva), "montant_tva": s2(l.montant_tva)} for l in av.lines],
        "total_credite_ht": s2(av.total_ht), "total_tva": s2(av.total_tva),
        "total_credite_ttc": s2(av.printed("total_ttc")), "devise": "EUR", "motif": av.motif,
    }


def tv_support(s):
    dd = s.data
    out = {"sous_type": s.sous_type}
    if s.sous_type == "titre_transport":
        out.update({"ref_transport": dd["ref"], "nombre_colis": dd["packages"], "masse_brute": str(dd["gross"])})
    elif s.sous_type == "liste_colisage":
        out.update({"refs_facture": [dd["ref"]], "nombre_colis": dd["packages"], "masse_brute": str(dd["gross"]),
                    "ref_transport": dd["transport_ref"]})
    elif s.doc_type == "document_non_exploitable":
        out.update({"motif_non_exploitable": s.sous_type})
    return out


# ======================================================================
# Niveaux attendus et finalisation
# ======================================================================

def finalize_errors(dm, doc_meta):
    """doc_meta : doc_id -> {'degradation': .., 'structured': bool}."""
    did = dm.plan["id"]

    def deg_ok(docs):
        for x in docs:
            m = doc_meta.get(x)
            if m is None:
                continue
            if not (m["structured"] or m["degradation"] in ("d0", "d1")):
                return False
        return True

    decl_by_id = dm.decl_by_id
    out = []
    by_key = {}
    # niveau sans dépendances d'abord
    for e in dm.errors:
        ctl = e["control"]
        elig = ctl in CERTAIN_ELIGIBLE and e["eligible"]
        explicit = True
        if ctl.startswith("A") or ctl == "F5":
            ds = [decl_by_id[x] for x in e["documents"] if x in decl_by_id]
            explicit = all(_explicit(dm, d) for d in ds) if ds else False
        if ctl.startswith("C") or ctl in ("G4", "G5"):
            for x in e["documents"]:
                if x in decl_by_id:
                    d = decl_by_id[x]
                    ft = next((f for f in dm.fts if f.doc_id in e["documents"]), None)
                    if ft is not None and not any(m[:15] == d.mrn[:15] for m in ft.refs_mrn):
                        explicit = False
        gap_ok = e["whole"] or (e["gap"] is not None and e["thr"] is not None and abs(e["gap"]) >= 3 * e["thr"])
        if e["amount"] is not None and e["nature"] == "recouvrable" and e["amount"] < 0:
            gap_ok = False  # écart en faveur du client : toujours à vérifier
        certain = elig and deg_ok(e["documents"]) and gap_ok and not e["confusion"] and explicit
        e["level"] = "ecart_certain" if certain else "a_verifier"
        by_key[e["key"]] = e
    for e in dm.errors:
        if e["control"] == "C6" and e.get("depends_on"):
            if not all(by_key.get(k, {}).get("level") == "ecart_certain" for k in e["depends_on"]):
                e["level"] = "a_verifier"
        if e["control"] == "C6" and not e.get("depends_on"):
            e["level"] = "a_verifier"
    n = 0
    order = {"P": 0, "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6, "G": 7}
    errs = sorted(dm.errors, key=lambda e: (order[e["control"][0]], int(e["control"][1:]), e["key"] or ""))
    for e in errs:
        n += 1
        ctl = e["control"]
        nature = AMOUNT_NATURE.get(ctl, "aucun")
        amount = e["amount"]
        if nature in ("aucun", "renvoi"):
            amount = None
        ent = {
            "error_id": f"{did}-E{n}", "control_id": ctl, "accepted_control_ids": list(ACCEPTED[ctl]),
            "expected_level": e["level"], "expected_amount_eur": None if amount is None else s2(amount),
            "amount_nature": nature, "composante": _composante(ctl, e),
            "documents": list(e["documents"]), "fields": list(e["fields"]), "injection": e["injection"],
            "description": e["description"],
        }
        if ctl in ("F2", "F3", "F4", "F5"):
            ent["other_dossiers"] = list(e["other_dossiers"] or [])
        if e.get("consequence_of"):
            ent["consequence_of"] = e["consequence_of"]
        out.append((ent, e))
    return out


def _composante(ctl, e):
    if ctl in ("A4", "A5", "A6", "F5"):
        return "valeur"
    if ctl in ("C1",):
        return "droit"
    if ctl == "C2":
        return "autre_taxe"
    if ctl in ("C3", "C4"):
        return "tva"
    if ctl in ("G1", "G2", "G4", "G5"):
        return "forfait_petits_envois"
    if ctl in ("C6", "D2", "D3", "D4", "D5", "D6", "D7", "D9", "F4"):
        return "prestation"
    if ctl == "E6":
        c = e.get("composante")
        return c if c in ("droit", "autre_taxe", "tva", "forfait_petits_envois", "prestation") else None
    if ctl == "D8":
        return "tva"
    return None


def totals_and_outcome(entries):
    cert = D0
    av = D0
    for ent, e in entries:
        if ent["amount_nature"] != "recouvrable" or ent["expected_amount_eur"] is None:
            continue
        if e.get("exclude_totals") or e.get("replaced_by_e6"):
            continue
        amt = D(ent["expected_amount_eur"])
        if amt <= 0:
            continue
        if ent["expected_level"] == "ecart_certain":
            cert += amt
        else:
            av += amt
    ctls = [ent["control_id"] for ent, _ in entries]
    if "P1" in ctls:
        outcome = "document_manquant"
    elif any(ent["expected_level"] == "ecart_certain" for ent, _ in entries):
        outcome = "ecart_certain"
    elif entries:
        outcome = "a_verifier"
    else:
        outcome = "conforme"
    return {"recouvrable_certain_eur": s2(cert), "recouvrable_a_verifier_eur": s2(av)}, outcome
