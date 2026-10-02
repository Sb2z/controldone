"""Injection des erreurs du catalogue (SPEC §19.5) dans le modèle d'un dossier."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from .build import (VAT_RATE, _alloc_to, _conv, _lbl, _marker, _presta, compute_taxes, debours_lines, faf_amount,
                    faf_base, ft_number, make_faf_line, recompute_decl_totals)
from .clients import grid_poste
from .common import (D, D0, ZERO_DEC_CURRENCIES, CONF_CLASSES, is_confusion_variant, make_awb, make_mrn, q0, q2, q3,
                     qcur, transpose_digits)
from .model import OFF_GRID, CreditNote, FTLine, ForwarderInvoice, Party, SupportDoc, composante_of
from .refdata import PRODUCTS_BY_KEY

INCOTERMS = ["EXW", "FCA", "FOB", "FAS", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"]
CUR_SWAP = {"EUR": "USD", "USD": "CNY", "CNY": "USD", "GBP": "USD", "CHF": "EUR", "INR": "USD", "TRY": "EUR",
            "CAD": "USD", "JPY": "USD", "KRW": "USD"}


def _ci0(dm):
    return dm.shipments[0]["cis"][0]


def _d0(dm):
    return dm.final_decls[0]


def _explicit(dm, d):
    from .common import D as _D  # noqa
    for ci in dm.shipments[d.shipment]["cis"]:
        if not any(_ref_compatible(ref, ci.numero) for code, ref in d.doc_refs if code in ("N380", "N325")):
            return False
    return True


def norm_ref(s):
    return "".join(ch for ch in s.upper() if ch.isalnum())


def _ref_compatible(a, b):
    na, nb = norm_ref(a), norm_ref(b)
    if na == nb:
        return True
    short, long_ = (na, nb) if len(na) <= len(nb) else (nb, na)
    return len(short) >= 5 and short in long_


def rescale_decl(dm, d, new_total, keep_currency=True):
    quant = Decimal(1) if d.currency in ZERO_DEC_CURRENCIES else Decimal("0.01")
    vals = _alloc_to([a.amount for a in d.articles], new_total, quant)
    for a, v in zip(d.articles, vals):
        a.amount = v
        a.stat_value = v if d.currency == "EUR" else _conv(v, d.eur_per_unit)
    d.total_invoiced = new_total
    compute_taxes(dm, d, keep_mp=dm._mp_main)


def _confusion_sub(value: Decimal, r, currency):
    """Substitution d'un chiffre par un autre de la même classe de confusion (§8.5.4)."""
    dec = 0 if currency in ZERO_DEC_CURRENCIES else 2
    s = f"{value:.{dec}f}"
    ip = s.split(".")[0]
    for pos in range(len(ip)):
        ch = ip[pos]
        for cls in CONF_CLASSES:
            if ch in cls:
                opts = sorted(c for c in cls if c != ch and not (pos == 0 and c == "0"))
                if opts:
                    lst = list(ip)
                    lst[pos] = opts[0]
                    return D("".join(lst) + s[len(ip):])
    return value


# ======================================================================
# Déclaration : A, B, G1–G3, G6, F5
# ======================================================================

