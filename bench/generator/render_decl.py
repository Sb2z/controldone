"""Rendu PDF des déclarations : L1 (H1 par articles), L2 (preuve condensée), L3 (cases numérotées),
L4 (H7 petits envois). Mises en page inventées, inspirées seulement de la structure publique
du document administratif unique vierge ; aucune reproduction d'un document réel rempli."""

from __future__ import annotations

from decimal import Decimal

from .common import cur_decimals, d_fr, fmt_kg, fmt_num, fmt_qty, pct_str
from .pdfkit import BLUE, DARK, GREY, LIGHT, LIGHT2, Pen

MP_LEGEND = "Modes de paiement : A = comptant ; E = paiement différé (crédit d'enlèvement) ; G = TVA autoliquidée (ATVAI)"
L2_STATUS = {"A": "0", "E": "1", "G": "7"}
DOC_LABELS = {"N380": "Facture commerciale", "N325": "Facture pro forma", "N740": "Lettre de transport aérien",
              "N705": "Connaissement", "1008": "Autoliquidation TVA - n° TVA importateur",
              "FR7": "Référence fiscale complémentaire (TVA importateur)"}


def _rate_text(d, ns):
    if d.rate_printed is None:
        return None
    v = fmt_num(d.rate_printed, ns, 5)
    cur = d.currency if d.currency != "EUR" else None
    fc = d._inv_cur if hasattr(d, "_inv_cur") else cur
    fc = fc or "DEV"
    if d.rate_sens == "devise_par_eur":
        return f"1 EUR = {v} {fc}"
    return f"1 {fc} = {v} EUR"


def _amt(v, ns="fr", dec=2):
    return fmt_num(v, ns, dec)


def _taux(t, ns="fr"):
    if t.categorie == "forfait_petits_envois":
        return f"{fmt_num(t.taux, ns, 2)} EUR/art."
    if t.taux_nature == "specifique":
        return f"{fmt_num(t.taux, ns, 2)} EUR/{t.base_unite}"
    return f"{pct_str(t.taux, ns)} %"


def _base(t, ns="fr"):
    if t.base_montant is not None:
        return _amt(t.base_montant, ns)
    return f"{fmt_qty(t.base_quantite, ns)} {t.base_unite}"


def _printed_cat(d, code):
    return d.printed_totals_override.get(f"cat:{code}", d.cat_totals.get(code, Decimal(0)))


def _printed(d, key):
    return d.printed_totals_override.get(key, getattr(d, key))


def render_declaration(pen: Pen, d, dm, variant: int):
    {"L1": _l1, "L2": _l2, "L3": _l3, "L4": _l4}[d.layout](pen, d, dm, variant)


