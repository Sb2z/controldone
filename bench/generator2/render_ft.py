"""Rendus des factures du transitaire (et de leurs avoirs) : familles G1 à G12.

G1  FR  paysage, colonnes TVA par ligne, débours puis prestations
G2  EN  relevé multipage, en-têtes répétés, « carried forward / brought forward », TVA en récapitulatif
G3  DE  en-tête à deux colonnes entrelacées, montants suffixés « EUR », TVA en récapitulatif
G4  IT  bloc de totaux en tête, montants préfixés « € », TVA par ligne
G5  ES  prestations en page 1, débours (suplidos) en annexe page 2
G6  FR  totaux en tête, ligne « droits et taxes » combinée, remise négative, tampon « ACQUITTÉ »
G7  UBL 2.1 seul (sans PDF)
G8  CII D16B seul (sans PDF)
G9  FR  codes TVA lettres + montants, filigrane « COPIE », annotation manuscrite
G10 EN  corps à deux colonnes (débours | prestations), montants suffixés « EUR »
G11 FR/EN intégrateur express, forfait petits envois avec base imprimée
G12 NL  factures de débours et de prestations séparées
"""

from __future__ import annotations

from decimal import Decimal as D

from lxml import etree
from reportlab.lib.colors import HexColor

from . import fmtx as F
from .pdfkit import LIGHT, Pdf
from .util import FICTIF

TITLES = {
    "fr": {"facture": "FACTURE", "avoir": "AVOIR", "complementaire": "FACTURE COMPLÉMENTAIRE", "debours": "FACTURE DE DÉBOURS",
           "prestations": "FACTURE DE PRESTATIONS", "complement_prestations": "FACTURE — COMPLÉMENT DE PRESTATIONS"},
    "en": {"facture": "INVOICE", "avoir": "CREDIT NOTE", "complementaire": "SUPPLEMENTARY INVOICE", "debours": "DISBURSEMENT INVOICE",
           "prestations": "SERVICES INVOICE", "complement_prestations": "INVOICE — ADDITIONAL SERVICES"},
    "de": {"facture": "RECHNUNG", "avoir": "GUTSCHRIFT", "complementaire": "NACHBERECHNUNG", "debours": "AUSLAGENRECHNUNG",
           "prestations": "LEISTUNGSRECHNUNG", "complement_prestations": "RECHNUNG — ZUSATZLEISTUNGEN"},
    "it": {"facture": "FATTURA", "avoir": "NOTA DI CREDITO", "complementaire": "FATTURA INTEGRATIVA", "debours": "FATTURA ANTICIPAZIONI",
           "prestations": "FATTURA SERVIZI", "complement_prestations": "FATTURA — SERVIZI AGGIUNTIVI"},
    "es": {"facture": "FACTURA", "avoir": "FACTURA RECTIFICATIVA (ABONO)", "complementaire": "FACTURA COMPLEMENTARIA",
           "debours": "FACTURA DE SUPLIDOS", "prestations": "FACTURA DE SERVICIOS", "complement_prestations": "FACTURA — SERVICIOS ADICIONALES"},
    "nl": {"facture": "FACTUUR", "avoir": "CREDITNOTA", "complementaire": "AANVULLENDE FACTUUR", "debours": "VOORSCHOTFACTUUR",
           "prestations": "DIENSTENFACTUUR", "complement_prestations": "FACTUUR — AANVULLENDE DIENSTEN"},
}

LBL = {
    "fr": {"no": "N°", "date": "Date", "client": "Client", "tva": "N° TVA", "mrn": "MRN", "ref_tr": "LTA / B/L / CMR", "refs_ci": "Factures fournisseur",
           "deb": "Débours (hors champ de TVA)", "srv": "Prestations", "tot_deb": "Total débours", "tot_srv": "Total prestations HT",
           "tot_ht": "Total HT", "tva_t": "TVA", "tot_ttc": "Total TTC", "net": "Net à payer", "qty": "Qté", "pu": "P.U.", "ht": "Montant HT",
           "rate": "TVA %", "vat": "Montant TVA", "ttc": "TTC", "desig": "Désignation", "origin": "Facture d'origine", "motif": "Motif",
           "pay": "Règlement à réception par virement", "due": "Échéance"},
    "en": {"no": "No.", "date": "Date", "client": "Customer", "tva": "VAT No.", "mrn": "MRN", "ref_tr": "AWB / B/L", "refs_ci": "Supplier invoices",
           "deb": "Disbursements (outside the scope of VAT)", "srv": "Our charges", "tot_deb": "Total disbursements", "tot_srv": "Total charges (net)",
           "tot_ht": "Total net", "tva_t": "VAT", "tot_ttc": "Total incl. VAT", "net": "Balance due", "qty": "Qty", "pu": "Rate", "ht": "Net amount",
           "rate": "VAT %", "vat": "VAT", "ttc": "Gross", "desig": "Description", "origin": "Original invoice", "motif": "Reason",
           "pay": "Payment by bank transfer on receipt", "due": "Due date"},
    "de": {"no": "Nr.", "date": "Datum", "client": "Rechnungsempfänger", "tva": "USt-IdNr.", "mrn": "MRN", "ref_tr": "AWB / B/L", "refs_ci": "Lieferantenrechnungen",
           "deb": "Zollabgaben und Auslagen (nicht steuerbar)", "srv": "Leistungen", "tot_deb": "Summe Auslagen", "tot_srv": "Summe Leistungen netto",
           "tot_ht": "Nettobetrag gesamt", "tva_t": "MwSt.", "tot_ttc": "Rechnungsbetrag", "net": "Zahlbetrag", "qty": "Menge", "pu": "Einzelpreis",
           "ht": "Betrag", "rate": "MwSt. %", "vat": "MwSt.", "ttc": "Brutto", "desig": "Leistung", "origin": "Ursprungsrechnung", "motif": "Grund",
           "pay": "Zahlbar sofort ohne Abzug", "due": "Fällig"},
    "it": {"no": "N.", "date": "Data", "client": "Cliente", "tva": "Partita IVA", "mrn": "MRN", "ref_tr": "AWB / B/L", "refs_ci": "Fatture fornitore",
           "deb": "Anticipazioni (escluse art. 15)", "srv": "Servizi", "tot_deb": "Totale anticipazioni", "tot_srv": "Imponibile servizi",
           "tot_ht": "Totale imponibile + anticipazioni", "tva_t": "IVA", "tot_ttc": "Totale documento", "net": "Netto a pagare", "qty": "Q.tà",
           "pu": "Prezzo", "ht": "Importo", "rate": "IVA %", "vat": "IVA", "ttc": "Totale", "desig": "Descrizione", "origin": "Fattura di riferimento",
           "motif": "Causale", "pay": "Pagamento: bonifico a vista", "due": "Scadenza"},
    "es": {"no": "N.º", "date": "Fecha", "client": "Cliente", "tva": "NIF-IVA", "mrn": "MRN / DUA", "ref_tr": "AWB / B/L", "refs_ci": "Facturas proveedor",
           "deb": "Suplidos (no sujetos a IVA)", "srv": "Servicios", "tot_deb": "Total suplidos", "tot_srv": "Base imponible",
           "tot_ht": "Total sin IVA (servicios + suplidos)", "tva_t": "IVA", "tot_ttc": "TOTAL FACTURA", "net": "Líquido a pagar", "qty": "Cant.",
           "pu": "Precio", "ht": "Importe", "rate": "IVA %", "vat": "Cuota IVA", "ttc": "Total", "desig": "Concepto", "origin": "Factura rectificada",
           "motif": "Motivo", "pay": "Pago por transferencia", "due": "Vencimiento"},
    "nl": {"no": "Nr.", "date": "Datum", "client": "Klant", "tva": "Btw-nr.", "mrn": "MRN", "ref_tr": "AWB / B/L", "refs_ci": "Leveranciersfacturen",
           "deb": "Voorschotten (buiten btw)", "srv": "Diensten", "tot_deb": "Totaal voorschotten", "tot_srv": "Totaal diensten excl. btw",
           "tot_ht": "Totaal excl. btw", "tva_t": "Btw", "tot_ttc": "Totaal incl. btw", "net": "Te betalen", "qty": "Aantal", "pu": "Prijs",
           "ht": "Bedrag", "rate": "Btw %", "vat": "Btw", "ttc": "Totaal", "desig": "Omschrijving", "origin": "Oorspronkelijke factuur",
           "motif": "Reden", "pay": "Betaling per overschrijving", "due": "Vervaldatum"},
}