def inject_declaration(dm):
    p = dm.plan
    r = dm.r
    d = _d0(dm)
    cis = dm.shipments[d.shipment]["cis"]
    ci = cis[0]
    fc_ids = [c.doc_id for c in cis]
    facture = sum((c.total for c in cis), D0)
    for e in p["errors"]:
        ctl = e["control"]
        inj = e["injection"]
        docs = fc_ids + [d.doc_id]
        if ctl == "A3":
            newcur = CUR_SWAP.get(d.currency, "USD")
            if newcur == ci.currency:
                newcur = "GBP"
            d.currency = newcur
            if newcur != "EUR":
                from .build import _rate_print
                d.rate_printed, d.eur_per_unit = _rate_print(dm, newcur, p["rate_sens"])
                d.rate_sens = p["rate_sens"]
            else:
                d.rate_printed, d.rate_sens, d.eur_per_unit = None, None, Decimal(1)
            for a in d.articles:
                a.stat_value = a.amount if d.currency == "EUR" else _conv(a.amount, d.eur_per_unit)
            compute_taxes(dm, d, keep_mp=dm._mp_main)
            dm.add_error("A3", inj, docs, whole=True, fields=[f"{d.doc_id}.devise_facture"],
                         description=f"Devise déclarée {newcur} au lieu de {ci.currency} (montant identique).",
                         key="A3")
        elif ctl == "A4":
            old = d.total_invoiced
            if inj == "valeur_transposee":
                new = transpose_digits(old, r, d.currency)
            elif r.random() < 0.18:
                new = _confusion_sub(old, r, d.currency)
            else:
                f = D(r.choice([1, -1]) * r.uniform(0.03, 0.18)).quantize(Decimal("0.0001"))
                new = qcur(old * (1 + f), d.currency)
            if abs(new - old) <= max(Decimal(1), old * Decimal("0.001")) or new <= 0:
                new = qcur(old * Decimal("1.07"), d.currency)
            # ne jamais égaler une ligne de pied
            for v in ci.footer.values():
                if abs(abs(new - old) - v) <= max(Decimal(1), facture * Decimal("0.001")):
                    new = new + qcur(Decimal("37"), d.currency)
            rescale_decl(dm, d, new)
            gap = new - facture
            amount = q2(gap) if d.currency == "EUR" else q2(gap * d.eur_per_unit)
            dm.add_error("A4", inj, docs, amount=amount, nature="ecart_documentaire", composante="valeur",
                         gap=abs(gap), thr=max(Decimal(5), facture * Decimal("0.005")),
                         confusion=is_confusion_variant(str(old), str(new)),
                         fields=[f"{d.doc_id}.montant_total_facture"],
                         description=f"Montant facturé déclaré {new} au lieu de {old} {d.currency}.", key="A4")
        elif ctl == "A5":
            attendu = q2(facture * d.eur_per_unit)
            if r.random() < 0.35 and d.rate_sens == "devise_par_eur":
                new = q2(facture * d.rate_printed)
            elif r.random() < 0.35 and d.rate_sens == "eur_par_devise":
                new = q2(facture / d.rate_printed)
            else:
                f = D(r.choice([1, -1]) * r.uniform(0.02, 0.12)).quantize(Decimal("0.0001"))
                new = q2(attendu * (1 + f))
            rescale_decl(dm, d, new)
            gap = new - attendu
            dm.add_error("A5", inj, docs, amount=q2(gap), nature="ecart_documentaire", composante="valeur",
                         gap=abs(gap), thr=max(Decimal(5), attendu * Decimal("0.005")),
                         fields=[f"{d.doc_id}.montant_total_facture", f"{d.doc_id}.taux_change"],
                         description=f"Montant converti {new} EUR ; attendu {attendu} EUR au taux imprimé.",
                         key="A5")
        elif ctl == "A6":
            if d.rate_printed is None:
                from .build import _rate_print
                d.rate_printed, d.eur_per_unit = _rate_print(dm, ci.currency, p["rate_sens"])
                d.rate_sens = p["rate_sens"]
            d.currency = "EUR"
            new = q2(facture)
            rescale_decl(dm, d, new)
            attendu = q2(facture * d.eur_per_unit)
            gap = new - attendu
            dm.add_error("A6", inj, docs, amount=q2(gap), nature="ecart_documentaire", composante="valeur",
                         gap=abs(gap), thr=max(Decimal(5), attendu * Decimal("0.005")),
                         fields=[f"{d.doc_id}.devise_facture", f"{d.doc_id}.montant_total_facture"],
                         description=f"Montant {facture} {ci.currency} repris tel quel en EUR.", key="A6")
        elif ctl == "A7":
            attendu = q2(facture * d.eur_per_unit)
            fct = D(r.choice(["0.45", "0.5", "1.9", "2.4", "10"]))
            new = q2(attendu * fct)
            rescale_decl(dm, d, new)
            dm.add_error("A7", inj, docs, amount=None, nature="aucun", eligible=False,
                         fields=[f"{d.doc_id}.montant_total_facture"],
                         description=f"Montant EUR déclaré {new} sans taux imprimé, rapport {fct} à l'ordre de grandeur.",
                         key="A7")
        elif ctl == "F5":
            d2 = dm.final_decls[1]
            old2 = d2.total_invoiced
            if d2.currency == "EUR" and ci.currency != "EUR":
                new2 = q2(facture * d2.eur_per_unit)
            else:
                new2 = facture
            rescale_decl(dm, d2, new2)
            s = sum((x.total_invoiced for x in dm.final_decls[:2]), D0)
            if d.currency == "EUR":
                gap = s - (facture if ci.currency == "EUR" else q2(facture * d.eur_per_unit))
                amt = q2(gap)
                gap_units = gap
            else:
                gap_units = s - facture
                amt = q2(gap_units * d.eur_per_unit) if d.rate_printed is not None else None
            dm.add_error("F5", inj, [ci.doc_id, d.doc_id, d2.doc_id], amount=amt, nature="ecart_documentaire",
                         composante="valeur", eligible=False, other_dossiers=[],
                         fields=[f"{d2.doc_id}.montant_total_facture"],
                         description="La même facture est déclarée en totalité sur la seconde déclaration "
                                     "en plus de la première (somme déclarée supérieure au total).", key="F5")
            dm.add_error("A4", "valeur_modifiee", [ci.doc_id, d.doc_id, d2.doc_id], amount=amt,
                         nature="ecart_documentaire", composante="valeur", gap=abs(gap_units),
                         thr=max(Decimal(5), facture * Decimal("0.005")), consequence_of="F5",
                         fields=[f"{d2.doc_id}.montant_total_facture"],
                         description="Conséquence de F5 : somme des montants déclarés supérieure au total facture.",
                         key="A4F5")
    # ---- erreurs n'affectant pas les montants déclarés
    for e in p["errors"]:
        ctl = e["control"]
        inj = e["injection"]
        docs = fc_ids + [d.doc_id]
        if ctl == "A1":
            if inj == "entite_groupe_differente":
                others = [x for x in dm.reg.clients[p["client"]]["entities"] if x is not dm.entity]
                ent = r.choice(others)
            else:
                ent = dm.reg.third_party
            d.importer = Party(ent.name, ent.addr, "FR", ent.vat, ent.siren, ent.eori)
            d.doc_refs = [(c, (ent.vat if c in ("1008", "FR7") else ref)) for c, ref in d.doc_refs]
            dm.add_error("A1", inj, docs, whole=True, fields=[f"{d.doc_id}.importateur.tva"],
                         description=f"Importateur déclaré {ent.vat} ({ent.name}) ; facture adressée à {dm.entity.vat}.",
                         key="A1")
        elif ctl == "A2":
            d.doc_refs = [(c, ref) for c, ref in d.doc_refs if c not in ("N380", "N325")]
            dm.add_error("A2", inj, docs, eligible=False, fields=[f"{d.doc_id}.documents_references"],
                         description="La déclaration ne cite pas la référence de la facture.", key="A2")
        elif ctl == "A8":
            new = r.choice([i for i in INCOTERMS if i != d.incoterm])
            old = d.incoterm
            d.incoterm = new
            dm.add_error("A8", inj, docs, eligible=False, fields=[f"{d.doc_id}.incoterm"],
                         description=f"Incoterm {new} sur la déclaration, {old} sur la facture.", key="A8")
        elif ctl == "A9":
            arts = [a for a in d.articles if a.qty_sup is not None] or d.articles
            a = r.choice(arts)
            base = a.qty_sup if a.qty_sup is not None else a.qty_total
            if base >= 10 and r.random() < 0.5:
                new = base + max(D(2), (base * Decimal("0.1")).quantize(Decimal(1)))
            else:
                new = base * 2
            a.qty_sup = new
            if a.unit_sup is None:
                a.unit_sup = "p/st"
            dm.add_error("A9", inj, docs, eligible=False, fields=[f"{d.doc_id}.articles[{a.no - 1}].quantite"],
                         description=f"Article {a.no} : quantité {new} au lieu de {base}.", key="A9")
        elif ctl == "A10":
            f = D(r.uniform(1.15, 1.45)).quantize(Decimal("0.01"))
            for a in d.articles:
                a.gross = q3(a.gross * f)
            d.gross_total = sum((a.gross for a in d.articles), D0)
            dm.add_error("A10", inj, docs + [s.doc_id for s in dm.supports if s.sous_type == "titre_transport"][:0],
                         eligible=False, fields=[f"{d.doc_id}.masse_brute_totale"],
                         description=f"Masses brutes de la déclaration multipliées par {f}.", key="A10")
        elif ctl == "A11":
            k = r.randint(1, 4)
            d.packages_total += k
            d.articles[0].packages += k
            dm.add_error("A11", inj, docs, eligible=False, fields=[f"{d.doc_id}.nombre_colis_total"],
                         description=f"Nombre de colis déclaré {d.packages_total}, facture {ci.packages}.", key="A11")
        elif ctl == "A12":
            a = r.choice(d.articles)
            old = a.origin
            a.origin = r.choice([c for c in ("VN", "TH", "MY", "IN", "TR", "ID", "BD", "KH") if c != old])
            dm.add_error("A12", inj, docs, nature="renvoi", eligible=False,
                         fields=[f"{d.doc_id}.articles[{a.no - 1}].pays_origine"],
                         description=f"Article {a.no} : origine {a.origin}, facture {old}.", key="A12")
        elif ctl == "A13":
            a = r.choice(d.articles)
            old6 = a.hs10[:6]
            ci_codes6 = {l.hs10[:6] for c in cis for l in c.lines}
            for _ in range(200):
                cand = old6[:4] + f"{r.randint(10, 99)}"
                if cand != old6 and cand not in ci_codes6 and not is_confusion_variant(old6, cand):
                    break
            a.hs10 = cand + a.hs10[6:]
            dm.add_error("A13", inj, docs, nature="renvoi", eligible=False,
                         fields=[f"{d.doc_id}.articles[{a.no - 1}].code_marchandise"],
                         description=f"Article {a.no} : code {a.hs10}, facture {old6}.", key="A13")
        elif ctl == "A14":
            dm.add_error("A14", inj, docs, eligible=False, fields=[f"{d.doc_id}.date_acceptation"],
                         description=f"Déclaration acceptée le {d.date}, facture du {ci.date}.", key="A14")
        elif ctl == "A15":
            arts = [a for a in d.articles if a.line_refs]
            a = r.choice(arts)
            drop = a.line_refs[0]
            prod = a.desc.split(" REF ")[0]
            rest = a.line_refs[1:]
            wrong = drop[:-1] + ("Z" if drop[-1] != "Z" else "Y")
            a.desc = f"{prod} REF {', '.join([wrong] + rest)}"
            dm.add_error("A15", inj, docs, eligible=False, fields=[f"{d.doc_id}.articles[{a.no - 1}].description"],
                         description=f"Référence {drop} absente des désignations (remplacée par {wrong}).",
                         key="A15")
        elif ctl == "B1":
            cands = [t for t in d.taxes if t.categorie != "forfait_petits_envois" and t.base_montant
                     and t.montant > 0 and t.taux_nature == "ad_valorem"]
            t = r.choice(cands)
            calc = t.base_montant * t.taux / 100
            mode = r.random()
            if mode < 0.2:
                new = transpose_digits(t.montant, r)
            elif mode < 0.35:
                new = q2(t.montant + D(r.choice([1, -1]) * r.uniform(1.2, 2.8)))
            else:
                new = q2(t.montant + D(r.choice([1, 1, -1]) * r.uniform(3.5, 95)))
            fl, ce, rd = calc.to_integral_value(rounding="ROUND_FLOOR"), calc.to_integral_value(
                rounding="ROUND_CEILING"), q0(calc)
            if new <= 0 or abs(new - calc) <= Decimal("1.05") or new in (fl, ce, rd):
                new = q2(t.montant + Decimal("12.40"))
            old = t.montant
            t.montant = new
            recompute_decl_totals(d)
            amt = q2(new - calc)
            dm.add_error("B1", inj, [d.doc_id], amount=amt, nature="arithmetique_declaration", gap=abs(amt),
                         thr=Decimal(1), confusion=is_confusion_variant(str(old), str(new)),
                         fields=[f"{d.doc_id}.taxations[{d.taxes.index(t)}].montant"],
                         description=f"Taxe {t.code} article {t.article} : montant {new}, base × taux = {q2(calc)}.",
                         key="B1")
        elif ctl == "B2":
            delta = q2(D(r.uniform(4, 160)))
            if d.layout in ("L1", "L3", "X1", "X2") and "A00" in d.cat_totals:
                d.printed_totals_override["cat:A00"] = d.cat_totals["A00"] - delta
                fld = f"{d.doc_id}.total_A00"
                desc = f"Total imprimé des droits A00 {d.cat_totals['A00'] - delta} ; somme des lignes {d.cat_totals['A00']}."
            else:
                d.printed_totals_override["total_a_payer"] = d.total_a_payer - delta
                d.printed_totals_override["total_droits_taxes"] = d.total_droits_taxes - delta
                fld = f"{d.doc_id}.total_a_payer"
                desc = f"Total à payer imprimé {d.total_a_payer - delta} ; somme des lignes {d.total_a_payer}."
            dm.add_error("B2", inj, [d.doc_id], amount=-delta, nature="arithmetique_declaration", gap=delta,
                         thr=Decimal(1), fields=[fld], description=desc, key="B2")
        elif ctl == "B3":
            a = r.choice(d.articles)
            unit = Decimal(1) if d.currency in ZERO_DEC_CURRENCIES else Decimal("0.01")
            delta = max((a.amount * D(r.uniform(0.03, 0.12))).quantize(unit), D(25))
            a.amount += delta
            amt = -delta if d.currency == "EUR" else q2(-delta * d.eur_per_unit)
            dm.add_error("B3", inj, [d.doc_id], amount=q2(amt), nature="arithmetique_declaration",
                         gap=abs(q2(amt)), thr=Decimal(1), fields=[f"{d.doc_id}.articles[{a.no - 1}].montant_facture"],
                         description=f"Article {a.no} : montant facturé augmenté de {delta} sans changer le total.",
                         key="B3")
        elif ctl == "B4":
            arts = sorted(d.articles, key=lambda a: -a.net)
            k_art = arts[-1] if len(arts) > 1 else arts[0]
            j_art = arts[0] if arts[0] is not k_art else None
            delta = q3(max(D(5), k_art.gross * Decimal("0.06")))
            if j_art is not None and j_art.net - delta < Decimal("0.5"):
                delta = q3(j_art.net / 2)
            k_art.net = k_art.gross + delta
            if j_art is not None:
                j_art.net -= delta
            tol = max(Decimal("0.5"), k_art.gross * Decimal("0.005"))
            dm.add_error("B4", inj, [d.doc_id], gap=delta - tol, thr=Decimal(1),
                         fields=[f"{d.doc_id}.articles[{k_art.no - 1}].masse_nette"],
                         description=f"Article {k_art.no} : masse nette {k_art.net} > masse brute {k_art.gross}.",
                         key="B4")
        elif ctl == "B5":
            a = r.choice(d.articles)
            k = r.randint(1, 3)
            a.packages += k
            dm.add_error("B5", "somme_colis_incoherente", [d.doc_id], eligible=False,
                         fields=[f"{d.doc_id}.articles[{a.no - 1}].nombre_colis"],
                         description=f"Article {a.no} : {k} colis de plus que le total imprimé.", key="B5")
        elif ctl in ("G1", "G2", "G3", "G6"):
            _inject_g_decl(dm, d, ctl, inj, ci)


