"""Rendu des factures de transitaire (gabarits T1–T8, SPEC §19.6) et des avoirs."""

from __future__ import annotations

from decimal import Decimal

from .common import d_en, d_fr, fmt_num, fmt_qty, pct_str
from .pdfkit import BLUE, DARK, GREY, LIGHT, LIGHT2, Color, Pen

NS = {"T1": "fr", "T2": "en", "T3": "frs", "T4": "fr", "T5": "de", "T6": "fr", "T7": "fr", "T8": "frn"}
GREEN = Color(0.1, 0.4, 0.3)
RED = Color(0.55, 0.1, 0.1)
IBAN = "IBAN FR00 0000 0000 0000 0000 0000 000 (FICTIF)"


def _m(v, tpl, neg=False):
    return fmt_num(-v if neg else v, NS[tpl], 2, neg="paren" if tpl == "T8" else "minus")


def tref_print(ref, tpl):
    if tpl != "T8":
        return ref
    if ref.startswith("999-"):
        s = ref[4:]
        return f"999 / {s[:4]} {s[4:]}"
    return f"{ref[:4]} {ref[4:8]} / {ref[8:]}"


def _date(d, tpl):
    return d_en(d) if tpl == "T2" else d_fr(d)


def _fw_header(pen, ft, tpl, title, color=BLUE, lang="fr"):
    e = ft.emetteur
    pen.logo(12, 10, e.name.split(" (")[0].replace("Transitaire Démo ", "").upper(), w=44, h=13, color=color)
    pen.lines(60, 13, [e.name, ", ".join(e.addr), f"{'VAT' if lang == 'en' else 'TVA'} {e.vat}"], size=7.6,
              bold_first=True, maxw=80)
    pen.text(198, 15, title, size=13, bold=True, align="right", maxw=60)
    pen.text(198, 21, ft.numero, size=10, bold=True, align="right")


def _client_block(pen, ft, x, y, lang="fr"):
    c = ft.client
    pen.text(x, y, "Bill to" if lang == "en" else "Client facturé", size=7.2, color=GREY)
    pen.lines(x, y + 4.2, [c.name] + list(c.addr) + [f"{'VAT No.' if lang == 'en' else 'N° TVA'} {c.vat}"], size=8,
              bold_first=True, maxw=85)


def _refs_block(pen, ft, x, y, tpl, lang="fr", extra=()):
    lab = {"fr": ("Date", "Échéance", "LTA / BL", "MRN", "Fact. fournisseur", "Dossier"),
           "en": ("Date", "Due date", "AWB / BL", "MRN", "Supplier inv.", "File"),
           "fr_en": ("Date", "Échéance / Due", "LTA / AWB", "MRN", "Fact. / Inv.", "Dossier / File")}[lang]
    rows = [(lab[0], _date(ft.date, tpl))]
    if ft.due_date:
        rows.append((lab[1], _date(ft.due_date, tpl)))
    if ft.refs_transport:
        rows.append((lab[2], " ; ".join(tref_print(t, tpl) for t in ft.refs_transport)))
    for i, m in enumerate(ft.refs_mrn):
        rows.append((lab[3] if i == 0 else "", m))
    if ft.refs_ci:
        rows.append((lab[4], " ; ".join(ft.refs_ci[:3])))
    rows += list(extra)
    for k, (a, b) in enumerate(rows):
        pen.text(x, y + k * 4.1, a, size=7.6, color=DARK)
        pen.text(x + 26, y + k * 4.1, b, size=7.8, maxw=70)
    return y + len(rows) * 4.1


def _legal(pen, ft, tpl, y=280):
    pen.text(105, y, f"{ft.emetteur.name} - SAS au capital fictif - RCS Démo {ft.emetteur.siren} - {IBAN}", size=6,
             align="center", color=GREY, maxw=190)


def _totals(pen, rows, x, y, tpl, w=70, size=8.2):
    for k, (lab, v, bold) in enumerate(rows):
        yy = y + k * 4.8
        if bold:
            pen.rect(x - 2, yy - 3.7, w + 4, 5.6, fill=LIGHT, stroke=False)
        pen.text(x, yy, lab, size=size, bold=bold)
        pen.text(x + w, yy, v if isinstance(v, str) else _m(v, tpl), size=size, bold=bold, align="right")
    return y + len(rows) * 4.8