def tr_ref(r, style):
    if style == "spaced" and "-" in r:
        a, b = r.split("-", 1)
        return f"{a} {b[:4]} {b[4:]}"
    if style == "slashed" and "-" in r:
        a, b = r.split("-", 1)
        return f"{a}/{b}"
    return r


def _lang(doc):
    lg = doc["lang"]
    return "fr" if lg == "fr_en" else lg


def _title(doc):
    return TITLES[_lang(doc)][doc.get("title_kind", "facture")]


def _is_av(doc):
    return doc["kind"] == "av"


def _sections(doc):
    deb = [ln for ln in doc["lines"] if ln["nature"].startswith("debours")]
    srv = [ln for ln in doc["lines"] if not ln["nature"].startswith("debours")]
    return deb, srv


def _lib(ln, num):
    s = ln["libelle"]
    if ln.get("date_debut") and ln.get("date_fin"):
        s += f" ({F.date(ln['date_debut'], 'dmy/')} – {F.date(ln['date_fin'], 'dmy/')})"
    return s


def _base(ln, num):
    if ln.get("base_info"):
        r, n = ln["base_info"]
        return f" — {F.amt(r, num)} × {n}"
    return ""


def _totals(doc):
    if _is_av(doc):
        return {"tot_ht": doc["total_ht"], "tva": doc["total_tva"], "ttc": doc["total_ttc"]}
    return {"tot_deb": doc["total_debours"], "tot_ht": doc["total_ht"], "tva": doc["total_tva"], "ttc": doc["total_ttc"],
            "net": doc["net"]}


def _neg(v, num, mode, av):
    s = F.amt(v, num)
    if not av:
        return s
    if mode == "minus":
        return "-" + s
    if mode == "paren":
        return f"({s})"
    return s


def _refs_lines(doc, lab, style="raw"):
    out = []
    mr = doc.get("refs_mrn") or []
    if mr:
        out.append(f"{lab['mrn']}: " + ", ".join(mr))
    tr = doc.get("refs_transport") or []
    if tr:
        out.append(f"{lab['ref_tr']}: " + ", ".join(tr_ref(r, doc.get("transport_ref_style", "raw")) for r in tr))
    if _is_av(doc):
        if doc["refs_facture_origine"]:
            out.append(f"{lab['origin']}: " + ", ".join(doc["refs_facture_origine"]))
        if doc.get("motif"):
            out.append(f"{lab['motif']}: {doc['motif']}")
    return out


def _parties(p, doc, lab, x1, x2, y, size=8.5):
    em = doc["emetteur"]
    cl = doc["client"]
    p.lines(x1, y, [em["nom"]] + em["adresse"] + [f"{lab['tva']}: {em['tva']}"], size=size)
    p.text(x2, y + 12, lab["client"], size=7.5, style="B")
    p.lines(x2, y, [cl["nom"]] + cl["adresse"] + [f"{lab['tva']}: {cl['tva']}"], size=size)


def _multi_mrn(doc):
    return len({ln["mrn"] for ln in doc["lines"] if ln["mrn"]}) > 1


# ---------------------------------------------------------------------------
# G1 — Fictilog (FR, paysage)
# ---------------------------------------------------------------------------

def render_g1(doc, rng):
    lab = LBL["fr"]
    num = "frs"
    av = _is_av(doc)
    p = Pdf(land=True, title=f"{_title(doc)} {doc['numero']}", family="Sans", lang_mark="fr")
    W, H = p.W, p.H
    acc = HexColor("#1a5276")
    y = H - 44
    p.logo(36, y - 26, "FT", rng, color=acc, size=34)
    p.text(80, y - 4, doc["emetteur"]["nom"], size=14, style="B", color=acc)
    p.text(80, y - 17, " — ".join(doc["emetteur"]["adresse"]) + f" — TVA {doc['emetteur']['tva']}", size=7.5)
    p.text(W - 36, y - 4, f"{_title(doc)} N° {doc['numero']}", size=14, style="B", align="r")
    p.text(W - 36, y - 18, f"du {F.date(doc['date'], 'dmy/')}", size=9, align="r")
    y -= 46
    cl = doc["client"]
    p.rect(W - 300, y - 62, 264, 62, lw=0.6)
    p.lines(W - 292, y - 12, [cl["nom"]] + cl["adresse"] + [f"TVA intracom. : {cl['tva']}"], size=8.5)
    p.lines(36, y - 4, _refs_lines(doc, lab), size=8.5)
    y -= 80
    cols = [(lab["desig"], 250, "l"), ("Réf. MRN", 150, "l"), (lab["qty"], 40, "r"), ("P.U. HT", 70, "r"), (lab["ht"], 80, "r"),
            (lab["rate"], 46, "r"), (lab["vat"], 70, "r"), ("Montant TTC", 63, "r")]
    deb, srv = _sections(doc)
    rows = []
    for title, sec in ((lab["deb"].upper(), deb), (lab["srv"].upper(), srv)):
        if not sec:
            continue
        rows.append([title, None, None, None, None, None, None, None])
        for ln in sec:
            rows.append([_lib(ln, num) + _base(ln, num), ln["mrn"] or "", F.qty(ln["qty"], num), F.amt(ln["pu"], num) + " €",
                         _neg(ln["ht"], num, "minus", av) + " €", F.amt(ln["vat_rate"], num), F.amt(ln["vat"], num) + " €",
                         F.amt(ln["ht"] + ln["vat"], num) + " €"])
    y = p.table(36, y, cols, rows, size=8, grid="h", head_fill=LIGHT, bottom=120)
    t = _totals(doc)
    y -= 8
    items = []
    if not av:
        items.append((lab["tot_deb"], t["tot_deb"]))
    items += [(lab["tot_ht"], t["tot_ht"]), (f"{lab['tva_t']} 20 %", t["tva"]), (lab["tot_ttc"], t["ttc"])]
    if not av:
        items.append((lab["net"], t["net"]))
    for i, (k, v) in enumerate(items):
        bold = "B" if i == len(items) - 1 else ""
        p.text(W - 160, y, k, size=9, style=bold, align="r")
        p.text(W - 38, y, _neg(v, num, "minus", av) + " €", size=9, style=bold, align="r")
        y -= 13
    p.text(36, 50, f"{lab['pay']} — IBAN {doc.get('iban', 'FR76 0000 0000 0000 FICT')}", size=7.5)
    if doc.get("hidden_instr"):
        p.hidden_text(36, 34, doc["hidden_instr"])
    return p.save()


# ---------------------------------------------------------------------------
# G2 — Placebo Freight (EN, relevé multipage)
# ---------------------------------------------------------------------------