def _inject_g_decl(dm, d, ctl, inj, ci):
    r = dm.r
    ft = next(t for t in d.taxes if t.categorie == "forfait_petits_envois")
    n = len(d.articles)
    if ctl == "G1":
        delta = D(r.choice(["3.00", "6.00", "-3.00", "4.50", "9.00", "1.50"]))
        ft.montant = q2(ft.base_quantite * ft.taux + delta)
        recompute_decl_totals(d)
        dm.add_error("G1", inj, [d.doc_id], amount=delta, nature="arithmetique_declaration",
                     composante="forfait_petits_envois", gap=abs(delta), thr=Decimal(1),
                     fields=[f"{d.doc_id}.taxations[{d.taxes.index(ft)}].montant"],
                     description=f"Forfait : {ft.base_quantite} × {ft.taux} imprimé {ft.montant}.", key="G1")
    elif ctl == "G2":
        units = sum((a.qty_total for a in d.articles), D0)
        if units == n:
            units = D(n + 2)
        ft.base_quantite = units
        ft.montant = q2(units * ft.taux)
        recompute_decl_totals(d)
        dn = units - n
        dm.add_error("G2", inj, [d.doc_id], amount=q2(dn * ft.taux), nature="arithmetique_declaration",
                     composante="forfait_petits_envois", gap=abs(dn), thr=Decimal(1),
                     fields=[f"{d.doc_id}.taxations[{d.taxes.index(ft)}].base_quantite"],
                     description=f"Base du forfait {units} (unités) pour {n} articles.", key="G2")
        dm.add_error("G3", "forfait_codes_distincts", [d.doc_id], nature="renvoi", eligible=False,
                     consequence_of="G2", fields=[f"{d.doc_id}.taxations[{d.taxes.index(ft)}].base_quantite"],
                     description="Conséquence : la base diffère aussi du nombre de codes distincts.", key="G3G2")
    elif ctl == "G3":
        dm.add_error("G3", inj, [d.doc_id], nature="renvoi", eligible=False,
                     fields=[f"{d.doc_id}.articles"],
                     description=f"{n} positions mais {len({a.hs10 for a in d.articles})} codes distincts ; base {ft.base_quantite}.",
                     key="G3")
    elif ctl == "G6":
        docs = [d.doc_id] if d.date < dt.date(2026, 7, 1) else [ci.doc_id, d.doc_id]
        dm.add_error("G6", inj, docs, nature="renvoi", eligible=False, fields=[f"{d.doc_id}.date_acceptation"],
                     description="Forfait liquidé hors période ou au-delà du seuil de valeur.", key="G6")