def _rd(l, ft, sep=" "):
    """Détail d'une ligne de prestation ; MRN ajouté quand la facture couvre plusieurs déclarations."""
    if l.mrn and len(set(ft.refs_mrn)) > 1:
        return f"{l.mrn}{sep}{l.detail}".strip()
    return l.detail


def render_ft(pen: Pen, ft, dm, variant: int):
    {"T1": _t1, "T2": _t2, "T3": _t3, "T4": _t4, "T5": _t5, "T6": _t6, "T7": _t7, "T8": _t8}[ft.template](
        pen, ft, dm, variant)


def _due(ft):
    import datetime as dt
    ft.due_date = ft.due_date or ft.date + dt.timedelta(days=30)


# ------------------------------------------------------------------ T1
def _t1(pen, ft, dm, variant, title="FACTURE"):
    tpl = "T1"
    _due(ft)
    pen.set_theme("sans")
    _fw_header(pen, ft, tpl, title)
    _client_block(pen, ft, 115, 32)
    y = _refs_block(pen, ft, 12, 32, tpl) + 6
    deb = [l for l in ft.lines if l.is_debours]
    pre = [l for l in ft.lines if not l.is_debours]
    if deb:
        pen.text(12, y, "DÉBOURS (sommes payées pour votre compte, refacturées à l'identique)", size=8.5, bold=True,
                 color=BLUE)
        y = pen.table(12, y + 2, [("Désignation", 62, "left"), ("MRN", 44, "left"), ("Détail", 20, "left"),
                                  ("TVA", 14, "center"), ("Mt TVA", 20, "right"), ("Montant", 26, "right")],
                      [[l.libelle, l.mrn or "", l.detail, l.marker + (f" {pct_str(l.taux_tva)} %" if l.taux_tva else ""),
                        _m(l.montant_tva, tpl) if l.montant_tva else "", _m(l.montant_ht, tpl)] for l in deb],
                      size=7.6, row_h=5)
        if ft.total_debours_printed:
            pen.text(150, y + 4, "Total débours", size=8.2, bold=True, align="right")
            pen.text(196, y + 4, _m(ft.total_debours, tpl), size=8.2, bold=True, align="right")
        y += 9
    if pre:
        pen.text(12, y, "PRESTATIONS", size=8.5, bold=True, color=BLUE)
        y = pen.table(12, y + 2, [("Désignation", 58, "left"), ("Détail", 40, "left"), ("Qté", 12, "right"),
                                  ("PU HT", 22, "right"), ("Montant HT", 26, "right"), ("TVA", 14, "center"),
                                  ("", 14, "center")],
                      [[l.libelle, _rd(l, ft), fmt_qty(l.qty, "fr"), _m(l.unit_price, tpl), _m(l.montant_ht, tpl),
                        f"{pct_str(l.taux_tva)} %", l.marker] for l in pre], size=7.4, row_h=5) + 4
    rows = []
    if deb and pre:
        rows.append(("Total prestations HT", sum((l.montant_ht for l in pre), Decimal(0)), False))
    rows += [("Total HT", ft.printed("total_ht"), False), ("TVA 20 %", ft.printed("total_tva"), False),
             ("Total TTC", ft.printed("total_ttc"), True)]
    if ft.acompte:
        rows += [("Acompte reçu", -ft.acompte, False), ("Net à payer", ft.printed("net_a_payer"), True)]
    else:
        rows += [("Net à payer", ft.printed("net_a_payer"), True)]
    y = _totals(pen, rows, 126, y + 2, tpl)
    pen.text(12, y + 6, "Codes TVA : E = exonéré / hors champ (débours) ; N = normal 20 %.", size=6.8, color=GREY)
    _legal(pen, ft, tpl)