def render_g2(doc, rng):
    lab = LBL["en"]
    num = "en"
    av = _is_av(doc)
    p = Pdf(title=f"{_title(doc)} {doc['numero']}", family="Free", lang_mark="en")
    W, H = p.W, p.H
    acc = HexColor("#7d3c98")
    em = doc["emetteur"]

    def header(first):
        y = H - 40
        p.text(36, y, em["nom"].upper(), size=12, style="B", color=acc)
        p.text(W - 36, y, (("STATEMENT / " if doc.get("est_releve") else "") + _title(doc)), size=12, style="B", align="r")
        p.text(W - 36, y - 13, f"{lab['no']} {doc['numero']}  —  {F.date(doc['date'], 'en_long')}", size=8.5, align="r")
        p.text(W - 36, y - 24, f"Page {p.page_no}", size=7.5, align="r")
        return y - 34

    y = header(True)
    p.lines(36, y, em["adresse"] + [f"VAT {em['tva']}"], size=8)
    cl = doc["client"]
    p.text(320, y + 2, "Account", size=7.5, style="B", color=acc)
    p.lines(320, y - 10, [cl["nom"]] + cl["adresse"] + [f"VAT {cl['tva']}"], size=8)
    y -= 70
    # tableau des envois
    mrns = doc.get("refs_mrn") or []
    trs = doc.get("refs_transport") or []
    if mrns:
        rows = [[tr_ref(trs[i], doc.get("transport_ref_style", "raw")) if i < len(trs) else "", m, F.date(doc["date"], "dmy/")] for i, m in enumerate(mrns)]
        y = p.table(36, y, [("Air waybill / B/L", 160, "l"), ("MRN", 170, "l"), ("Statement date", 100, "l")], rows, size=8, grid="h", head_fill=LIGHT)
        y -= 14
    if _is_av(doc) and doc["refs_facture_origine"]:
        p.text(36, y, f"{lab['origin']}: {', '.join(doc['refs_facture_origine'])}   {lab['motif']}: {doc.get('motif', '')}", size=8.5)
        y -= 16
    cols = [("MRN", 120, "l"), ("Description", 230, "l"), ("Qty", 40, "r"), ("VAT code", 52, "c"), ("Net amount", 80, "r")]
    running = [D(0)]
    order = []
    deb, srv = _sections(doc)
    for ln in deb + srv:
        order.append(ln)
    rows = []
    for ln in order:
        code = "S" if ln["vat_rate"] > 0 else "O"
        rows.append([ln["mrn"] or "", _lib(ln, num), F.qty(ln["qty"], num), code, "EUR " + _neg(ln["ht"], num, "paren", av)])

    # rendu manuel pour gérer les reports de page
    rh = 23
    tw = sum(c[1] for c in cols)

    def head(yh):
        p.rect(36, yh - rh, tw, rh, lw=0.3, fill=LIGHT)
        cx = 36
        for t, w, al in cols:
            if al == "r":
                p.text(cx + w - 3, yh - 14, t, size=8, style="B", align="r")
            elif al == "c":
                p.text(cx + w / 2, yh - 14, t, size=8, style="B", align="c")
            else:
                p.text(cx + 3, yh - 14, t, size=8, style="B")
            cx += w
        return yh - rh

    y = head(y)
    for i, (ln, r) in enumerate(zip(order, rows)):
        if y - rh < 150:
            p.text(36 + tw - 3, y - 14, f"Carried forward  EUR {F.amt(running[0], num)}", size=8, style="I", align="r")
            p.new_page()
            y = header(False)
            y = head(y)
            p.text(36 + tw - 3, y - 14, f"Brought forward  EUR {F.amt(running[0], num)}", size=8, style="I", align="r")
            y -= rh
        cx = 36
        for (t, w, al), cell in zip(cols, r):
            if al == "r":
                p.text(cx + w - 3, y - 14, cell, size=8, align="r")
            elif al == "c":
                p.text(cx + w / 2, y - 14, cell, size=8, align="c")
            else:
                p.text(cx + 3, y - 14, cell, size=8)
            cx += w
        y -= rh
        p.hline(36, 36 + tw, y, lw=0.2, color=HexColor("#aaaaaa"))
        running[0] += ln["ht"]
    y -= 10
    if y < 190:
        p.new_page()
        y = header(False)
    t = _totals(doc)
    taxable = sum((ln["ht"] for ln in doc["lines"] if ln["vat_rate"] > 0), D(0))
    exempt = sum((ln["ht"] for ln in doc["lines"] if ln["vat_rate"] == 0), D(0))
    p.text(36, y, "VAT analysis", size=8.5, style="B")
    y = p.table(36, y - 6, [("Code", 50, "c"), ("Rate", 60, "r"), ("Net", 100, "r"), ("VAT", 90, "r")],
                [["S", "20.0%", "EUR " + F.amt(taxable, num), "EUR " + F.amt(t["tva"], num)], ["O", "out of scope", "EUR " + F.amt(exempt, num), "EUR 0.00"]],
                size=8, grid="h", head_fill=None)
    y -= 12
    items = []
    if not av:
        items.append((lab["tot_deb"], t["tot_deb"]))
    items += [(lab["tot_ht"], t["tot_ht"]), (lab["tva_t"], t["tva"]), (lab["tot_ttc"], t["ttc"])]
    if not av:
        items.append((lab["net"], t["net"]))
    for k, v in items:
        p.text(W - 150, y, k, size=9, align="r", style="B" if k == items[-1][0] else "")
        p.text(W - 38, y, "EUR " + _neg(v, num, "paren", av), size=9, align="r", style="B" if k == items[-1][0] else "")
        y -= 13
    if doc.get("hidden_instr"):
        p.hidden_text(36, 34, doc["hidden_instr"])
    return p.save()


# ---------------------------------------------------------------------------
# G3 — Simulacargo (DE)
# ---------------------------------------------------------------------------

def render_g3(doc, rng):
    lab = LBL["de"]
    num = "de"
    av = _is_av(doc)
    p = Pdf(title=f"{_title(doc)} {doc['numero']}", family="DV", lang_mark="de")
    W, H = p.W, p.H
    acc = HexColor("#922b21")
    em = doc["emetteur"]
    cl = doc["client"]
    y = H - 44
    p.text(36, y, em["nom"], size=15, style="B", color=acc)
    p.text(36, y - 12, "Internationale Spedition · Zollagentur", size=8, color=HexColor("#555555"))
    y -= 36
    # en-tête entrelacé : chaque ligne porte un élément du client à gauche et de la facture à droite
    left = [lab["client"] + ":", cl["nom"]] + cl["adresse"] + [f"{lab['tva']} {cl['tva']}"]
    right = [f"{_title(doc)}", f"{lab['no']} {doc['numero']}", f"{lab['date']}: {F.date(doc['date'], 'dmy.')}",
             f"Absender: {em['nom']}", " / ".join(em["adresse"][:2]), f"{lab['tva']} {em['tva']}"]
    n = max(len(left), len(right))
    for i in range(n):
        if i < len(left):
            p.text(36, y, left[i], size=8.8, style="B" if i in (0,) else "")
        if i < len(right):
            p.text(300, y, right[i], size=8.8 if i else 12, style="B" if i in (0, 1) else "")
        y -= 12.5
    y -= 6
    for r in _refs_lines(doc, lab):
        p.text(36, y, r, size=8.5)
        y -= 11
    y -= 8
    deb, srv = _sections(doc)
    show_mrn = _multi_mrn(doc)
    cols = [("Pos.", 30, "c"), (lab["desig"], 180 if show_mrn else 290, "l")] + ([("MRN", 110, "l")] if show_mrn else []) + \
           [(lab["qty"], 40, "r"), (lab["pu"], 75, "r"), (lab["ht"], 88, "r")]
    pos = 0
    for title, sec in ((lab["deb"], deb), (lab["srv"] + " (MwSt. 20 %)", srv)):
        if not sec:
            continue
        p.text(36, y, title, size=9, style="B", color=acc)
        y -= 4
        rows = []
        for ln in sec:
            pos += 1
            rows.append([str(pos), _lib(ln, num) + _base(ln, num)] + ([ln["mrn"] or ""] if show_mrn else []) +
                        [F.qty(ln["qty"], num), F.amt(ln["pu"], num) + " EUR", _neg(ln["ht"], num, "minus", av) + " EUR"])
        y = p.table(36, y, cols, rows, size=8, grid="h", head_fill=HexColor("#f5eef8"), bottom=150, wrap_col=1)
        y -= 14
    t = _totals(doc)
    items = []
    if not av:
        items.append((lab["tot_deb"], t["tot_deb"]))
        items.append((lab["tot_srv"], t["tot_ht"] - t["tot_deb"]))
    items += [(lab["tot_ht"], t["tot_ht"]), (f"{lab['tva_t']} 20 %", t["tva"]), (lab["tot_ttc"], t["ttc"])]
    for k, v in items:
        last = k == items[-1][0]
        p.text(W - 150, y, k, size=9, align="r", style="B" if last else "")
        p.text(W - 38, y, _neg(v, num, "minus", av) + " EUR", size=9, align="r", style="B" if last else "")
        y -= 13
    p.text(36, 52, lab["pay"] + f" — Bankverbindung: {doc.get('iban', 'FR76 FICT')}", size=7.5)
    if doc.get("hidden_instr"):
        p.hidden_text(36, 36, doc["hidden_instr"])
    return p.save()