# ======================================================================
# Facture du transitaire : C, D, G4, G5
# ======================================================================

def _deb_ft(dm):
    return dm.fts[0]


def _pre_ft(dm):
    if dm.plan["template"] == "T5":
        return dm.fts[1]
    return dm.fts[0]


def _line(ft, code, mrn=None):
    for l in ft.lines:
        if l.code == code and (mrn is None or l.mrn == mrn):
            return l
    return None


def _set_ht(l, ht):
    l.montant_ht = q2(ht)
    if l.qty and l.qty != 0:
        l.unit_price = q2(l.montant_ht / l.qty) if l.qty != 1 else l.montant_ht
    l.montant_tva = q2(l.montant_ht * l.taux_tva / 100)


def _delta(r, big=False):
    if big:
        return q2(D(r.uniform(220, 650)))
    x = r.random()
    if x < 0.2:
        return q2(D(r.uniform(1.2, 2.8)))
    return q2(D(r.uniform(4, 260)))


def inject_forwarder(dm):
    p = dm.plan
    r = dm.r
    tpl = p["template"]
    lang = dm.fw.lang
    d = _d0(dm)
    tref = dm.shipments[d.shipment]["cis"][0].transport_ref
    deb = _deb_ft(dm)
    pre = _pre_ft(dm)
    faf_dirty = False
    for e in p["errors"]:
        ctl, inj = e["control"], e["injection"]
        if ctl in ("C1", "C2", "C4", "C5"):
            code = {"C1": "DROITS", "C2": "AUTRES", "C4": "TVA", "C5": "COMBINES"}[ctl]
            l = _line(deb, code, d.mrn)
            if l is None and tpl == "T2" and ctl != "C5":
                cands = [x for x in deb.lines if x.code == code and x.mrn == d.mrn]
                l = cands[0] if cands else None
            if l is None:
                l = FTLine({"DROITS": "debours_droits", "AUTRES": "debours_autres_taxes", "TVA": "debours_tva",
                            "COMBINES": "debours_combines"}[code], code, _lbl(code, lang), Decimal(1), D0, D0, D0, D0,
                           _marker(tpl, "debours"), mrn=d.mrn, ref_transport=tref)
                deb.lines.insert(0, l)
            if tpl == "T2" and ctl in ("C1", "C2", "C4"):
                cands = [x for x in deb.lines if x.code == code and x.mrn == d.mrn and x.montant_ht > 0]
                if cands:
                    l = r.choice(cands)
            if e.get("big") or p.get("big_debours"):
                delta = _delta(r, big=True)
            elif r.random() < 0.15 and l.montant_ht >= 100:
                delta = transpose_digits(l.montant_ht, r) - l.montant_ht
                if abs(delta) < Decimal("1.10") or delta < 0:
                    delta = _delta(r)
            else:
                delta = _delta(r)
            _set_ht(l, l.montant_ht + delta)
            faf_dirty = True
            dm.add_error(ctl, inj, [deb.doc_id, d.doc_id], nature="recouvrable",
                         composante={"C1": "droit", "C2": "autre_taxe", "C4": "tva", "C5": None}[ctl],
                         thr=Decimal(1), fields=[f"{deb.doc_id}.lignes[{deb.lines.index(l)}].montant_ht"],
                         description=f"{l.libelle} refacturé(e) {l.montant_ht} (excédent {delta}).",
                         key=f"{ctl}:{d.doc_id}")
        elif ctl == "C3":
            vat = sum((t.montant for t in d.taxes if t.categorie == "tva"), D0)
            l = FTLine("debours_tva", "TVA", _lbl("TVA", lang), Decimal(1), vat, vat, D0, D0, _marker(tpl, "debours"),
                       mrn=d.mrn, ref_transport=tref)
            idx = max([i for i, x in enumerate(deb.lines) if x.is_debours] + [-1]) + 1
            deb.lines.insert(idx, l)
            faf_dirty = True
            dm.add_error("C3", inj, [deb.doc_id, d.doc_id], nature="recouvrable", composante="tva", thr=Decimal(1),
                         fields=[f"{deb.doc_id}.lignes[{idx}].montant_ht", f"{d.doc_id}.indices_autoliquidation"],
                         description="TVA refacturée alors que la déclaration porte l'indice d'autoliquidation.",
                         key=f"C3:{d.doc_id}")
        elif ctl in ("G4", "G5"):
            l = _line(deb, "FORFAIT", d.mrn)
            tx = next(t for t in d.taxes if t.categorie == "forfait_petits_envois")
            if ctl == "G4":
                k = r.randint(1, 3)
                newv = l.montant_ht + Decimal(3) * k
                l.qty, l.unit_price, l.montant_ht, l.detail = Decimal(1), newv, newv, ""
                dm.add_error("G4", inj, [deb.doc_id, d.doc_id], nature="recouvrable",
                             composante="forfait_petits_envois", thr=Decimal(1),
                             fields=[f"{deb.doc_id}.lignes[{deb.lines.index(l)}].montant_ht"],
                             description=f"Forfait refacturé {newv}, liquidé {tx.montant}.", key=f"G4:{d.doc_id}")
            else:
                units = sum((a.qty_total for a in d.articles), D0)
                if units <= tx.base_quantite:
                    units = tx.base_quantite + 2
                l.qty, l.unit_price = units, tx.taux
                l.montant_ht = q2(units * tx.taux)
                l.detail = f"{tx.taux} x {units}"
                amt = q2((units - tx.base_quantite) * tx.taux)
                dm.add_error("G5", inj, [deb.doc_id, d.doc_id], amount=amt, nature="recouvrable",
                             composante="forfait_petits_envois", gap=amt, thr=Decimal(1),
                             fields=[f"{deb.doc_id}.lignes[{deb.lines.index(l)}].quantite"],
                             description=f"Base de refacturation {units} unités pour {tx.base_quantite} articles.",
                             key=f"G5:{d.doc_id}")
            faf_dirty = True
    # piège d'arrondi sous tolérance (C1)
    if p["round_trap"] and not any(e["control"] in ("C1", "C5") for e in p["errors"]):
        l = _line(deb, "DROITS", d.mrn) or _line(deb, "COMBINES", d.mrn)
        if l is not None and l.montant_ht > 0:
            _set_ht(l, l.montant_ht + Decimal("0.03"))
            dm.trap_round = True
    if faf_dirty and not dm.has("D4"):
        refresh_faf(dm)
    for e in p["errors"]:
        ctl, inj = e["control"], e["injection"]
        if ctl == "D2":
            v = r.choice(OFF_GRID["autre_prestation"])
            amt = q2(D(r.choice(["18.00", "25.00", "29.50", "35.00", "45.00", "60.00"])))
            l = _presta(dm, "DEDOUANEMENT", lang, tpl, 1, amt, mrn=d.mrn, tref=tref, nature="autre_prestation",
                        libelle=v[lang])
            l.code = "HORS_GRILLE"
            pre.lines.append(l)
            dm.add_error("D2", inj, [pre.doc_id], amount=amt, nature="recouvrable", composante="prestation",
                         gap=amt, thr=Decimal("0.10"), eligible=dm.grid["prestations_hors_grille"] == "interdites",
                         fields=[f"{pre.doc_id}.lignes[{len(pre.lines) - 1}]"],
                         description=f"Ligne hors grille « {l.libelle} » {amt}.", key="D2")
        elif ctl == "D3":
            l = _line(pre, "DEDOUANEMENT", d.mrn) if (e.get("for_avoir") or r.random() < 0.6) else (
                _line(pre, "TRANSPORT") or _line(pre, "DEDOUANEMENT", d.mrn))
            if r.random() < 0.15 and not e.get("for_avoir"):
                delta = q2(D(r.uniform(0.12, 0.28)))
            else:
                delta = q2(D(r.uniform(5, 30)))
            _set_ht(l, l.montant_ht + delta * l.qty)
            l.unit_price = l.unit_price if l.qty != 1 else l.montant_ht
            dm.add_error("D3", inj, [pre.doc_id], amount=q2(delta * l.qty), nature="recouvrable",
                         composante="prestation", gap=q2(delta * l.qty), thr=Decimal("0.10"),
                         fields=[f"{pre.doc_id}.lignes[{pre.lines.index(l)}].montant_ht"],
                         description=f"{l.libelle} facturé {l.montant_ht}, grille {l.montant_ht - delta * l.qty}.",
                         key="D3")
            dm.d3_line = l
        elif ctl == "D4":
            l = _line(pre, "AVANCE_FONDS", None)
            pst = grid_poste(dm.grid, "AVANCE_FONDS")
            deb_lines = [x for x in deb.lines if x.is_debours and (x.mrn == l.mrn or l.mrn is None)]
            base = faf_base(dm.grid, deb_lines)
            att = faf_amount(dm.grid, base)
            pct = D(pst["pourcentage"]) + D(r.choice(["0.5", "1.0", "1.5"]))
            billed = q2(pct * base / 100)
            if pst["maximum"] is not None:
                billed = min(billed, D(pst["maximum"]) + D(r.choice(["15.00", "40.00"])))
            if billed - att < Decimal("0.5"):
                billed = att + D(r.choice(["5.00", "10.00", "12.50"]))
            _set_ht(l, billed)
            l.detail = f"{pct} % x {base}"
            dm.add_error("D4", inj, [pre.doc_id, deb.doc_id], amount=q2(billed - att), nature="recouvrable",
                         composante="prestation", gap=q2(billed - att), thr=Decimal("0.10"),
                         fields=[f"{pre.doc_id}.lignes[{pre.lines.index(l)}].montant_ht"],
                         description=f"Avance de fonds facturée {billed}, grille {att}.", key="D4")
        elif ctl == "D5":
            cands = [x for x in pre.lines if x.code in ("DEDOUANEMENT", "MANUTENTION", "TRANSPORT", "SURCHARGE_SURETE")]
            l = r.choice(cands)
            dup = FTLine(l.nature, l.code, l.libelle, l.qty, l.unit_price, l.montant_ht, l.taux_tva, l.montant_tva,
                         l.marker, mrn=l.mrn, ref_transport=l.ref_transport, detail=l.detail)
            pre.lines.insert(pre.lines.index(l) + 1, dup)
            dm.add_error("D5", inj, [pre.doc_id], amount=l.montant_ht, nature="recouvrable", composante="prestation",
                         gap=l.montant_ht, thr=Decimal("0.10"),
                         fields=[f"{pre.doc_id}.lignes[{pre.lines.index(dup)}]"],
                         description=f"Ligne « {l.libelle} » {l.montant_ht} facturée deux fois.", key="D5")
        elif ctl == "D6":
            l = _line(pre, "MAGASINAGE")
            mg = grid_poste(dm.grid, "MAGASINAGE")
            total_days = (l.date_fin - l.date_debut).days + 1
            new_days = total_days if r.random() < 0.6 else l.qty + r.randint(2, 4)
            extra = D(new_days) - l.qty
            l.qty = D(new_days)
            _set_ht(l, l.qty * D(mg["prix"]))
            l.unit_price = D(mg["prix"])
            amt = q2(extra * D(mg["prix"]))
            dm.add_error("D6", inj, [pre.doc_id], amount=amt, nature="recouvrable", composante="prestation", gap=amt,
                         thr=Decimal("0.10"), fields=[f"{pre.doc_id}.lignes[{pre.lines.index(l)}].quantite"],
                         description=f"Magasinage {new_days} jours facturés, {total_days - mg['franchise_jours']} attendus.",
                         key="D6")
        elif ctl == "D7":
            fu = _line(pre, "SURCHARGE_CARBURANT")
            if fu is not None and r.random() < 0.5:
                tp = _line(pre, "TRANSPORT")
                pst = grid_poste(dm.grid, "SURCHARGE_CARBURANT")
                newpct = D(pst["pourcentage"]) + D(r.choice(["4.0", "6.0", "8.0"]))
                old = fu.montant_ht
                _set_ht(fu, q2(tp.montant_ht * newpct / 100))
                fu.detail = f"{newpct} %"
                amt = q2(fu.montant_ht - old)
                dm.add_error("D7", inj, [pre.doc_id], amount=amt, nature="recouvrable", composante="prestation",
                             gap=amt, thr=Decimal("0.10"), fields=[f"{pre.doc_id}.lignes[{pre.lines.index(fu)}]"],
                             description=f"Surcharge carburant {newpct} % au lieu de {pst['pourcentage']} %.",
                             key="D7")
            else:
                v = r.choice(OFF_GRID["surcharge"])
                amt = q2(D(r.choice(["22.00", "35.00", "48.00", "65.00"])))
                l = _presta(dm, "SURCHARGE_SURETE", lang, tpl, 1, amt, mrn=d.mrn, tref=tref, nature="surcharge",
                            libelle=v[lang])
                l.code = "SURCHARGE_HORS_GRILLE"
                pre.lines.append(l)
                dm.add_error("D7", inj, [pre.doc_id], amount=amt, nature="recouvrable", composante="prestation",
                             gap=amt, thr=Decimal("0.10"),
                             eligible=dm.grid["prestations_hors_grille"] == "interdites",
                             fields=[f"{pre.doc_id}.lignes[{len(pre.lines) - 1}]"],
                             description=f"Surcharge non prévue « {l.libelle} » {amt}.", key="D7")
        elif ctl == "D8":
            cands = [x for x in deb.lines if x.is_debours and x.montant_ht > 0 and x.mrn == d.mrn]
            l = cands[0]
            l.taux_tva = VAT_RATE
            l.montant_tva = q2(l.montant_ht * VAT_RATE / 100)
            l.marker = _marker(tpl, "presta")
            dm.add_error("D8", inj, [deb.doc_id], amount=l.montant_tva, nature="recouvrable", composante=None,
                         eligible=False, exclude_totals=False,
                         fields=[f"{deb.doc_id}.lignes[{deb.lines.index(l)}].montant_tva"],
                         description=f"TVA {l.montant_tva} facturée sur la ligne de débours « {l.libelle} ».",
                         key="D8")
        elif ctl == "D9":
            ls = grid_poste(dm.grid, "LIGNE_SUP")
            l = _line(pre, "LIGNE_SUP", d.mrn)
            k = r.randint(2, 4)
            if l is None:
                l = _presta(dm, "LIGNE_SUP", lang, tpl, k, D(ls["prix"]), mrn=d.mrn, tref=tref)
                pre.lines.insert(1, l)
            else:
                l.qty += k
                _set_ht(l, l.qty * D(ls["prix"]))
                l.unit_price = D(ls["prix"])
            l.detail = f"{len(d.articles) + k} art. - {ls['inclus']} inclus" if len(d.articles) + k > ls["inclus"] else ""
            amt = q2(k * D(ls["prix"]))
            dm.add_error("D9", inj, [pre.doc_id, d.doc_id], amount=amt, nature="recouvrable",
                         composante="prestation", gap=amt, thr=Decimal("0.10"),
                         fields=[f"{pre.doc_id}.lignes[{pre.lines.index(l)}].quantite"],
                         description=f"{l.qty} lignes supplémentaires facturées pour {len(d.articles)} articles "
                                     f"({ls['inclus']} inclus).", key="D9")
        elif ctl == "C7":
            if r.random() < 0.7:
                bad = make_mrn(r, 2026)
                deb.refs_mrn.append(bad)
                dm.add_error("C7", inj, [deb.doc_id], eligible=False, fields=[f"{deb.doc_id}.refs_mrn"],
                             description=f"MRN {bad} cité sans déclaration correspondante.", key="C7")
            else:
                bad = make_awb(r)
                deb.refs_transport.append(bad)
                dm.add_error("C7", inj, [deb.doc_id], eligible=False, fields=[f"{deb.doc_id}.refs_transport"],
                             description=f"Référence de transport {bad} citée sans correspondance.", key="C7")
        elif ctl == "C8":
            if p["client"] == "CL01" and r.random() < 0.7:
                others = [x for x in dm.reg.clients["CL01"]["entities"] if x is not dm.entity]
                ent = r.choice(others)
            else:
                ent = dm.reg.third_party
            for ft in dm.fts:
                ft.client = Party(ent.name, ent.addr, "FR", ent.vat, ent.siren, ent.eori)
            dm.add_error("C8", inj, [dm.fts[0].doc_id], whole=True, fields=[f"{dm.fts[0].doc_id}.client_facture.tva"],
                         description=f"Facture adressée à {ent.vat} ; importateur {d.importer.vat}.", key="C8")
    for ft in dm.fts:
        ft.recompute()
    for e in p["errors"]:
        if e["control"] == "D1":
            ft = pre
            delta = q2(D(r.uniform(1.2, 2.8))) if r.random() < 0.2 else q2(D(r.uniform(3.5, 75)))
            if r.random() < 0.5:
                ft.printed_override["total_ttc"] = ft.total_ttc + delta
                ft.printed_override["net_a_payer"] = ft.total_ttc + delta - ft.acompte
                fld = "total_ttc"
            else:
                ft.printed_override["total_ht"] = ft.total_ht + delta
                ft.printed_override["total_ttc"] = ft.total_ttc + delta
                ft.printed_override["net_a_payer"] = ft.net_a_payer + delta
                fld = "total_ht"
            dm.add_error("D1", e["injection"], [ft.doc_id], amount=delta, nature="recouvrable", composante=None,
                         gap=delta, thr=Decimal(1), fields=[f"{ft.doc_id}.{fld}"],
                         description=f"{fld} imprimé supérieur de {delta} à la somme recalculée.", key="D1")