# ------------------------------------------------------------------ T2
def _t2(pen, ft, dm, variant):
    tpl = "T2"
    _due(ft)
    pen.set_theme("dejavu")
    _fw_header(pen, ft, tpl, "INVOICE", color=GREEN, lang="en")
    _client_block(pen, ft, 115, 32, lang="en")
    y = _refs_block(pen, ft, 12, 32, tpl, lang="en") + 6
    deb = [l for l in ft.lines if l.is_debours]
    pre = [l for l in ft.lines if not l.is_debours]
    if deb:
        pen.text(12, y, "CUSTOMS DISBURSEMENTS", size=8.5, bold=True, color=GREEN)
        rows = []
        by_art = {}
        order = []
        for l in deb:
            key = (l.mrn, l.hs or l.code, l.article)
            if key not in by_art:
                by_art[key] = {"hs": l.hs or "", "base": "", "duty": "", "vat": "", "other": [], "mrn": l.mrn}
                order.append(key)
            b = by_art[key]
            st = f" {l.marker}" + (" S" if l.taux_tva else "")
            if l.code == "DROITS":
                b["base"] = _m(l.base_droit, tpl) if l.base_droit is not None else ""
                b["duty"] = _m(l.montant_ht, tpl) + st
            elif l.code == "TVA":
                b["vat"] = _m(l.montant_ht, tpl) + st
            else:
                b["other"].append((l.libelle, _m(l.montant_ht, tpl) + st, l.detail))
        for key in order:
            b = by_art[key]
            if b["duty"] or b["vat"] or b["base"]:
                rows.append([b["hs"], b["mrn"] or "", b["base"], b["duty"], b["vat"]])
            for lib, v, det in b["other"]:
                rows.append([lib if not det else f"{lib} ({det})", b["mrn"] or "", "", v, ""])
        y = pen.table(12, y + 2, [("HS code / item", 44, "left"), ("MRN", 44, "left"), ("Duty base", 30, "right"),
                                  ("Duty", 34, "right"), ("Import VAT", 34, "right")], rows, size=7.4, row_h=5)
        pen.text(150, y + 4, "Total disbursements", size=8.2, bold=True, align="right")
        pen.text(196, y + 4, _m(ft.total_debours, tpl) + " Z", size=8.2, bold=True, align="right")
        y += 10
    if pre:
        pen.text(12, y, "SERVICES", size=8.5, bold=True, color=GREEN)
        y = pen.table(12, y + 2, [("Description", 56, "left"), ("Details", 48, "left"), ("Qty", 12, "right"),
                                  ("Unit price", 24, "right"), ("Amount", 28, "right"), ("VAT", 18, "center")],
                      [[l.libelle, _rd(l, ft), fmt_qty(l.qty, "en"), _m(l.unit_price, tpl), _m(l.montant_ht, tpl),
                        f"{l.marker} {pct_str(l.taux_tva, 'en')}%"] for l in pre], size=7.4, row_h=5) + 4
    rows = [("Total excl. VAT", _m(ft.printed("total_ht"), tpl), False),
            ("VAT 20%", _m(ft.printed("total_tva"), tpl) + " S", False),
            ("Total incl. VAT", _m(ft.printed("total_ttc"), tpl), True),
            ("Amount due", _m(ft.printed("net_a_payer"), tpl), True)]
    y = _totals(pen, rows, 126, y + 2, tpl)
    pen.text(12, y + 6, "VAT status: Z = disbursement outside VAT scope ; S = standard rate 20%.", size=6.8,
             color=GREY)
    _legal(pen, ft, tpl)


# ------------------------------------------------------------------ T3
def _t3(pen, ft, dm, variant):
    tpl = "T3"
    _due(ft)
    pen.set_theme("serif")
    pen.text(12, 16, ft.emetteur.name, size=13, bold=True)
    pen.lines(12, 21, [", ".join(ft.emetteur.addr), f"TVA intracommunautaire {ft.emetteur.vat}"], size=8)
    pen.rect(130, 10, 68, 14, lw=1)
    pen.text(164, 16, "FACTURE", size=12, bold=True, align="center")
    pen.text(164, 21, f"N° {ft.numero}", size=9, align="center")
    _client_block(pen, ft, 115, 34)
    y = _refs_block(pen, ft, 12, 34, tpl) + 8
    y = pen.table(12, y, [("Désignation", 80, "left"), ("Référence", 46, "left"), ("Qté", 12, "right"),
                          ("Montant HT", 28, "right"), ("TVA", 20, "center")],
                  [[l.libelle + (" (débours)" if l.is_debours else ""), l.mrn or l.detail, fmt_qty(l.qty, "frs"),
                    _m(l.montant_ht, tpl), f"{l.marker} - {pct_str(l.taux_tva)} %"] for l in ft.lines],
                  size=7.8, row_h=5.4, grid="h") + 6
    rows = [("Total HT", ft.printed("total_ht"), False), ("Total TVA", ft.printed("total_tva"), False),
            ("Total TTC", ft.printed("total_ttc"), True), ("Net à payer", ft.printed("net_a_payer"), True)]
    y = _totals(pen, rows, 126, y, tpl)
    pen.text(12, y + 6, "TVA : 0 = débours non soumis ; 1 = taux normal 20 %.", size=6.8, color=GREY)
    _legal(pen, ft, tpl)