# ---------------------------------------------------------------------------
# G4 — Spedizioni Immaginarie (IT, totaux en tête)
# ---------------------------------------------------------------------------

def render_g4(doc, rng):
    lab = LBL["it"]
    num = "de"
    av = _is_av(doc)
    p = Pdf(title=f"{_title(doc)} {doc['numero']}", family="Serif", lang_mark="it")
    W, H = p.W, p.H
    acc = HexColor("#117864")
    em = doc["emetteur"]
    y = H - 46
    p.text(36, y, em["nom"], size=16, style="B", color=acc)
    p.lines(36, y - 14, em["adresse"] + [f"{lab['tva']} {em['tva']}"], size=8)
    p.text(W - 36, y, _title(doc), size=14, style="B", align="r")
    p.text(W - 36, y - 14, f"{lab['no']} {doc['numero']} del {F.date(doc['date'], 'it_long')}", size=9, align="r")
    y -= 70
    # bloc des totaux en tête
    t = _totals(doc)
    p.rect(W - 260, y - 76, 224, 80, lw=1, color=acc)
    items = [(lab["tot_ttc"], t["ttc"])]
    if not av:
        items.append(("di cui anticipazioni", t["tot_deb"]))
    items += [(lab["tot_ht"], t["tot_ht"]), (f"{lab['tva_t']} 20%", t["tva"])]
    yy = y - 12
    for i, (k, v) in enumerate(items):
        p.text(W - 252, yy, k, size=10 if i == 0 else 8.5, style="B" if i == 0 else "")
        p.text(W - 44, yy, "€ " + _neg(v, num, "minus", av), size=10 if i == 0 else 8.5, style="B" if i == 0 else "", align="r")
        yy -= 16 if i == 0 else 13
    cl = doc["client"]
    p.text(36, y, lab["client"], size=8, style="B", color=acc)
    p.lines(36, y - 12, [cl["nom"]] + cl["adresse"] + [f"{lab['tva']} {cl['tva']}"], size=8.5)
    y -= 92
    for r in _refs_lines(doc, lab):
        p.text(36, y, r, size=8.5)
        y -= 11
    y -= 6
    show_mrn = _multi_mrn(doc)
    cols = [(lab["desig"], 152 if show_mrn else 260, "l")] + ([("MRN", 108, "l")] if show_mrn else []) + \
           [(lab["qty"], 34, "r"), (lab["pu"], 62, "r"), (lab["ht"], 66, "r"), ("Cod. IVA", 46, "c"), (lab["vat"], 55, "r")]
    rows = []
    for ln in doc["lines"]:
        code = "20%" if ln["vat_rate"] > 0 else "E15"
        rows.append([_lib(ln, num) + _base(ln, num)] + ([ln["mrn"] or ""] if show_mrn else []) +
                    [F.qty(ln["qty"], num), "€ " + F.amt(ln["pu"], num), "€ " + _neg(ln["ht"], num, "minus", av), code,
                     "€ " + F.amt(ln["vat"], num)])
    y = p.table(36, y, cols, rows, size=8, grid="full", head_fill=HexColor("#e8f8f5"), bottom=100, wrap_col=0)
    y -= 12
    p.text(36, y, "E15 = esclusa ex art. 15 (anticipazioni in nome e per conto del cliente); 20% = IVA francese", size=7.2, style="I")
    p.text(36, 52, lab["pay"], size=7.5)
    if doc.get("hidden_instr"):
        p.hidden_text(36, 36, doc["hidden_instr"])
    return p.save()


# ---------------------------------------------------------------------------
# G5 — Tránsitos Ficticios (ES, suplidos en annexe)
# ---------------------------------------------------------------------------

def render_g5(doc, rng):
    lab = LBL["es"]
    num = "de"
    av = _is_av(doc)
    p = Pdf(title=f"{_title(doc)} {doc['numero']}", family="Sans", lang_mark="es")
    W, H = p.W, p.H
    acc = HexColor("#b9770e")
    em = doc["emetteur"]
    cl = doc["client"]
    deb, srv = _sections(doc)
    y = H - 46
    p.logo(36, y - 24, "TF", rng, color=acc)
    p.text(76, y - 4, em["nom"], size=14, style="B")
    p.text(76, y - 16, ", ".join(em["adresse"]) + f" · {lab['tva']} {em['tva']}", size=7.5)
    y -= 46
    p.rect(36, y - 64, W - 72, 64, lw=0.6)
    p.text(44, y - 14, _title(doc), size=12, style="B", color=acc)
    p.text(44, y - 28, f"{lab['no']} {doc['numero']}", size=9)
    p.text(44, y - 40, f"{lab['date']}: {F.date(doc['date'], 'es_long')}", size=9)
    p.lines(300, y - 14, [cl["nom"]] + cl["adresse"][:2] + [f"{lab['tva']}: {cl['tva']}"], size=8.5)
    y -= 80
    for r in _refs_lines(doc, lab):
        p.text(36, y, r, size=8.5)
        y -= 11
    y -= 6
    cols = [(lab["desig"], 230, "l"), (lab["qty"], 40, "r"), (lab["pu"], 70, "r"), (lab["ht"], 75, "r"), (lab["rate"], 40, "r"), (lab["vat"], 68, "r")]
    rows = [[_lib(ln, num), F.qty(ln["qty"], num), F.amt(ln["pu"], num) + " €", _neg(ln["ht"], num, "minus", av) + " €",
             F.amt(ln["vat_rate"], num), F.amt(ln["vat"], num) + " €"] for ln in srv]
    if deb:
        tdeb = sum((ln["ht"] for ln in deb), D(0))
        rows.append(["Suplidos según anexo (página 2)", None, None, _neg(tdeb, num, "minus", av) + " €", "—", None])
    y = p.table(36, y, cols, rows, size=8, grid="h", head_fill=HexColor("#fdf2e9"), bottom=140, wrap_col=0)
    y -= 12
    t = _totals(doc)
    items = []
    if not av:
        items = [(lab["tot_srv"], t["tot_ht"] - t["tot_deb"]), (f"{lab['tva_t']} 20 %", t["tva"]), (lab["tot_deb"], t["tot_deb"]),
                 (lab["tot_ht"], t["tot_ht"]), (lab["tot_ttc"], t["ttc"])]
    else:
        items = [(lab["tot_ht"], t["tot_ht"]), (f"{lab['tva_t']} 20 %", t["tva"]), (lab["tot_ttc"], t["ttc"])]
    for k, v in items:
        last = k == items[-1][0]
        p.text(W - 150, y, k, size=9, align="r", style="B" if last else "")
        p.text(W - 38, y, _neg(v, num, "minus", av) + " €", size=9, align="r", style="B" if last else "")
        y -= 13
    p.text(36, 52, lab["pay"], size=7.5)
    if deb:
        p.new_page()
        y = H - 50
        p.text(36, y, f"ANEXO — Relación de suplidos · {_title(doc)} {doc['numero']}", size=12, style="B", color=acc)
        y -= 24
        rows = [[_lib(ln, num) + _base(ln, num), ln["mrn"] or (doc.get("refs_mrn") or [""])[0], _neg(ln["ht"], num, "minus", av) + " €"] for ln in deb]
        y = p.table(36, y, [(lab["desig"], 240, "l"), ("DUA / MRN", 150, "l"), (lab["ht"], 90, "r")], rows, size=8.5, grid="full",
                    head_fill=HexColor("#fdf2e9"))
        y -= 14
        p.text(36 + 480 - 3, y, f"{lab['tot_deb']}: " + _neg(sum((ln['ht'] for ln in deb), D(0)), num, "minus", av) + " €", size=9.5, style="B", align="r")
        p.text(36, y - 24, "Importes satisfechos en nombre y por cuenta del cliente (art. 78.Tres.3.º LIVA) — DONNÉES FICTIVES.", size=7.2, style="I")
    if doc.get("hidden_instr"):
        p.hidden_text(36, 36, doc["hidden_instr"])
    return p.save()