def refresh_faf(dm):
    """Frais d'avance de fonds recalculés sur les débours effectivement refacturés."""
    deb_ft = _deb_ft(dm)
    pre_ft = _pre_ft(dm)
    all_deb = [l for ft in dm.fts if ft.kind != "rebill" for l in ft.lines if l.is_debours]
    for l in pre_ft.lines:
        if l.code != "AVANCE_FONDS":
            continue
        deb = [x for x in all_deb if l.mrn is None or x.mrn == l.mrn]
        base = faf_base(dm.grid, deb)
        _set_ht(l, faf_amount(dm.grid, base))
        pst = grid_poste(dm.grid, "AVANCE_FONDS")
        l.detail = f"{pst['pourcentage']} % x {base} (min {pst['minimum']})"


# ======================================================================
# Croisements F2 / F3 / F4
# ======================================================================

def inject_fpair(dm, partner):
    p = dm.plan
    r = dm.r
    kind = p["fpair"]["kind"]
    pid = partner.plan["id"]
    pft = partner.fts[0]
    pd = partner.final_decls[0]
    if kind == "F2":
        dm.fts[0].numero = pft.numero
        dm.add_error("F2", "numero_reutilise", [dm.fts[0].doc_id], eligible=False, other_dossiers=[pid],
                     fields=[f"{dm.fts[0].doc_id}.numero"],
                     description=f"Numéro {pft.numero} déjà utilisé par le même transitaire (dossier {pid}).",
                     key="F2")
        return
    lines = []
    if kind == "F3":
        for ft in partner.fts:
            for l in ft.lines:
                if l.is_debours and l.mrn == pd.mrn:
                    lines.append(FTLine(l.nature, l.code, l.libelle, l.qty, l.unit_price, l.montant_ht, l.taux_tva,
                                        l.montant_tva, l.marker, mrn=l.mrn, ref_transport=l.ref_transport,
                                        detail=l.detail, hs=l.hs, base_droit=l.base_droit, base_tva=l.base_tva))
    else:
        src = None
        for ft in partner.fts:
            for l in ft.lines:
                if l.code == "DEDOUANEMENT" and l.mrn == pd.mrn:
                    src = l
        lines.append(FTLine(src.nature, src.code, src.libelle, src.qty, src.unit_price, src.montant_ht, src.taux_tva,
                            src.montant_tva, src.marker, mrn=src.mrn, ref_transport=src.ref_transport))
    tref = partner.shipments[0]["cis"][0].transport_ref
    ftr = ForwarderInvoice("ft9", "rebill", p["template"], ft_number(dm, 5), dm.fts[0].date + dt.timedelta(days=r.randint(2, 9)),
                           dm.fw_party(), dm.entity_party(), [tref], [pd.mrn], [], lines, dm.fw.lang,
                           decl_ids=[])
    ftr.recompute()
    dm.fts.append(ftr)
    dm.ext_mrns.add(pd.mrn)
    if kind == "F3":
        amt = sum((l.montant_ht for l in lines), D0)
        dm.add_error("F3", "mrn_refacture_deux_fois", [ftr.doc_id], amount=q2(amt), nature="recouvrable",
                     composante=None, gap=amt, thr=Decimal(1), other_dossiers=[pid],
                     fields=[f"{ftr.doc_id}.refs_mrn"],
                     description=f"Débours du MRN {pd.mrn} (dossier {pid}, facture {pft.numero}) refacturés à nouveau.",
                     key="F3")
    else:
        amt = lines[0].montant_ht
        dm.add_error("F4", "prestation_refacturee", [ftr.doc_id], amount=q2(amt), nature="recouvrable",
                     composante="prestation", eligible=False, other_dossiers=[pid], fields=[f"{ftr.doc_id}.lignes[0]"],
                     description=f"Prestation « {lines[0].libelle} » du MRN {pd.mrn} déjà facturée (dossier {pid}).",
                     key="F4")
    dm.add_error("C7", "mrn_cite_inconnu", [ftr.doc_id], eligible=False, consequence_of=kind,
                 fields=[f"{ftr.doc_id}.refs_mrn"],
                 description=f"Conséquence : le MRN {pd.mrn} cité n'appartient pas à ce dossier.", key="C7F")