# ------------------------------------------------------------------ T4
def _t4(pen, ft, dm, variant):
    tpl = "T4"
    _due(ft)
    pen.set_theme("sans")
    e = ft.emetteur
    pen.logo(12, 8, "DELTA FRET", w=40, h=12, color=Color(0.35, 0.15, 0.45))
    pen.lines(56, 11, [e.name, ", ".join(e.addr), f"TVA {e.vat}"], size=7.4, bold_first=True)
    pen.text(198, 12, "RELEVÉ MENSUEL DE FACTURATION", size=11.5, bold=True, align="right")
    pen.text(198, 18, f"N° {ft.numero}", size=9.5, bold=True, align="right")
    if ft.period:
        pen.text(198, 23, f"Période du {d_fr(ft.period[0])} au {d_fr(ft.period[1])}", size=8, align="right")
    _client_block(pen, ft, 12, 30)
    pen.text(115, 30, f"Date du relevé : {d_fr(ft.date)}", size=8)
    pen.text(115, 34.5, f"Échéance : {d_fr(ft.due_date)}", size=8)
    pen.text(115, 39, f"Nombre d'envois : {len(ft.refs_mrn)}", size=8)
    y = 54
    mrns = []
    for l in ft.lines:
        if l.mrn not in mrns:
            mrns.append(l.mrn)
    rows = []
    matrix_codes = ("DROITS", "AUTRES", "TVA", "DEDOUANEMENT", "LIGNE_SUP", "AVANCE_FONDS")
    extra_lines = []
    for m in mrns:
        ls_all = [l for l in ft.lines if l.mrn == m]
        ls = []
        seen_codes = set()
        for l in ls_all:
            if l.code in matrix_codes and l.code in seen_codes:
                extra_lines.append(l)  # ligne répétée : détaillée à part, jamais additionnée dans la cellule
                continue
            seen_codes.add(l.code)
            ls.append(l)

        def s(code, ls=ls):
            v = sum((l.montant_ht for l in ls if l.code == code), Decimal(0))
            if code == "LIGNE_SUP" and v:
                q = sum((l.qty for l in ls if l.code == code), Decimal(0))
                return f"{_m(v, tpl)} ({fmt_qty(q, 'fr')})"
            return _m(v, tpl) if v else "-"
        tref = next((l.ref_transport for l in ls if l.ref_transport), "")
        ddate = ""
        for d in dm.final_decls:
            if d.mrn == m:
                ddate = d_fr(d.date)
        rows.append([tref, m, ddate, s("DROITS"), s("AUTRES"), s("TVA"), s("DEDOUANEMENT"), s("LIGNE_SUP"),
                     s("AVANCE_FONDS")])
    y = pen.table(8, y, [("Transport", 26, "left"), ("MRN", 36, "left"), ("Date", 17, "center"),
                         ("Droits", 18, "right"), ("Autres tx", 16, "right"), ("TVA import", 19, "right"),
                         ("Dédouan.", 17, "right"), ("Lignes sup. (qté)", 20, "right"), ("Av. fonds", 15, "right")],
                  rows, size=6.9, row_h=5, header_size=6.6) + 5
    other = [l for l in ft.lines if l.code not in matrix_codes or l in extra_lines]
    if other:
        pen.text(8, y, "Détail des autres lignes", size=8, bold=True)
        y = pen.table(8, y + 2, [("MRN", 36, "left"), ("Désignation", 50, "left"), ("Détail", 46, "left"),
                                 ("Qté", 12, "right"), ("PU", 18, "right"), ("Montant HT", 22, "right")],
                      [[l.mrn or "", l.libelle, l.detail, fmt_qty(l.qty, "fr"), _m(l.unit_price, tpl),
                        _m(l.montant_ht, tpl)] for l in other], size=7, row_h=4.8) + 4
    pre_ht = sum((l.montant_ht for l in ft.lines if not l.is_debours), Decimal(0))
    rows = [("Total débours (D)", ft.total_debours, False), ("Total prestations HT (T)", pre_ht, False),
            ("Total HT", ft.printed("total_ht"), False), ("TVA 20 % sur prestations", ft.printed("total_tva"), False),
            ("TOTAL TTC DU RELEVÉ", ft.printed("total_ttc"), True), ("Net à payer", ft.printed("net_a_payer"), True)]
    _totals(pen, rows, 120, y + 2, tpl, w=76)
    _legal(pen, ft, tpl)