# ---------------------------------------------------------------------------
# G6 — Demofret (FR, totaux en tête, « droits et taxes » combinés, tampon)
# ---------------------------------------------------------------------------

def render_g6(doc, rng):
    lab = LBL["fr"]
    num = "fr"
    av = _is_av(doc)
    p = Pdf(title=f"{_title(doc)} {doc['numero']}", family="Free", lang_mark="fr")
    W, H = p.W, p.H
    acc = HexColor("#2e4053")
    em = doc["emetteur"]
    cl = doc["client"]
    y = H - 46
    p.text(36, y, em["nom"].upper(), size=18, style="B", color=acc)
    p.text(36, y - 13, " · ".join(em["adresse"]), size=7.5)
    p.text(36, y - 23, f"TVA {em['tva']}", size=7.5)
    t = _totals(doc)
    p.rect(W - 210, y - 50, 174, 56, lw=0, fill=acc, stroke=False)
    p.text(W - 200, y - 10, (lab["net"] if not av else "Montant crédité TTC").upper(), size=8, color=HexColor("#ffffff"))
    p.text(W - 46, y - 34, _neg(t["ttc"] if av else t["net"], num, "minus", av) + " €", size=16, style="B", align="r", color=HexColor("#ffffff"))
    y -= 70
    p.text(36, y, f"{_title(doc)} n° {doc['numero']}", size=12, style="B")
    p.text(36, y - 14, f"Date : {F.date(doc['date'], 'fr_long')}", size=9)
    p.lines(330, y, [cl["nom"]] + cl["adresse"] + [f"N° TVA : {cl['tva']}"], size=8.5)
    y -= 66
    for r in _refs_lines(doc, lab):
        p.text(36, y, r, size=8.5)
        y -= 11
    y -= 8
    cols = [(lab["desig"], 250, "l"), (lab["qty"], 36, "r"), (lab["pu"], 70, "r"), (lab["ht"], 76, "r"), (lab["rate"], 40, "r"), (lab["vat"], 60, "r")]
    rows = [[_lib(ln, num) + _base(ln, num), F.qty(ln["qty"], num), F.amt(ln["pu"], num), _neg(ln["ht"], num, "minus", av),
             F.amt(ln["vat_rate"], num), F.amt(ln["vat"], num)] for ln in doc["lines"]]
    y = p.table(36, y, cols, rows, size=8.2, grid="h", head_fill=HexColor("#d6dbdf"), bottom=140, wrap_col=0)
    y -= 12
    items = [(lab["tot_ht"], t["tot_ht"]), ("TVA 20 %", t["tva"]), (lab["tot_ttc"], t["ttc"])]
    ty = y
    for k, v in items:
        p.text(W - 150, y, k, size=9, align="r")
        p.text(W - 38, y, _neg(v, num, "minus", av) + " €", size=9, align="r")
        y -= 13
    if not av:
        p.stamp(W - 130, ty - 14, "ACQUITTÉ", size=22, angle=14, alpha=0.45)
    p.text(36, 52, "Les débours sont refacturés à l'identique, sans TVA. " + lab["pay"], size=7.5)
    if doc.get("hidden_instr"):
        p.hidden_text(36, 36, doc["hidden_instr"])
    return p.save()


# ---------------------------------------------------------------------------
# G9 — Mirage Douane & Fret (FR, codes lettres, filigrane COPIE, manuscrit)
# ---------------------------------------------------------------------------

def render_g9(doc, rng):
    lab = LBL["fr"]
    num = "frs"
    av = _is_av(doc)
    p = Pdf(title=f"{_title(doc)} {doc['numero']}", family="Serif", lang_mark="fr")
    W, H = p.W, p.H
    acc = HexColor("#5b2c6f")
    em = doc["emetteur"]
    cl = doc["client"]
    y = H - 48
    p.text(W / 2, y, em["nom"], size=17, style="B", align="c", color=acc)
    p.text(W / 2, y - 13, " – ".join(em["adresse"]) + f" – TVA {em['tva']}", size=7.5, align="c")
    p.hline(36, W - 36, y - 20, lw=1.4, color=acc)
    y -= 44
    p.text(36, y, f"{_title(doc)}  {doc['numero']}", size=13, style="B")
    p.text(36, y - 14, f"Lyon, le {F.date(doc['date'], 'dmy/')}", size=9)
    p.rect(W - 280, y - 64, 244, 70, lw=0.5)
    p.lines(W - 272, y - 6, [cl["nom"]] + cl["adresse"] + [f"TVA : {cl['tva']}"], size=8.5)
    y -= 80
    for r in _refs_lines(doc, lab):
        p.text(36, y, r, size=8.5)
        y -= 11
    y -= 6
    show_mrn = _multi_mrn(doc)
    cols = [("Code", 30, "c"), (lab["desig"], 117 if show_mrn else 225, "l")] + ([("MRN", 108, "l")] if show_mrn else []) + \
           [(lab["qty"], 34, "r"), (lab["pu"], 60, "r"), (lab["ht"], 72, "r"), ("TVA", 46, "c")]
    cols.append((lab["vat"], 523 - sum(c[1] for c in cols), "r"))
    rows = []
    for ln in doc["lines"]:
        code = "A" if ln["vat_rate"] > 0 else "E"
        rows.append([code, _lib(ln, num) + _base(ln, num)] + ([ln["mrn"] or ""] if show_mrn else []) +
                    [F.qty(ln["qty"], num), F.amt(ln["pu"], num), _neg(ln["ht"], num, "minus", av), f"{code} {F.amt(ln['vat_rate'], num)}%",
                     F.amt(ln["vat"], num)])
    y = p.table(36, y, cols, rows, size=8, grid="full", head_fill=HexColor("#f4ecf7"), bottom=150, wrap_col=1)
    y -= 6
    p.text(36, y - 4, "Codes : A = TVA 20 % ; E = débours exonérés (art. 267-II-2° CGI)", size=7, style="I")
    y -= 20
    t = _totals(doc)
    items = []
    if not av:
        items.append((lab["tot_deb"], t["tot_deb"]))
    items += [(lab["tot_ht"], t["tot_ht"]), ("TVA (code A)", t["tva"]), (lab["tot_ttc"], t["ttc"])]
    ytot = y
    for k, v in items:
        p.text(W - 150, y, k, size=9.5, align="r")
        p.text(W - 38, y, _neg(v, num, "minus", av) + " EUR", size=9.5, align="r")
        y -= 14
    p.watermark("COPIE", size=110, alpha=0.10)
    p.handwriting(W - 260, ytot - 70, rng.choice(["Vu - OK compta", "Bon pour accord", "à régler fin de mois", "Réglé le " + F.date(doc["date"], "dmy/")]),
                  rng, size=14, angle=rng.uniform(-8, 4))
    p.handwriting(48, 120, rng.choice(["Dossier n° " + str(rng.randint(100, 999)), "voir LTA jointe", "cpte 6241"]), rng, size=12, angle=rng.uniform(-5, 5))
    if doc.get("hidden_instr"):
        p.hidden_text(36, 36, doc["hidden_instr"])
    return p.save()