# ======================================================================
# Avoirs (E)
# ======================================================================

GAP_COMPOSANTE = {"C1": "droit", "C2": "autre_taxe", "C3": "tva", "C4": "tva", "C5": "combine", "G4": "forfait_petits_envois",
                  "G5": "forfait_petits_envois", "D2": "prestation", "D3": "prestation", "D4": "prestation",
                  "D5": "prestation", "D6": "prestation", "D7": "prestation", "D9": "prestation", "C6": "prestation"}


def build_avoirs(dm):
    p = dm.plan
    r = dm.r
    ectl = [e["control"] for e in p["errors"] if e["control"].startswith("E")]
    if not ectl:
        return
    origin = _pre_ft(dm) if p["template"] == "T5" else dm.fts[0]
    d = _d0(dm)
    lang = dm.fw.lang
    tpl = p["template"]
    gaps = {GAP_COMPOSANTE[e["control"]] for e in p["errors"] if e["control"] in GAP_COMPOSANTE}
    if any(e["control"] in ("C1", "C2", "C4", "C5", "G4", "G5", "C3") for e in p["errors"]) and \
            any(l.code == "AVANCE_FONDS" for l in origin.lines):
        gaps.add("prestation")  # FAF potentiellement en excédent (C6)
    lines = []
    refs_origin = [origin.numero]
    refs_mrn = [d.mrn]
    motif = "Geste commercial"
    if "E6" in ectl:
        l = dm.d3_line
        delta = next(e["amount"] for e in dm.errors if e["control"] == "D3")
        credit = q2(delta * D(r.uniform(0.3, 0.65)))
        lines.append(_presta(dm, l.code, lang, tpl, 1, credit, mrn=d.mrn, libelle=l.libelle))
        motif = "Régularisation partielle frais de dédouanement"
    elif "E2" in ectl:
        if "prestation" not in gaps:
            src = next(l for l in origin.lines if l.code == "DEDOUANEMENT")
            credit = q2(src.montant_ht * D(r.uniform(1.3, 1.9)))
            lines.append(_presta(dm, src.code, lang, tpl, 1, credit, mrn=d.mrn, libelle=src.libelle))
        else:
            src = next((l for l in dm.fts[0].lines if l.code in ("DROITS", "COMBINES") and l.montant_ht > 0), None)
            if src is None or "droit" in gaps or "combine" in gaps:
                src = next(l for l in origin.lines if l.code == "DEDOUANEMENT")
                credit = q2(src.montant_ht * D(r.uniform(1.3, 1.9)))
                lines.append(_presta(dm, src.code, lang, tpl, 1, credit, mrn=d.mrn, libelle=src.libelle))
            else:
                credit = q2(src.montant_ht * D(r.uniform(1.3, 1.9)))
                lines.append(FTLine(src.nature, src.code, src.libelle, Decimal(1), credit, credit, D0, D0, src.marker,
                                    mrn=d.mrn))
        motif = "Régularisation"
    else:
        # E1, E5 ou E3/E4 seuls : avoir commercial sans écart correspondant
        if "prestation" not in gaps:
            credit = q2(D(r.choice(["15.00", "20.00", "25.00", "30.00", "40.00"])))
            src = next(l for l in origin.lines if l.code == "DEDOUANEMENT")
            lines.append(_presta(dm, src.code, lang, tpl, 1, credit, mrn=d.mrn, libelle=src.libelle))
        else:
            src = next((l for l in dm.fts[0].lines if l.is_debours and l.montant_ht > 20
                        and composante_of(l.nature) not in gaps), None)
            if src is not None:
                credit = q2(src.montant_ht * D(r.uniform(0.2, 0.4)))
                lines.append(FTLine(src.nature, src.code, src.libelle, Decimal(1), credit, credit, D0, D0, src.marker,
                                    mrn=d.mrn))
            else:
                credit = q2(D("15.00"))
                src = next(l for l in origin.lines if l.code == "DEDOUANEMENT")
                lines.append(_presta(dm, src.code, lang, tpl, 1, credit, mrn=d.mrn, libelle=src.libelle))
    if "E1" in ectl:
        refs_origin = []
        if r.random() < 0.4:
            refs_mrn = []
    av = CreditNote("av1", f"AV-26{10000 + p['idx'] * 7:05d}", origin.date + dt.timedelta(days=r.randint(12, 60)),
                    dm.fw_party(), origin.client, refs_origin, refs_mrn,
                    list(origin.refs_transport[:1]) if refs_mrn else [], lines, motif, tpl, lang)
    av.recompute()
    dm.avoirs.append(av)
    for c in ectl:
        if c == "E1":
            dm.add_error("E1", "avoir_sans_reference", [av.doc_id], eligible=False,
                         fields=[f"{av.doc_id}.refs_facture_origine"],
                         description="Avoir sans référence de facture d'origine.", key="E1")
        elif c == "E2":
            dm.add_error("E2", "avoir_excessif", [av.doc_id, origin.doc_id], eligible=False,
                         fields=[f"{av.doc_id}.lignes[0].montant_ht"],
                         description="Avoir supérieur au montant facturé pour cette nature.", key="E2")
        elif c == "E4":
            delta = q2(D(r.uniform(3.5, 40)))
            av.printed_override["total_ttc"] = av.total_ttc + delta
            dm.add_error("E4", "avoir_total_faux", [av.doc_id], eligible=False,
                         fields=[f"{av.doc_id}.total_credite_ttc"],
                         description=f"Total de l'avoir imprimé supérieur de {delta} à la somme des lignes.",
                         key="E4")
        elif c == "E3":
            dm.duplicates.append((av.doc_id, "av1b"))
            dm.add_error("E3", "avoir_double", [av.doc_id, "av1b"], eligible=False, fields=[],
                         description="Le même avoir est présent deux fois (pièce jointe de courriel et dépôt).",
                         key="E3")