# ------------------------------------------------------------------ T5
def _t5(pen, ft, dm, variant):
    tpl = "T5"
    _due(ft)
    pen.set_theme("dejavu")
    title = "FACTURE DE DÉBOURS" if ft.kind == "debours" else ("FACTURE DE PRESTATIONS" if ft.kind == "prestations"
                                                               else "FACTURE")
    _fw_header(pen, ft, tpl, title, color=Color(0.6, 0.3, 0.05))
    _client_block(pen, ft, 115, 32)
    extra = []
    if ft.kind == "prestations":
        other = [f.numero for f in dm.fts if f.kind == "debours"]
        if other:
            extra.append(("Fact. débours", other[0]))
    y = _refs_block(pen, ft, 12, 32, tpl, extra=extra) + 8
    y = pen.table(12, y, [("Désignation", 58, "left"), ("MRN / détail", 48, "left"), ("Qté", 10, "right"),
                          ("PU", 20, "right"), ("Montant", 24, "right"), ("TVA", 18, "right"), ("", 8, "center")],
                  [[l.libelle, l.mrn if l.is_debours else (_rd(l, ft) or l.mrn or ""), fmt_qty(l.qty, "de"),
                    _m(l.unit_price, tpl), _m(l.montant_ht, tpl), _m(l.montant_tva, tpl), l.marker]
                   for l in ft.lines], size=7.4, row_h=5.2) + 5
    if ft.kind == "debours":
        rows = [("Total débours", ft.total_debours, True), ("TVA", ft.printed("total_tva"), False),
                ("Net à payer", ft.printed("net_a_payer"), True)]
    else:
        rows = [("Total HT", ft.printed("total_ht"), False), ("TVA 20 %", ft.printed("total_tva"), False),
                ("Total TTC", ft.printed("total_ttc"), True), ("Net à payer", ft.printed("net_a_payer"), True)]
    _totals(pen, rows, 126, y, tpl)
    _legal(pen, ft, tpl)


# ------------------------------------------------------------------ T6
def _t6(pen, ft, dm, variant):
    tpl = "T6"
    _due(ft)
    pen.set_theme("sans")
    e = ft.emetteur
    pen.rect(0, 0, pen.W, 8, fill=Color(0.75, 0.2, 0.2), stroke=False)
    pen.text(12, 18, e.name, size=12, bold=True)
    pen.lines(12, 23, [", ".join(e.addr), f"TVA {e.vat}"], size=7.6)
    pen.text(198, 18, f"FACTURE N° {ft.numero}", size=11, bold=True, align="right")
    pen.text(198, 23, f"du {d_fr(ft.date)}", size=8.5, align="right")
    _client_block(pen, ft, 115, 32)
    y = _refs_block(pen, ft, 12, 32, tpl) + 8
    y = pen.table(12, y, [("Nat.", 10, "center"), ("Désignation", 70, "left"), ("Référence / détail", 50, "left"),
                          ("Qté", 12, "right"), ("Montant HT", 26, "right"), ("TVA", 18, "right")],
                  [["D" if l.is_debours else "P", l.libelle, l.mrn if l.is_debours else (_rd(l, ft) or ""),
                    fmt_qty(l.qty, "fr"), _m(l.montant_ht, tpl), _m(l.montant_tva, tpl)] for l in ft.lines],
                  size=7.5, row_h=5.2) + 5
    rows = [("Total débours (D)", ft.total_debours, False), ("Total HT", ft.printed("total_ht"), False),
            ("TVA", ft.printed("total_tva"), False), ("Total TTC", ft.printed("total_ttc"), True),
            ("Net à payer", ft.printed("net_a_payer"), True)]
    y = _totals(pen, rows, 126, y, tpl)
    pen.text(12, y + 5, "D = débours (hors TVA) ; P = prestation. Copie de la déclaration et conditions générales "
                        "jointes.", size=6.8, color=GREY)
    _legal(pen, ft, tpl)