# ---------------------------------------------------------------------------
# G10 — Chimera Customs Brokers (EN, deux colonnes)
# ---------------------------------------------------------------------------

def render_g10(doc, rng):
    lab = LBL["en"]
    num = "en"
    av = _is_av(doc)
    p = Pdf(title=f"{_title(doc)} {doc['numero']}", family="Sans", lang_mark="en")
    W, H = p.W, p.H
    acc = HexColor("#145a32")
    em = doc["emetteur"]
    cl = doc["client"]
    y = H - 44
    p.rect(0, y - 14, W, 38, lw=0, fill=acc, stroke=False)
    p.text(36, y, em["nom"], size=15, style="B", color=HexColor("#ffffff"))
    p.text(W - 36, y, _title(doc), size=14, style="B", align="r", color=HexColor("#ffffff"))
    y -= 34
    p.lines(36, y, em["adresse"] + [f"VAT {em['tva']}"], size=7.8)
    p.lines(W - 36, y, [f"{lab['no']} {doc['numero']}", f"{lab['date']} {F.date(doc['date'], 'en_long')}"], size=9, align="r")
    y -= 50
    p.text(36, y, "Invoice to", size=7.5, style="B", color=acc)
    p.lines(36, y - 11, [cl["nom"]] + cl["adresse"] + [f"VAT {cl['tva']}"], size=8.5)
    p.lines(300, y - 11, _refs_lines(doc, lab), size=8)
    y -= 80
    deb, srv = _sections(doc)
    colw = (W - 72 - 16) / 2

    def column(x, title, sec, yy):
        p.text(x, yy, title, size=9, style="B", color=acc)
        yy -= 4
        rows = [[_lib(ln, num) + _base(ln, num) + (f" [{ln['mrn']}]" if _multi_mrn(doc) and ln["mrn"] else ""),
                 F.qty(ln["qty"], num), _neg(ln["ht"], num, "paren", av) + " EUR"] for ln in sec]
        return p.table(x, yy, [("Item", colw - 110, "l"), ("Qty", 30, "r"), ("Amount", 80, "r")], rows, size=7.6, grid="h",
                       head_fill=HexColor("#e9f7ef"), wrap_col=0, bottom=150)

    y1 = column(36, "Disbursements paid on your behalf", deb, y) if deb else y
    y2 = column(36 + colw + 16, "Our charges (VAT 20%)", srv, y) if srv else y
    y = min(y1, y2) - 16
    t = _totals(doc)
    items = []
    if not av:
        items.append((lab["tot_deb"], t["tot_deb"]))
        items.append((lab["tot_srv"], t["tot_ht"] - t["tot_deb"]))
    items += [(lab["tot_ht"], t["tot_ht"]), ("VAT @ 20% on charges", t["tva"]), (lab["tot_ttc"], t["ttc"])]
    for k, v in items:
        last = k == items[-1][0]
        p.text(W - 150, y, k, size=9, align="r", style="B" if last else "")
        p.text(W - 38, y, _neg(v, num, "paren", av) + " EUR", size=9, align="r", style="B" if last else "")
        y -= 13
    p.text(36, 52, lab["pay"], size=7.5)
    if doc.get("hidden_instr"):
        p.hidden_text(36, 36, doc["hidden_instr"])
    return p.save()


# ---------------------------------------------------------------------------
# G11 — Nebula Express (intégrateur, bilingue)
# ---------------------------------------------------------------------------

BIL = {"debours_droits": "Import duty", "debours_autres_taxes": "Other duties", "debours_tva": "Import VAT",
       "debours_forfait_petits_envois": "Flat-rate duty per item", "frais_dedouanement": "Clearance fee",
       "frais_avance_fonds": "Disbursement fee", "frais_ligne_supplementaire": "Additional lines", "transport": "Delivery",
       "manutention": "Handling", "surcharge": "Surcharge", "autre_prestation": "Other", "magasinage": "Storage"}


def render_g11(doc, rng):
    lab = LBL["fr"]
    num = "en"
    av = _is_av(doc)
    p = Pdf(size=(420, 640), title=f"{_title(doc)} {doc['numero']}", family="DV", lang_mark="fr")
    W, H = p.W, p.H
    acc = HexColor("#d35400")
    em = doc["emetteur"]
    cl = doc["client"]
    y = H - 40
    p.text(24, y, em["nom"].upper(), size=13, style="B", color=acc)
    p.text(W - 24, y, ("CREDIT NOTE / AVOIR" if av else "DUTY & TAX INVOICE"), size=9.5, style="B", align="r")
    p.text(W - 24, y - 11, ("" if av else "FACTURE DROITS ET TAXES"), size=8, align="r")
    y -= 24
    p.text(24, y, " / ".join(em["adresse"][:2]) + f" · TVA {em['tva']}", size=6.8)
    y -= 18
    trs = doc.get("refs_transport") or [""]
    p.rect(24, y - 34, W - 48, 36, lw=1.2, color=acc)
    p.text(32, y - 12, "AWB / LTA", size=7)
    p.text(32, y - 28, tr_ref(trs[0], doc.get("transport_ref_style", "raw")), size=14, style="B")
    p.text(W - 32, y - 12, f"Invoice / Facture {doc['numero']}", size=8, align="r")
    p.text(W - 32, y - 26, F.date(doc["date"], "dmy/"), size=8, align="r")
    y -= 48
    addr = ", ".join(cl["adresse"])
    if p.width(addr, 7.6) <= W - 48:
        p.lines(24, y, [f"Importer / Destinataire : {cl['nom']}", addr, f"VAT / TVA : {cl['tva']}"], size=7.6)
        y -= 38
    else:   # adresse longue (2.1 : client avec représentant fiscal) : sur deux lignes
        h = len(cl["adresse"]) // 2
        p.lines(24, y, [f"Importer / Destinataire : {cl['nom']}", ", ".join(cl["adresse"][:h]), ", ".join(cl["adresse"][h:]),
                        f"VAT / TVA : {cl['tva']}"], size=7.6)
        y -= 48
    for r in _refs_lines(doc, lab)[:1] + _refs_lines(doc, lab)[2:]:
        p.text(24, y, r, size=7.6)
        y -= 10
    y -= 4
    cols = [("Description", 150, "l"), ("Base", 64, "r"), ("HT/Net", 56, "r"), ("TVA%", 34, "r"), ("TVA/VAT", 68, "r")]
    rows = []
    for ln in doc["lines"]:
        base = ""
        if ln.get("base_info"):
            r, n = ln["base_info"]
            base = f"{F.amt(r, num)} x {n}"
        elif ln["qty"] != 1:
            base = f"{F.amt(ln['pu'], num)} x {F.qty(ln['qty'], num)}"
        rows.append([f"{ln['libelle']} / {BIL.get(ln['nature'], '')}", base, "€" + _neg(ln["ht"], num, "minus", av),
                     F.amt(ln["vat_rate"], num), "€" + F.amt(ln["vat"], num)])
    y = p.table(24, y, cols, rows, size=7, grid="h", head_fill=HexColor("#fbeee6"), wrap_col=0, bottom=110)
    y -= 10
    t = _totals(doc)
    items = []
    if not av:
        items.append(("Total droits et taxes / duties & taxes", t["tot_deb"]))
    items += [("Total HT / net", t["tot_ht"]), ("TVA / VAT", t["tva"]), ("TOTAL TTC", t["ttc"])]
    for k, v in items:
        p.text(W - 100, y, k, size=7.8, align="r", style="B" if k == "TOTAL TTC" else "")
        p.text(W - 26, y, "€" + _neg(v, num, "minus", av), size=7.8, align="r", style="B" if k == "TOTAL TTC" else "")
        y -= 11
    p.text(24, 36, "Payable before delivery / payable avant livraison.", size=6.5)
    if doc.get("hidden_instr"):
        p.hidden_text(24, 26, doc["hidden_instr"])
    return p.save()