# ======================================================================
# P et F1
# ======================================================================

NX_KINDS = [("pre_alerte", "PRE-ALERT / INVOICE"), ("liste_expedition", "INVOICE - PACKING DETAILS"),
            ("devis", "INVOICE QUOTATION"), ("bon_commande", "PURCHASE ORDER / FACTURE"),
            ("bon_livraison_sans_valeur", "FACTURE - BON DE LIVRAISON (sans valeur)")]


def inject_p_and_f1(dm):
    p = dm.plan
    r = dm.r
    pe = p["p_error"]
    if pe == "facture_manquante":
        for ci in dm.cis:
            dm.absent.add(ci.doc_id)
        dm.add_error("P1", "facture_manquante", [dm.final_decls[0].doc_id], eligible=False,
                     description="Aucune facture commerciale dans le dossier.", key="P1")
    elif pe == "declaration_manquante":
        for d in dm.decls:
            dm.absent.add(d.doc_id)
        dm.add_error("P1", "declaration_manquante", [dm.cis[0].doc_id], eligible=False,
                     description="Aucune déclaration dans le dossier.", key="P1")
    elif pe == "faux_document_facture":
        kind, title = r.choice(NX_KINDS)
        ci = dm.cis[0]
        nx = SupportDoc("nx1", kind, "en" if "INVOICE" in title.split()[0] else "fr",
                        {"title": title, "ci": ci, "date": ci.date - dt.timedelta(days=r.randint(1, 6))},
                        doc_type="document_non_exploitable")
        dm.nx.append(nx)
        dm.add_error("P2", "faux_document_facture", [nx.doc_id], eligible=False,
                     description=f"Document intitulé facture mais de type {kind}.", key="P2")
        if r.random() < 0.5:
            for c in dm.cis:
                dm.absent.add(c.doc_id)
            dm.add_error("P1", "facture_manquante", [nx.doc_id, dm.final_decls[0].doc_id], eligible=False,
                         description="Seul un document non exploitable intitulé facture est présent.", key="P1")
    if dm.has("F1"):
        dm.f1_requested = True