# ------------------------------------------------------------------ T7
def _t7(pen, ft, dm, variant):
    tpl = "T7"
    _due(ft)
    pen.set_theme("dejavu")
    _fw_header(pen, ft, tpl, "FACTURE", color=Color(0.05, 0.45, 0.55))
    pen.text(198, 26, "Facture électronique Factur-X (profil EN 16931)", size=6.8, align="right", color=GREY)
    _client_block(pen, ft, 115, 32)
    y = _refs_block(pen, ft, 12, 32, tpl) + 8
    y = pen.table(12, y, [("Désignation", 64, "left"), ("Référence", 48, "left"), ("Qté", 12, "right"),
                          ("PU HT", 20, "right"), ("Total HT", 22, "right"), ("Cat.", 9, "center"),
                          ("TVA %", 13, "right")],
                  [[l.libelle, l.mrn if l.is_debours else (_rd(l, ft) or ""), fmt_qty(l.qty, "fr"),
                    _m(l.unit_price, tpl), _m(l.montant_ht, tpl), l.marker, pct_str(l.taux_tva)]
                   for l in ft.lines], size=7.4, row_h=5.2) + 5
    rows = [("Total HT", ft.printed("total_ht"), False), ("Total TVA", ft.printed("total_tva"), False),
            ("Total TTC", ft.printed("total_ttc"), True), ("Net à payer", ft.printed("net_a_payer"), True)]
    y = _totals(pen, rows, 126, y, tpl)
    pen.text(12, y + 5, "Catégories TVA : E = exonéré (débours, art. 267 II 2° CGI) ; S = taux normal.", size=6.8,
             color=GREY)
    _legal(pen, ft, tpl)


# ------------------------------------------------------------------ T8
def _t8(pen, ft, dm, variant):
    tpl = "T8"
    _due(ft)
    pen.set_theme("lmono" if variant % 2 else "dejavu")
    e = ft.emetteur
    pen.text(10, 10, e.name, size=10, bold=True)
    pen.text(10, 14, f"{', '.join(e.addr)} - TVA/VAT {e.vat}", size=6.5)
    pen.text(200, 10, "FACTURE / INVOICE", size=10, bold=True, align="right")
    pen.text(200, 14, f"N° / No. {ft.numero} - {d_fr(ft.date)}", size=7.2, align="right")
    pen.hline(10, 200, 16.5, lw=0.6)
    c = ft.client
    pen.lines(10, 20, [f"Client / Bill to: {c.name}", f"{', '.join(c.addr)}", f"TVA / VAT No.: {c.vat}"], size=6.8,
              leading=3.2)
    refs = [f"LTA / AWB : {' ; '.join(tref_print(t, tpl) for t in ft.refs_transport)}",
            f"MRN : {' ; '.join(ft.refs_mrn)}", f"Échéance / Due : {d_fr(ft.due_date)}"]
    pen.lines(110, 20, refs, size=6.8, leading=3.2, maxw=90)
    y = 31
    y = pen.table(10, y, [("Désignation / Description", 62, "left"), ("Réf. / Ref.", 46, "left"),
                          ("Qté/Qty", 12, "right"), ("PU/Unit", 18, "right"), ("HT/Net", 20, "right"),
                          ("TVA/VAT", 18, "right"), ("C", 6, "center")],
                  [[l.libelle, (l.mrn or "") + (f" {l.detail}" if l.detail and not l.is_debours else ""),
                    fmt_qty(l.qty, "frn"), _m(l.unit_price, tpl), _m(l.montant_ht, tpl), _m(l.montant_tva, tpl),
                    l.marker] for l in ft.lines], size=6.5, row_h=3.9, grid="h", header_size=6.2) + 3
    rows = [("Débours / Disbursements", ft.total_debours, False), ("Total HT / Net", ft.printed("total_ht"), False),
            ("TVA / VAT", ft.printed("total_tva"), False), ("TTC / Gross", ft.printed("total_ttc"), True),
            ("Net à payer / Amount due", ft.printed("net_a_payer"), True)]
    y = _totals(pen, rows, 120, y + 2, tpl, w=78, size=7)
    pen.text(10, y + 3, "C : D = débours / disbursement (hors TVA) ; N = normal 20 %. Montants négatifs entre "
                        "parenthèses / negative amounts in brackets.", size=5.8, color=GREY)
    _legal(pen, ft, tpl)