# ---------------------------------------------------------------------------
# G12 — Schaduw Expeditie (NL, débours et prestations séparés)
# ---------------------------------------------------------------------------

def render_g12(doc, rng):
    lab = LBL["nl"]
    num = "de"
    av = _is_av(doc)
    p = Pdf(title=f"{_title(doc)} {doc['numero']}", family="Sans", lang_mark="nl")
    W, H = p.W, p.H
    acc = HexColor("#1b4f72")
    em = doc["emetteur"]
    cl = doc["client"]
    y = H - 50
    p.c.setFillColor(acc)
    p.c.circle(48, y - 4, 14, stroke=0, fill=1)
    p.text(70, y - 2, em["nom"], size=15, style="B", color=acc)
    p.text(70, y - 14, " | ".join(em["adresse"]), size=7.5)
    y -= 44
    p.text(36, y, _title(doc), size=18, style="B")
    y -= 22
    meta = [(f"{lab['no']}", doc["numero"]), (lab["date"], F.date(doc["date"], "nl_long")), (lab["tva"], em["tva"])]
    for i, (k, v) in enumerate(meta):
        p.text(36 + i * 170, y, k, size=7.5, color=HexColor("#666666"))
        p.text(36 + i * 170, y - 12, v, size=9.5, style="B")
    y -= 36
    p.text(36, y, lab["client"], size=7.5, color=HexColor("#666666"))
    p.lines(36, y - 12, [cl["nom"]] + cl["adresse"] + [f"{lab['tva']} {cl['tva']}"], size=8.5)
    p.lines(300, y - 12, _refs_lines(doc, lab), size=8)
    y -= 80
    deb, srv = _sections(doc)
    if deb and not srv:
        cols = [(lab["desig"], 260, "l"), ("MRN", 150, "l"), (lab["ht"], 113, "r")]
        rows = [[_lib(ln, num) + _base(ln, num), ln["mrn"] or (doc.get("refs_mrn") or [""])[0], "€ " + _neg(ln["ht"], num, "minus", av)] for ln in deb]
    else:
        cols = [(lab["desig"], 220, "l"), (lab["qty"], 40, "r"), (lab["pu"], 66, "r"), (lab["ht"], 72, "r"), (lab["rate"], 50, "r"), (lab["vat"], 75, "r")]
        rows = [[_lib(ln, num) + _base(ln, num), F.qty(ln["qty"], num), "€ " + F.amt(ln["pu"], num), "€ " + _neg(ln["ht"], num, "minus", av),
                 F.amt(ln["vat_rate"], num), "€ " + F.amt(ln["vat"], num)] for ln in doc["lines"]]
    y = p.table(36, y, cols, rows, size=8.3, grid="h", head_fill=HexColor("#d6eaf8"), wrap_col=0, bottom=140)
    y -= 14
    t = _totals(doc)
    items = []
    if not av and deb:
        items.append((lab["tot_deb"], t["tot_deb"]))
    items += [(lab["tot_ht"], t["tot_ht"]), (f"{lab['tva_t']} 20%", t["tva"]), (lab["tot_ttc"], t["ttc"])]
    for k, v in items:
        last = k == items[-1][0]
        p.text(W - 150, y, k, size=9, align="r", style="B" if last else "")
        p.text(W - 38, y, "€ " + _neg(v, num, "minus", av), size=9, align="r", style="B" if last else "")
        y -= 13
    p.text(36, 52, lab["pay"] + " — " + ("voorschotten zonder btw doorbelast" if deb else "diensten onderworpen aan Franse btw"), size=7.5)
    if doc.get("hidden_instr"):
        p.hidden_text(36, 36, doc["hidden_instr"])
    return p.save()


RENDERERS = {"G1": render_g1, "G2": render_g2, "G3": render_g3, "G4": render_g4, "G5": render_g5, "G6": render_g6,
             "G9": render_g9, "G10": render_g10, "G11": render_g11, "G12": render_g12}


def render_ft_pdf(doc, rng) -> bytes:
    return RENDERERS[doc["family"]](doc, rng)


# ---------------------------------------------------------------------------
# G7 — UBL 2.1 (XML seul)
# ---------------------------------------------------------------------------

from .render_ci import CAC, CBC, UBL_NS, _cac, _cbc, _party  # noqa: E402


def render_g7_ubl(doc, rng) -> bytes:
    root = etree.Element(f"{{{UBL_NS}}}Invoice", nsmap={None: UBL_NS, "cac": CAC, "cbc": CBC})
    _cbc(root, "UBLVersionID", "2.1")
    _cbc(root, "CustomizationID", "urn:cen.eu:en16931:2017")
    _cbc(root, "ProfileID", "urn:fictif:bench:g2:forwarder:1")
    _cbc(root, "ID", doc["numero"])
    _cbc(root, "IssueDate", doc["date"].isoformat())
    _cbc(root, "InvoiceTypeCode", "380")
    _cbc(root, "Note", FICTIF + " - facture de test")
    if doc.get("calc_totals") is not None:
        _cbc(root, "Note", f"Total des débours : {doc['total_debours']} EUR")
    if doc.get("hidden_instr"):
        _cbc(root, "Note", doc["hidden_instr"])
    _cbc(root, "DocumentCurrencyCode", "EUR")
    for m in doc.get("refs_mrn") or []:
        a = _cac(root, "AdditionalDocumentReference")
        _cbc(a, "ID", m)
        _cbc(a, "DocumentType", "MRN")
    for r in doc.get("refs_transport") or []:
        a = _cac(root, "AdditionalDocumentReference")
        _cbc(a, "ID", tr_ref(r, doc.get("transport_ref_style", "raw")))
        _cbc(a, "DocumentType", "AWB/BL")
    em = doc["emetteur"]
    cl = doc["client"]
    _party(root, "AccountingSupplierParty", em["nom"], em["adresse"], em["tva"], "FR")
    _party(root, "AccountingCustomerParty", cl["nom"], cl["adresse"], cl["tva"], "FR")
    tt = _cac(root, "TaxTotal")
    _cbc(tt, "TaxAmount", str(doc["total_tva"]), currencyID="EUR")
    for cat, rate in (("S", D(20)), ("E", D(0))):
        lines = [ln for ln in doc["lines"] if (ln["vat_rate"] > 0) == (cat == "S")]
        if not lines:
            continue
        st = _cac(tt, "TaxSubtotal")
        _cbc(st, "TaxableAmount", str(sum((ln["ht"] for ln in lines), D(0))), currencyID="EUR")
        _cbc(st, "TaxAmount", str(sum((ln["vat"] for ln in lines), D(0))), currencyID="EUR")
        tc = _cac(st, "TaxCategory")
        _cbc(tc, "ID", cat)
        _cbc(tc, "Percent", str(rate))
        if cat == "E":
            _cbc(tc, "TaxExemptionReason", "Débours (art. 267-II-2° CGI)")
        _cbc(_cac(tc, "TaxScheme"), "ID", "VAT")
    lmt = _cac(root, "LegalMonetaryTotal")
    _cbc(lmt, "LineExtensionAmount", str(doc["total_ht"]), currencyID="EUR")
    _cbc(lmt, "TaxExclusiveAmount", str(doc["total_ht"]), currencyID="EUR")
    _cbc(lmt, "TaxInclusiveAmount", str(doc["total_ttc"]), currencyID="EUR")
    _cbc(lmt, "PayableAmount", str(doc["net"]), currencyID="EUR")
    for i, ln in enumerate(doc["lines"], 1):
        il = _cac(root, "InvoiceLine")
        _cbc(il, "ID", i)
        if ln["mrn"]:
            _cbc(il, "Note", f"MRN {ln['mrn']}")
        _cbc(il, "InvoicedQuantity", str(ln["qty"]), unitCode="C62" if ln["nature"] != "magasinage" else "DAY")
        _cbc(il, "LineExtensionAmount", str(ln["ht"]), currencyID="EUR")
        if ln.get("date_debut"):
            ip = _cac(il, "InvoicePeriod")
            _cbc(ip, "StartDate", ln["date_debut"].isoformat())
            _cbc(ip, "EndDate", ln["date_fin"].isoformat())
        it = _cac(il, "Item")
        _cbc(it, "Name", ln["libelle"])
        tc = _cac(it, "ClassifiedTaxCategory")
        _cbc(tc, "ID", "S" if ln["vat_rate"] > 0 else "E")
        _cbc(tc, "Percent", str(ln["vat_rate"]))
        _cbc(_cac(tc, "TaxScheme"), "ID", "VAT")
        if ln["vat"] and ln["nature"].startswith("debours"):
            _cbc(it, "Description", f"TVA appliquée : {ln['vat']} EUR")
        pr = _cac(il, "Price")
        _cbc(pr, "PriceAmount", str(ln["pu"]), currencyID="EUR")
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)