# ----------------------------------------------------------------------------- L1
def _l1(pen, d, dm, variant):
    pen.set_theme("sans" if variant % 2 else "dejavu")
    ns = "fr"
    dec = cur_decimals(d.currency)

    def head(cont=False):
        pen.rect(10, 8, 190, 14, fill=LIGHT, lw=0.8)
        pen.text(14, 14, "DÉCLARATION EN DOUANE - IMPORTATION (jeu de données H1)", size=11, bold=True)
        pen.text(14, 19, "Mise en libre pratique - copie déclarant - Bureau de douane fictif FR000999", size=7.5,
                 color=DARK)
        pen.text(196, 14, f"MRN {d.mrn}", size=9.5, bold=True, align="right")
        pen.text(196, 19, "suite" if cont else f"Version {d.version}", size=7.5, align="right")
        return 27

    y = head()
    rows = [("MRN", d.mrn), ("LRN (référence déclarant)", d.lrn), ("Date d'acceptation", d_fr(d.date)),
            ("Type de déclaration", "IM A"), ("Version", str(d.version))]
    for k, (a, b) in enumerate(rows):
        pen.text(12, y + k * 4.3, a, size=7.8, color=DARK)
        pen.text(58, y + k * 4.3, b, size=8.3, bold=k == 0)
    imp = d.importer
    pen.text(110, y, "Importateur", size=7.5, color=GREY)
    pen.lines(110, y + 4.2, [imp.name, f"N° TVA : {imp.vat}", f"EORI : {imp.eori}"], size=8, bold_first=True, maxw=88)
    pen.text(110, y + 17, "Déclarant / représentant (indirect)", size=7.5, color=GREY)
    pen.lines(110, y + 21.2, [d.declarant.name, f"N° TVA : {d.declarant.vat}"], size=8, maxw=88)
    y += 31
    pen.hline(10, 200, y - 3, lw=0.3)
    env = [("Pays d'expédition", d.pays_exp), ("Conditions de livraison", f"{d.incoterm} {d.incoterm_place}"),
           ("Monnaie de facturation", d.currency),
           ("Montant total facturé", f"{_amt(d.total_invoiced, ns, dec)} {d.currency}")]
    rt = _rate_text(d, ns)
    if rt:
        env.append(("Taux de change", rt))
    env += [("Masse brute totale", f"{fmt_kg(d.gross_total, ns)} kg"), ("Nombre total de colis", str(d.packages_total)),
            ("Nombre d'articles", str(d.n_articles_printed))]
    for k, (a, b) in enumerate(env):
        col = k % 2
        row = k // 2
        pen.text(12 + col * 95, y + row * 4.5, f"{a} :", size=7.8, color=DARK)
        pen.text(55 + col * 95, y + row * 4.5, b, size=8.3, bold=a.startswith("Montant"))
    y += ((len(env) + 1) // 2) * 4.5 + 3
    pen.text(12, y, "Documents produits / références (DG 12 03)", size=8, bold=True)
    y = pen.table(12, y + 2, [("Code", 18, "center"), ("Référence", 60, "left"), ("Libellé", 108, "left")],
                  [[c, r, DOC_LABELS.get(c, "")] for c, r in d.doc_refs], size=7.6, row_h=4.8) + 4
    for a in d.articles:
        taxes = [t for t in d.taxes if t.article == a.no]
        need = 28 + len(taxes) * 4.8
        if y + need > 272:
            pen.new_page()
            y = head(cont=True)
        pen.rect(12, y, 186, 5.5, fill=LIGHT2, stroke=False)
        pen.text(14, y + 4, f"Article {a.no}", size=8.5, bold=True)
        pen.text(40, y + 4, f"Code marchandise {a.hs10}", size=8.5, bold=True)
        pen.text(100, y + 4, f"Origine {a.origin}", size=8.2)
        pen.text(130, y + 4, f"Régime {a.regime} 000  Préférence {a.pref_code}", size=7.8)
        y += 9
        pen.text(14, y, f"Désignation : {a.desc}", size=7.8, maxw=180)
        y += 4.3
        info = [f"Montant facturé : {_amt(a.amount, ns, dec)} {d.currency}",
                f"Valeur statistique : {_amt(a.stat_value, ns)} EUR",
                f"Masse nette : {fmt_kg(a.net, ns)} kg", f"Masse brute : {fmt_kg(a.gross, ns)} kg"]
        info2 = [f"Colis : {a.packages}"]
        if a.qty_sup is not None:
            info2.insert(0, f"Unités supplémentaires : {fmt_qty(a.qty_sup, ns)} {a.unit_sup}")
        pen.text(14, y, "   |   ".join(info), size=7.4, maxw=184)
        pen.text(14, y + 3.8, "   |   ".join(info2), size=7.4)
        y += 7
        y = pen.table(20, y, [("Type", 14, "center"), ("Libellé", 52, "left"), ("Base d'imposition", 34, "right"),
                              ("Quotité", 26, "right"), ("Montant", 30, "right"), ("MP", 10, "center")],
                      [[t.code, t.label, _base(t, ns), _taux(t, ns), _amt(t.montant, ns), t.mp] for t in taxes],
                      size=7.5, row_h=4.6, header_fill=LIGHT) + 4
    if y > 230:
        pen.new_page()
        y = head(cont=True)
    pen.text(12, y + 2, "Récapitulatif des droits et taxes", size=8.5, bold=True)
    y += 4
    rows = []
    labels = {"A00": "Droits de douane", "B00": "TVA", "A30": "Droit antidumping", "A35": "Droit antidumping provisoire",
              "X01": "Droit spécifique (fictif)", "FPE": "Droit forfaitaire petits envois"}
    for code in sorted(d.cat_totals):
        rows.append([f"Total {code}", labels.get(code, code), _amt(_printed_cat(d, code), ns)])
    rows.append(["", "Total des droits et taxes (DE 14 16)", _amt(_printed(d, "total_droits_taxes"), ns)])
    rows.append(["", "Total à payer ou à garantir", _amt(_printed(d, "total_a_payer"), ns)])
    y = pen.table(80, y, [("", 22, "left"), ("", 62, "left"), ("EUR", 34, "right")], rows, size=8, row_h=5,
                  header=False, bold_rows={len(rows) - 1}) + 4
    pen.text(12, y + 2, MP_LEGEND, size=6.8, color=GREY)
    pen.text(12, y + 6, "Document généré pour un banc de test - aucune valeur juridique.", size=6.8, color=GREY)


# ----------------------------------------------------------------------------- L2
def _l2(pen, d, dm, variant):
    pen.set_theme("mono" if variant % 2 else "lmono")
    ns = "rawc"
    dec = cur_decimals(d.currency)
    pen.text(10, 10, "PREUVE DE DÉDOUANEMENT IMPORT", size=11, bold=True)
    pen.text(10, 14.5, "Édition logiciel déclarant Démo (FICTIF) - document récapitulatif", size=7, color=GREY)
    pen.text(200, 10, d.declarant.name, size=8, align="right", maxw=90)
    pen.text(200, 14.5, f"TVA {d.declarant.vat}", size=7, align="right")
    pen.hline(10, 200, 17, lw=0.8)
    left = [f"MRN.......: {d.mrn}", f"Réf. int..: {d.lrn}", f"Accepté le: {d_fr(d.date)}",
            f"Importat..: {d.importer.name}", f"TVA imp...: {d.importer.vat}", f"EORI......: {d.importer.eori}"]
    right = [f"Incoterm..: {d.incoterm} {d.incoterm_place}", f"Pays exp..: {d.pays_exp}",
             f"Valeur fac: {_amt(d.total_invoiced, ns, dec)} {d.currency}"]
    rt = _rate_text(d, ns)
    if rt:
        right.append(f"Taux......: {rt}")
    right += [f"Poids brut: {fmt_kg(d.gross_total, ns)} kg", f"Colis.....: {d.packages_total}",
              f"Nb articles: {d.n_articles_printed}"]
    pen.lines(10, 22, left, size=7.6, leading=3.8, maxw=95)
    pen.lines(110, 22, right, size=7.6, leading=3.8, maxw=90)
    y = 22 + max(len(left), len(right)) * 3.8 + 2
    refs = "  ".join(f"{c}:{r}" for c, r in d.doc_refs)
    pen.text(10, y, f"Docs: {refs}", size=7, maxw=190)
    y += 5
    cols = [("N", 6, "center"), ("Code", 20, "left"), ("Désignation", 44, "left"), ("Or", 7, "center"),
            ("Mt facturé", 20, "right"), ("Base droits", 19, "right"), ("Tx", 9, "right"), ("Droits", 15, "right"),
            ("Base TVA", 19, "right"), ("TVA", 16, "right"), ("St", 6, "center")]
    rows = []
    subrows = []
    for a in d.articles:
        a00 = next((t for t in d.taxes if t.article == a.no and t.code == "A00"), None)
        b00 = next((t for t in d.taxes if t.article == a.no and t.code == "B00"), None)
        rows.append([str(a.no), a.hs10, a.desc, a.origin, _amt(a.amount, ns, dec),
                     _amt(a00.base_montant, ns) if a00 else "", pct_str(a00.taux, ns) if a00 else "",
                     _amt(a00.montant, ns) if a00 else "", _amt(b00.base_montant, ns) if b00 else "",
                     _amt(b00.montant, ns) if b00 else "", L2_STATUS.get(b00.mp if b00 else "E", "1")])
        for t in d.taxes:
            if t.article == a.no and t.code not in ("A00", "B00"):
                rows.append(["", t.code, f"  {t.label}", "", "", _base(t, ns), _taux(t, ns).replace(" %", ""),
                             _amt(t.montant, ns), "", "", L2_STATUS.get(t.mp, "1")])
                subrows.append(len(rows) - 1)
    y = pen.table(10, y, cols, rows, size=6.9, row_h=4.6, grid="h", header_fill=LIGHT, fill_rows=set(subrows)) + 4
    tot = [("Total droits (A00)", _printed_cat(d, "A00"))]
    oth = sum((v for k, v in d.cat_totals.items() if k not in ("A00", "B00")), Decimal(0))
    if oth:
        tot.append(("Total autres taxes", oth))
    tot.append(("Total TVA (B00)", _printed_cat(d, "B00")))
    tot.append(("TOTAL DROITS ET TAXES", _printed(d, "total_droits_taxes")))
    tot.append(("TOTAL A PAYER", _printed(d, "total_a_payer")))
    for k, (a, v) in enumerate(tot):
        pen.text(120, y + k * 4.4, a, size=7.8, bold=k >= len(tot) - 1)
        pen.text(200, y + k * 4.4, _amt(v, ns), size=7.8, bold=k >= len(tot) - 1, align="right")
    y += len(tot) * 4.4 + 4
    pen.text(10, y, "St (statut paiement) : 0 = comptant ; 1 = différé ; 7 = TVA autoliquidée", size=6.6, color=GREY)


# ----------------------------------------------------------------------------- L3
def _box(pen, x, y, w, h, num, title, lines, size=7.6, bold=False):
    pen.rect(x, y, w, h, lw=0.5)
    pen.text(x + 1, y + 2.6, f"{num} {title}", size=5.4, color=GREY, maxw=w - 2)
    for i, s in enumerate(lines):
        pen.text(x + 1.5, y + 6.4 + i * 3.6, s, size=size, bold=bold and i == 0, maxw=w - 3)


def _l3(pen, d, dm, variant):
    pen.set_theme("sans")
    ns = "frs"
    dec = cur_decimals(d.currency)
    arts = list(d.articles)
    first = arts[:1]
    rest = arts[1:]
    pages = [first] + [rest[i:i + 3] for i in range(0, len(rest), 3)]
    tot_pages = len(pages)
    for pi, group in enumerate(pages):
        if pi > 0:
            pen.new_page()
        pen.text(10, 9, "DOCUMENT ADMINISTRATIF UNIQUE - IMPORTATION" if pi == 0 else "DAU-BIS (suite)", size=9.5,
                 bold=True)
        pen.text(200, 9, "Exemplaire déclarant - FICTIF", size=7, align="right", color=GREY)
        if pi == 0:
            _box(pen, 10, 12, 95, 20, "2", "Expéditeur / Exportateur", [dm_seller_name(dm, d)] + ["(adresse fictive)"])
            _box(pen, 105, 12, 30, 10, "1", "Déclaration", ["IM A"], bold=True)
            _box(pen, 135, 12, 32, 10, "3", "Formulaires", [f"1/{tot_pages}"])
            _box(pen, 167, 12, 33, 10, "5", "Articles", [str(d.n_articles_printed)])
            _box(pen, 105, 22, 47, 10, "6", "Total des colis", [str(d.packages_total)])
            _box(pen, 152, 22, 48, 10, "7", "Numéro de référence", [d.lrn])
            _box(pen, 10, 32, 95, 22, "8", "Destinataire / Importateur",
                 [d.importer.name, f"TVA {d.importer.vat}", f"EORI {d.importer.eori}"])
            _box(pen, 105, 32, 95, 22, "A", "Bureau de destination / MRN",
                 ["FR000999 - bureau fictif", f"MRN {d.mrn}", f"Acceptation : {d_fr(d.date)}"], bold=False)
            _box(pen, 10, 54, 95, 16, "14", "Déclarant / Représentant",
                 [d.declarant.name, f"TVA {d.declarant.vat}"])
            _box(pen, 105, 54, 32, 16, "15", "Pays d'expédition", [d.pays_exp])
            _box(pen, 137, 54, 63, 16, "20", "Conditions de livraison", [f"{d.incoterm} {d.incoterm_place}"])
            _box(pen, 10, 70, 63, 12, "22", "Monnaie et montant total facturé",
                 [f"{d.currency} {_amt(d.total_invoiced, ns, dec)}"], bold=True)
            rt = _rate_text(d, ns)
            _box(pen, 73, 70, 64, 12, "23", "Taux de change", [rt or ""])
            _box(pen, 137, 70, 63, 12, "35t", "Masse brute totale (kg)", [fmt_kg(d.gross_total, ns)])
            y = 84
        else:
            y = 14
        for a in group:
            y = _l3_article(pen, d, a, y, ns, dec)
        if pi == 0:
            refs = [f"{c} {r}" for c, r in d.doc_refs]
            _box(pen, 10, y, 120, 6 + 3.6 * len(refs) + 2, "44", "Mentions spéciales / Documents produits", refs)
            bl = []
            for code in sorted(d.cat_totals):
                bl.append(f"{code} : {_amt(_printed_cat(d, code), ns)}")
            bl.append(f"Total droits et taxes : {_amt(_printed(d, 'total_droits_taxes'), ns)}")
            bl.append(f"Total à payer : {_amt(_printed(d, 'total_a_payer'), ns)}")
            _box(pen, 130, y, 70, 6 + 3.6 * len(bl) + 2, "B", "Données comptables (EUR)", bl)
            y += max(6 + 3.6 * len(refs) + 2, 6 + 3.6 * len(bl) + 2)
            _box(pen, 10, y, 190, 14, "54", "Lieu et date - signature du déclarant",
                 [f"{d.declarant.name} - {d_fr(d.date)}", "MP : A comptant / E différé / G autoliquidation TVA"],
                 size=7)


def dm_seller_name(dm, d):
    cid = d.ci_ids[0] if d.ci_ids else None
    ci = dm.ci_by_id.get(cid) if cid else None
    return ci.seller.name if ci else ""


def _l3_article(pen, d, a, y, ns, dec):
    taxes = [t for t in d.taxes if t.article == a.no]
    h47 = 6 + 3.9 * (len(taxes) + 1) + 2
    _box(pen, 10, y, 120, 18, "31", f"Colis et désignation - article {a.no}",
         [a.desc, f"{a.packages} colis"], size=7.2)
    _box(pen, 130, y, 22, 9, "32", "Article n°", [str(a.no)], bold=True)
    _box(pen, 152, y, 48, 9, "33", "Code des marchandises", [a.hs10], bold=True)
    _box(pen, 130, y + 9, 22, 9, "34", "Pays origine", [a.origin])
    _box(pen, 152, y + 9, 24, 9, "35", "Masse brute (kg)", [fmt_kg(a.gross, ns)])
    _box(pen, 176, y + 9, 24, 9, "38", "Masse nette (kg)", [fmt_kg(a.net, ns)])
    y += 18
    _box(pen, 10, y, 30, 9, "36", "Préférence", [a.pref_code])
    _box(pen, 40, y, 30, 9, "37", "Régime", [f"{a.regime} 000"])
    _box(pen, 70, y, 40, 9, "41", "Unités supplémentaires",
         [f"{fmt_qty(a.qty_sup, ns)} {a.unit_sup}" if a.qty_sup is not None else "-"])
    _box(pen, 110, y, 45, 9, "42", "Prix de l'article", [f"{_amt(a.amount, ns, dec)}"])
    _box(pen, 155, y, 45, 9, "46", "Valeur statistique", [_amt(a.stat_value, ns)])
    y += 9
    pen.rect(10, y, 190, h47, lw=0.5)
    pen.text(11, y + 2.6, "47 Calcul des impositions", size=5.4, color=GREY)
    yy = pen.table(14, y + 4, [("Type", 14, "center"), ("Base d'imposition", 40, "right"), ("Quotité", 28, "right"),
                               ("Montant", 32, "right"), ("MP", 10, "center")],
                   [[t.code, _base(t, ns), _taux(t, ns), _amt(t.montant, ns), t.mp] for t in taxes],
                   size=7.2, row_h=3.9, header_fill=LIGHT2, grid="h")
    return y + h47 + 2


# ----------------------------------------------------------------------------- L4
def _l4(pen, d, dm, variant):
    pen.set_theme("dejavu" if variant % 2 else "sans")
    ns = "fr"
    dec = cur_decimals(d.currency)
    pen.rect(10, 8, 190, 16, fill=LIGHT, lw=0.8)
    pen.text(14, 14.5, "DÉCLARATION EN DOUANE - ENVOI DE FAIBLE VALEUR (H7)", size=11, bold=True)
    pen.text(14, 20, "Mise en libre pratique - édition intégrateur / déclarant (FICTIF)", size=7.5)
    pen.text(196, 14.5, f"MRN {d.mrn}", size=9.5, bold=True, align="right")
    y = 30
    rows = [("MRN", d.mrn), ("Référence locale", d.lrn), ("Date d'acceptation", d_fr(d.date)),
            ("Destinataire / importateur", d.importer.name), ("N° TVA", d.importer.vat),
            ("Déclarant", d.declarant.name), ("Pays d'expédition", d.pays_exp),
            ("Conditions de livraison", f"{d.incoterm} {d.incoterm_place}")]
    fr7 = [r for c, r in d.doc_refs if c == "FR7"]
    if fr7:
        rows.append(("Référence fiscale complémentaire (DE 13 16)", f"FR7 {fr7[0]}"))
    for k, (a, b) in enumerate(rows):
        pen.text(12, y + k * 4.5, f"{a} :", size=7.8, color=DARK)
        pen.text(80, y + k * 4.5, b, size=8.3, bold=(k == 0), maxw=118)
    y += len(rows) * 4.5 + 3
    other_refs = [f"{c} {r}" for c, r in d.doc_refs if c != "FR7"]
    pen.text(12, y, "Documents : " + " ; ".join(other_refs), size=7.6, maxw=186)
    y += 6
    cols = [("Pos.", 10, "center"), ("Code marchandise", 28, "center"), ("Description", 70, "left"),
            ("Qté", 12, "right"), ("Origine", 14, "center"), (f"Valeur ({d.currency})", 30, "right"),
            ("Masse brute kg", 22, "right")]
    rows = [[str(a.no), a.hs10, a.desc, fmt_qty(a.qty_total, ns), a.origin, _amt(a.amount, ns, dec),
             fmt_kg(a.gross, ns)] for a in d.articles]
    y = pen.table(12, y, cols, rows, size=7.6, row_h=5) + 3
    info = [f"Nombre d'articles (positions) : {d.n_articles_printed}",
            f"Valeur intrinsèque totale : {_amt(d.total_invoiced, ns, dec)} {d.currency}",
            f"Masse brute totale : {fmt_kg(d.gross_total, ns)} kg   Colis : {d.packages_total}"]
    rt = _rate_text(d, ns)
    if rt:
        info.append(f"Taux de change : {rt}")
    pen.lines(12, y + 2, info, size=8, leading=4.4)
    y += len(info) * 4.4 + 6
    pen.text(12, y, "Droits et taxes", size=8.5, bold=True)
    y = pen.table(12, y + 2, [("Type", 14, "center"), ("Libellé", 64, "left"), ("Base", 32, "right"),
                              ("Taux", 30, "right"), ("Montant EUR", 30, "right"), ("MP", 10, "center")],
                  [[t.code, t.label, (f"{fmt_qty(t.base_quantite, ns)} article(s)" if t.base_montant is None
                                      else _amt(t.base_montant, ns)), _taux(t, ns), _amt(t.montant, ns), t.mp]
                   for t in d.taxes], size=7.8, row_h=5.2) + 4
    pen.text(150, y + 2, "Total droits et taxes :", size=8, align="right")
    pen.text(196, y + 2, _amt(_printed(d, "total_droits_taxes"), ns), size=8, align="right")
    pen.text(150, y + 7, "Total à payer :", size=8.5, bold=True, align="right")
    pen.text(196, y + 7, _amt(_printed(d, "total_a_payer"), ns), size=8.5, bold=True, align="right")
    pen.text(12, y + 14, MP_LEGEND, size=6.6, color=GREY)