# ------------------------------------------------------------------ Avoirs
def render_avoir(pen: Pen, av, dm, variant):
    tpl = av.template
    lang = "en" if tpl == "T2" else ("fr_en" if tpl == "T8" else "fr")
    pen.set_theme({"T2": "dejavu", "T3": "serif", "T8": "lmono"}.get(tpl, "sans"))
    title = {"en": "CREDIT NOTE", "fr": "AVOIR", "fr_en": "AVOIR / CREDIT NOTE"}[lang]
    e = av.emetteur
    pen.logo(12, 10, e.name.split(" (")[0].replace("Transitaire Démo ", "").upper(), w=44, h=13,
             color=RED if tpl != "T2" else GREEN)
    pen.lines(60, 13, [e.name, ", ".join(e.addr), f"TVA {e.vat}"], size=7.6, bold_first=True, maxw=80)
    pen.text(198, 15, title, size=13, bold=True, align="right")
    pen.text(198, 21, av.numero, size=10, bold=True, align="right")
    c = av.client
    pen.lines(115, 32, [c.name] + list(c.addr) + [f"TVA {c.vat}"], size=8, bold_first=True, maxw=85)
    refs = [("Date", d_en(av.date) if lang == "en" else d_fr(av.date))]
    if av.refs_origin:
        refs.append(("Invoice ref." if lang == "en" else "Facture d'origine", " ; ".join(av.refs_origin)))
    if av.refs_mrn:
        refs.append(("MRN", " ; ".join(av.refs_mrn)))
    if av.refs_transport:
        refs.append(("AWB/BL" if lang == "en" else "LTA / BL", " ; ".join(tref_print(t, tpl) for t in av.refs_transport)))
    refs.append(("Reason" if lang == "en" else "Motif", av.motif))
    for k, (a, b) in enumerate(refs):
        pen.text(12, 32 + k * 4.2, a, size=7.6, color=DARK)
        pen.text(40, 32 + k * 4.2, b, size=7.8, maxw=70)
    y = 32 + len(refs) * 4.2 + 8
    neg = tpl in ("T8", "T2")
    y = pen.table(12, y, [("Description" if lang == "en" else "Désignation", 82, "left"),
                          ("MRN", 44, "left"), ("HT" if lang != "en" else "Net", 26, "right"),
                          ("TVA" if lang != "en" else "VAT", 24, "right")],
                  [[l.libelle, l.mrn or "", _m(l.montant_ht, tpl, neg), _m(l.montant_tva, tpl, neg)]
                   for l in av.lines], size=7.8, row_h=5.4) + 6
    lab = {"en": ("Total credited excl. VAT", "VAT", "Total credited"),
           "fr": ("Total HT crédité", "TVA", "Total TTC crédité"),
           "fr_en": ("Total HT / Net credited", "TVA / VAT", "Total TTC / Gross credited")}[lang]
    rows = [(lab[0], _m(av.total_ht, tpl, neg), False), (lab[1], _m(av.total_tva, tpl, neg), False),
            (lab[2], _m(av.printed("total_ttc"), tpl, neg), True)]
    _totals(pen, rows, 120, y, tpl, w=76)
    _legal(pen, av, tpl)