# ---------------------------------------------------------------------------
# G8 — CII D16B (XML seul, profil EN 16931)
# ---------------------------------------------------------------------------

RSM = "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
RAM = "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
UDT = "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100"


def _r(parent, tag, text=None, ns=RAM, **attrs):
    el = etree.SubElement(parent, f"{{{ns}}}{tag}", **{k: str(v) for k, v in attrs.items()})
    if text is not None:
        el.text = str(text)
    return el


def _dt(parent, tag, d):
    x = _r(parent, tag)
    _r(x, "DateTimeString", d.strftime("%Y%m%d"), ns=UDT, format="102")


def render_g8_cii(doc, rng) -> bytes:
    root = etree.Element(f"{{{RSM}}}CrossIndustryInvoice", nsmap={"rsm": RSM, "ram": RAM, "udt": UDT})
    ctx = _r(root, "ExchangedDocumentContext", ns=RSM)
    _r(_r(ctx, "GuidelineSpecifiedDocumentContextParameter"), "ID", "urn:cen.eu:en16931:2017")
    ed = _r(root, "ExchangedDocument", ns=RSM)
    _r(ed, "ID", doc["numero"])
    _r(ed, "TypeCode", "380")
    _dt(ed, "IssueDateTime", doc["date"])
    n = _r(ed, "IncludedNote")
    _r(n, "Content", FICTIF + " - facture de test")
    for m in doc.get("refs_mrn") or []:
        n = _r(ed, "IncludedNote")
        _r(n, "Content", f"MRN: {m}")
        _r(n, "SubjectCode", "AAI")
    for t in doc.get("refs_transport") or []:
        n = _r(ed, "IncludedNote")
        _r(n, "Content", f"Titre de transport: {tr_ref(t, doc.get('transport_ref_style', 'raw'))}")
        _r(n, "SubjectCode", "AAI")
    if doc.get("hidden_instr"):
        n = _r(ed, "IncludedNote")
        _r(n, "Content", doc["hidden_instr"])
    tx = _r(root, "SupplyChainTradeTransaction", ns=RSM)
    for i, ln in enumerate(doc["lines"], 1):
        li = _r(tx, "IncludedSupplyChainTradeLineItem")
        ad = _r(li, "AssociatedDocumentLineDocument")
        _r(ad, "LineID", i)
        if ln["mrn"]:
            _r(_r(ad, "IncludedNote"), "Content", f"MRN {ln['mrn']}")
        pr = _r(li, "SpecifiedTradeProduct")
        _r(pr, "Name", ln["libelle"])
        la = _r(li, "SpecifiedLineTradeAgreement")
        _r(_r(la, "NetPriceProductTradePrice"), "ChargeAmount", ln["pu"])
        ld = _r(li, "SpecifiedLineTradeDelivery")
        _r(ld, "BilledQuantity", ln["qty"], unitCode="DAY" if ln["nature"] == "magasinage" else "C62")
        ls = _r(li, "SpecifiedLineTradeSettlement")
        tax = _r(ls, "ApplicableTradeTax")
        _r(tax, "TypeCode", "VAT")
        _r(tax, "CategoryCode", "S" if ln["vat_rate"] > 0 else "E")
        _r(tax, "RateApplicablePercent", ln["vat_rate"])
        if ln.get("date_debut"):
            bp = _r(ls, "BillingSpecifiedPeriod")
            _dt(bp, "StartDateTime", ln["date_debut"])
            _dt(bp, "EndDateTime", ln["date_fin"])
        _r(_r(ls, "SpecifiedTradeSettlementLineMonetarySummation"), "LineTotalAmount", ln["ht"])
    ag = _r(tx, "ApplicableHeaderTradeAgreement")
    em = doc["emetteur"]
    cl = doc["client"]
    for tag, party in (("SellerTradeParty", em), ("BuyerTradeParty", cl)):
        pt = _r(ag, tag)
        _r(pt, "Name", party["nom"])
        pa = _r(pt, "PostalTradeAddress")
        _r(pa, "LineOne", party["adresse"][0])
        _r(pa, "CityName", party["adresse"][1] if len(party["adresse"]) > 1 else "")
        _r(pa, "CountryID", "FR")
        _r(_r(pt, "SpecifiedTaxRegistration"), "ID", party["tva"], schemeID="VA")
    _r(tx, "ApplicableHeaderTradeDelivery")
    st = _r(tx, "ApplicableHeaderTradeSettlement")
    _r(st, "InvoiceCurrencyCode", "EUR")
    for cat, rate in (("S", D(20)), ("E", D(0))):
        lines = [ln for ln in doc["lines"] if (ln["vat_rate"] > 0) == (cat == "S")]
        if not lines:
            continue
        tax = _r(st, "ApplicableTradeTax")
        _r(tax, "CalculatedAmount", sum((ln["vat"] for ln in lines), D(0)))
        _r(tax, "TypeCode", "VAT")
        if cat == "E":
            _r(tax, "ExemptionReason", "Débours")
        _r(tax, "BasisAmount", sum((ln["ht"] for ln in lines), D(0)))
        _r(tax, "CategoryCode", cat)
        _r(tax, "RateApplicablePercent", rate)
    ms = _r(st, "SpecifiedTradeSettlementHeaderMonetarySummation")
    _r(ms, "LineTotalAmount", doc["total_ht"])
    _r(ms, "TaxBasisTotalAmount", doc["total_ht"])
    _r(ms, "TaxTotalAmount", doc["total_tva"], currencyID="EUR")
    _r(ms, "GrandTotalAmount", doc["total_ttc"])
    _r(ms, "DuePayableAmount", doc["net"])
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)
