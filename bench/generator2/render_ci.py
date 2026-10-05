"""Rendus des factures commerciales : 9 présentations PDF (CA, CB, CC, CD, CE, CE2, CF, CG, CH),
un tableur (CK) et une facture UBL 2.1 (CU)."""

from __future__ import annotations

import io
import re
import zipfile
from decimal import Decimal as D

from lxml import etree
from reportlab.lib.colors import HexColor

from . import fmtx as F
from .pdfkit import LIGHT, Pdf
from .util import FICTIF, cur_decimals

L = {
    "en": {"inv": "COMMERCIAL INVOICE", "pf": "PROFORMA INVOICE", "no": "Invoice No.", "date": "Date", "seller": "Seller / Exporter",
           "buyer": "Bill to / Buyer", "consignee": "Ship to / Consignee", "item": "Item code", "desc": "Description", "hs": "HS code",
           "orig": "Origin", "qty": "Qty", "unit": "Unit", "pu": "Unit price", "amount": "Amount", "goods": "Subtotal goods",
           "fret": "Freight", "assurance": "Insurance", "emballage": "Packing", "remise": "Discount", "total": "TOTAL",
           "terms": "Delivery terms", "awb": "AWB No.", "bl": "B/L No.", "cmr": "CMR No.", "net": "Net weight", "gross": "Gross weight",
           "pkgs": "Packages", "pay": "Payment terms", "vat": "VAT No.", "via": "Shipped via / forwarder", "corig": "Country of origin",
           "sign": "Authorised signature", "ref": "Our ref.", "page": "Page"},
    "de": {"inv": "HANDELSRECHNUNG", "pf": "PROFORMA-RECHNUNG", "no": "Rechnung Nr.", "date": "Datum", "seller": "Verkäufer / Exporteur",
           "buyer": "Rechnungsempfänger", "consignee": "Lieferadresse", "item": "Art.-Nr.", "desc": "Bezeichnung", "hs": "Zolltarifnr.",
           "orig": "Ursprung", "qty": "Menge", "unit": "Einh.", "pu": "Einzelpreis", "amount": "Gesamtpreis", "goods": "Warenwert",
           "fret": "Fracht", "assurance": "Versicherung", "emballage": "Verpackung", "remise": "Rabatt", "total": "Rechnungsbetrag",
           "terms": "Lieferbedingungen", "awb": "Luftfrachtbrief", "bl": "Konnossement", "cmr": "CMR-Frachtbrief", "net": "Nettogewicht",
           "gross": "Bruttogewicht", "pkgs": "Packstücke", "pay": "Zahlungsbedingungen", "vat": "USt-IdNr.", "via": "Spediteur",
           "corig": "Ursprungsland", "sign": "Unterschrift", "ref": "Unser Zeichen", "page": "Seite"},
    "it": {"inv": "FATTURA COMMERCIALE", "pf": "FATTURA PROFORMA", "no": "Fattura n.", "date": "Data", "seller": "Venditore / Esportatore",
           "buyer": "Intestatario", "consignee": "Destinatario merce", "item": "Codice", "desc": "Descrizione", "hs": "Voce doganale",
           "orig": "Origine", "qty": "Q.tà", "unit": "U.M.", "pu": "Prezzo unit.", "amount": "Importo", "goods": "Totale merce",
           "fret": "Trasporto", "assurance": "Assicurazione", "emballage": "Imballo", "remise": "Sconto", "total": "TOTALE FATTURA",
           "terms": "Resa", "awb": "Lettera di vettura aerea", "bl": "Polizza di carico", "cmr": "CMR n.", "net": "Peso netto",
           "gross": "Peso lordo", "pkgs": "Colli", "pay": "Pagamento", "vat": "Partita IVA", "via": "Spedizioniere", "corig": "Paese d'origine",
           "sign": "Firma", "ref": "Rif.", "page": "Pagina"},
    "nl": {"inv": "HANDELSFACTUUR", "pf": "PROFORMAFACTUUR", "no": "Factuurnummer", "date": "Factuurdatum", "seller": "Verkoper / Exporteur",
           "buyer": "Factuuradres", "consignee": "Afleveradres", "item": "Artikelnr.", "desc": "Omschrijving", "hs": "GN-code",
           "orig": "Oorsprong", "qty": "Aantal", "unit": "Eenh.", "pu": "Prijs", "amount": "Bedrag", "goods": "Subtotaal",
           "fret": "Vracht", "assurance": "Verzekering", "emballage": "Verpakking", "remise": "Korting", "total": "TOTAAL",
           "terms": "Leveringsvoorwaarden", "awb": "Luchtvrachtbrief", "bl": "Cognossement", "cmr": "CMR", "net": "Nettogewicht",
           "gross": "Brutogewicht", "pkgs": "Colli", "pay": "Betalingsvoorwaarden", "vat": "Btw-nummer", "via": "Expediteur",
           "corig": "Land van oorsprong", "sign": "Handtekening", "ref": "Ons kenmerk", "page": "Pagina"},
    "es": {"inv": "FACTURA COMERCIAL", "pf": "FACTURA PROFORMA", "no": "Factura No.", "date": "Fecha", "seller": "Vendedor / Exportador",
           "buyer": "Facturar a", "consignee": "Consignatario", "item": "Referencia", "desc": "Descripción", "hs": "Fracción arancelaria",
           "orig": "Origen", "qty": "Cantidad", "unit": "Unidad", "pu": "Precio unitario", "amount": "Importe", "goods": "Subtotal",
           "fret": "Flete", "assurance": "Seguro", "emballage": "Embalaje", "remise": "Descuento", "total": "TOTAL",
           "terms": "Condiciones de entrega", "awb": "Guía aérea", "bl": "Conocimiento de embarque", "cmr": "CMR", "net": "Peso neto",
           "gross": "Peso bruto", "pkgs": "Bultos", "pay": "Forma de pago", "vat": "NIF / IVA", "via": "Agente de carga",
           "corig": "País de origen", "sign": "Firma autorizada", "ref": "Ref.", "page": "Página"},
    "fr": {"inv": "FACTURE", "pf": "FACTURE PRO FORMA", "no": "Facture n°", "date": "Date", "seller": "Vendeur / Exportateur",
           "buyer": "Facturé à", "consignee": "Livré à", "item": "Article", "desc": "Désignation", "hs": "N° tarif douanier",
           "orig": "Origine", "qty": "Qté", "unit": "Unité", "pu": "Prix unitaire", "amount": "Montant", "goods": "Total marchandises",
           "fret": "Fret", "assurance": "Assurance", "emballage": "Emballage", "remise": "Remise", "total": "TOTAL",
           "terms": "Conditions de livraison", "awb": "LTA n°", "bl": "Connaissement n°", "cmr": "Lettre de voiture CMR",
           "net": "Poids net", "gross": "Poids brut", "pkgs": "Colis", "pay": "Paiement", "vat": "N° TVA", "via": "Transitaire",
           "corig": "Pays d'origine", "sign": "Signature", "ref": "Notre réf.", "page": "Page"},
}

STYLES = {
    # header: disposition de l'en-tête ; tgrid: grille du tableau ; totpos: position des totaux
    "CA": {"font": "Sans", "num": "en", "date": "en_long", "header": "seller_left_title_right", "tgrid": "full", "head_fill": LIGHT,
           "totpos": "right", "accent": "#1a5276"},
    "CB": {"font": "Serif", "num": "ch", "date": "dmy.", "header": "centered_seller", "tgrid": "h", "head_fill": None,
           "totpos": "right", "accent": "#333333"},
    "CC": {"font": "Free", "num": "de", "date": "dmy/", "header": "band_title", "tgrid": "h", "head_fill": HexColor("#d5f5e3"),
           "totpos": "left_box", "accent": "#117864"},
    "CD": {"font": "DV", "num": "de", "date": "dmy-", "header": "seller_right", "tgrid": "full", "head_fill": HexColor("#fdebd0"),
           "totpos": "right", "accent": "#b9770e"},
    "CE": {"font": "Sans", "num": "en", "date": "es_long", "header": "band_title", "tgrid": "full", "head_fill": HexColor("#fadbd8"),
           "totpos": "right", "accent": "#922b21"},
    "CE2": {"font": "FSerif", "num": "de", "date": "dmy.", "header": "seller_right", "tgrid": "h", "head_fill": HexColor("#e8daef"),
            "totpos": "left_box", "accent": "#6c3483", "suffix": True},
    "CH": {"font": "Serif", "num": "ch", "date": "fr_long", "header": "centered_seller", "tgrid": "full", "head_fill": LIGHT,
           "totpos": "right", "accent": "#2e4053"},
}


def _tr_label(ci, lang):
    tr = ci["transport"]
    lab = L[lang]
    return {"air": lab["awb"], "sea": lab["bl"], "road": lab["cmr"]}[tr["mode"]]


def _lines_rows(ci, lang, num, cols_kind, suffix=False):
    rows = []
    dev = ci["devise"]
    for ln in ci["lines"]:
        r = []
        for k in cols_kind:
            if k == "no":
                r.append(str(ln["no"]))
            elif k == "item":
                r.append(ln["ref"])
            elif k == "desc":
                r.append(ln["desc"])
            elif k == "hs":
                r.append(F.hs(ln["hs10"], ci["hs_digits"], ci["hs_style"]))
            elif k == "orig":
                r.append(ln["origin"])
            elif k == "qty":
                r.append(F.qty(ln["qty"], num))
            elif k == "unit":
                r.append(ln["unit_raw"])
            elif k == "qtyu":
                r.append(f"{F.qty(ln['qty'], num)} {ln['unit_raw']}")
            elif k == "pu":
                r.append(F.pu(ln["pu"], dev, num) + (f" {dev}" if suffix else ""))
            elif k == "amount":
                r.append(F.money(ln["amount"], dev, num) + (f" {dev}" if suffix else ""))
        rows.append(r)
    return rows


def _footer_rows(ci, lang):
    lab = L[lang]
    out = []
    sub = ci["sub"]
    if len(sub) > 1:
        out.append((lab["goods"], sub["marchandises"]))
        for k in ("fret", "assurance", "emballage"):
            if k in sub:
                out.append((lab[k], sub[k]))
        if "remise" in sub:
            out.append((lab["remise"], -sub["remise"]))
    return out


def render_std(ci, rng):
    lay = ci["layout"] if ci["layout"] in STYLES else "CA"
    st = STYLES[lay]
    lang = ci["lang"] if ci["lang"] in L else "en"
    lab = L[lang]
    num = st["num"]
    dev = ci["devise"]
    sup = ci["supplier"]
    p = Pdf(title=f"{lab['inv']} {ci['numero']}", family=st["font"], lang_mark=lang)
    W, H = p.W, p.H
    acc = HexColor(st["accent"])
    title = lab["pf"] if ci["sous_type"] == "pro_forma" else lab["inv"]
    y = H - 50
    hdr = st["header"]
    seller_lines = [sup["nom"]] + sup["adresse"] + [sup["taxid"]]
    if hdr == "seller_left_title_right":
        p.logo(40, y - 22, sup["nom"], rng, color=acc)
        p.lines(80, y, seller_lines, size=8.5)
        p.text(W - 40, y, title, size=17, style="B", align="r", color=acc)
        p.rect(W - 230, y - 78, 190, 64, lw=0.6)
        p.lines(W - 224, y - 28, [f"{lab['no']}: {ci['numero']}", f"{lab['date']}: {F.date(ci['date'], st['date'])}",
                                  f"{lab['pay']}: {ci['payment_terms']}", f"{lab['terms']}: {ci['incoterm']} {ci['incoterm_lieu']}"], size=8)
        y -= 100
    elif hdr == "centered_seller":
        p.text(W / 2, y, sup["nom"], size=15, style="B", align="c")
        p.text(W / 2, y - 14, " · ".join(sup["adresse"]), size=8, align="c")
        p.text(W / 2, y - 25, sup["taxid"], size=8, align="c")
        p.hline(40, W - 40, y - 32, lw=1.2, color=acc)
        p.text(40, y - 55, f"{title}", size=14, style="B")
        p.text(W - 40, y - 55, f"{lab['no']} {ci['numero']}", size=10, style="B", align="r")
        p.text(W - 40, y - 68, f"{lab['date']}: {F.date(ci['date'], st['date'])}", size=9, align="r")
        y -= 90
    elif hdr == "band_title":
        p.rect(0, y - 8, W, 40, lw=0, fill=acc, stroke=False)
        p.text(40, y + 6, title, size=18, style="B", color=HexColor("#ffffff"))
        p.text(W - 40, y + 6, f"{lab['no']} {ci['numero']}", size=11, style="B", align="r", color=HexColor("#ffffff"))
        y -= 30
        p.lines(40, y, seller_lines, size=8.5)
        p.text(W - 40, y, f"{lab['date']}: {F.date(ci['date'], st['date'])}", size=9, align="r")
        p.text(W - 40, y - 12, f"{lab['pay']}: {ci['payment_terms']}", size=8, align="r")
        y -= 70
    else:  # seller_right
        p.text(40, y, title, size=16, style="B", color=acc)
        p.text(40, y - 16, f"{lab['no']}: {ci['numero']}", size=10)
        p.text(40, y - 29, f"{lab['date']}: {F.date(ci['date'], st['date'])}", size=9)
        p.lines(W - 40, y, seller_lines, size=8.5, align="r")
        y -= 80
    # Acheteur / destinataire
    ach = ci["acheteur"]
    buyer = [ach["nom"]] + ach["adresse"] + [f"{lab['vat']}: {ach['tva']}"] + ([f"EORI: {ci['eori']}"] if ci.get("eori") else [])
    p.text(40, y, lab["buyer"], size=8, style="B", color=acc)
    p.lines(40, y - 12, buyer, size=8.5)
    p.text(310, y, lab["consignee"], size=8, style="B", color=acc)
    p.lines(310, y - 12, [ach["nom"]] + ach["adresse"], size=8.5)
    y -= 12 + 11 * len(buyer) + 12
    # Tableau
    cols_kind = ["no", "item", "desc"] + (["hs"] if ci["hs_digits"] else []) + (["orig"] if ci["origin_mode"] == "line" else []) + ["qty", "unit", "pu", "amount"]
    widths = {"no": 22, "item": 62, "desc": 0, "hs": 70, "orig": 38, "qty": 48, "unit": 38, "pu": 64, "amount": 74}
    suffix = st.get("suffix", False)
    if suffix:
        widths["pu"] = 80
        widths["amount"] = 92
    tw = W - 80
    widths["desc"] = tw - sum(widths[k] for k in cols_kind if k != "desc")
    heads = {"no": "#", "item": lab["item"], "desc": lab["desc"], "hs": lab["hs"], "orig": lab["orig"], "qty": lab["qty"],
             "unit": lab["unit"], "pu": lab["pu"] + ("" if suffix else f" {dev}"), "amount": lab["amount"] + ("" if suffix else f" {dev}")}
    al = {"no": "c", "qty": "r", "pu": "r", "amount": "r", "orig": "c"}
    cols = [(heads[k], widths[k], al.get(k, "l")) for k in cols_kind]
    rows = _lines_rows(ci, lang, num, cols_kind, suffix=suffix)
    y = p.table(40, y, cols, rows, size=7.6, grid=st["tgrid"], head_fill=st["head_fill"], wrap_col=cols_kind.index("desc"), bottom=170)
    y -= 10
    # Totaux
    fr = _footer_rows(ci, lang)
    tot_lab = f"{lab['total']} {dev}"
    sfx = f" {dev}" if suffix else ""
    if st["totpos"] == "right":
        for k, v in fr:
            p.text(W - 150, y, k, size=8.5, align="r")
            p.text(W - 42, y, F.money(v, dev, num) + sfx, size=8.5, align="r")
            y -= 12
        p.hline(W - 230, W - 40, y + 8, lw=0.6)
        p.text(W - 150, y - 4, tot_lab, size=10, style="B", align="r")
        p.text(W - 42, y - 4, F.money(ci["total"], dev, num) + sfx, size=10, style="B", align="r")
        y -= 26
    else:
        h = 16 + 12 * (len(fr) + 1)
        p.rect(40, y - h, 240, h, lw=0.8, color=acc)
        yy = y - 13
        for k, v in fr:
            p.text(48, yy, k, size=8.5)
            p.text(272, yy, F.money(v, dev, num) + sfx, size=8.5, align="r")
            yy -= 12
        p.text(48, yy, tot_lab, size=10, style="B")
        p.text(272, yy, F.money(ci["total"], dev, num) + sfx, size=10, style="B", align="r")
        y -= h + 14
    # Informations d'expédition
    info = [f"{lab['terms']}: {ci['incoterm']} {ci['incoterm_lieu']} (Incoterms® 2020)"]
    if ci.get("ref_transport"):
        info.append(f"{_tr_label(ci, lang)}: {ci['ref_transport']}")
    info.append(f"{lab['net']}: {F.mass(ci['net_total'], num)} kg   {lab['gross']}: {F.mass(ci['gross_total'], num)} kg")
    info.append(f"{lab['pkgs']}: {ci['colis']}")
    if ci["origin_mode"] == "header":
        info.append(f"{lab['corig']}: {F.country(ci['lines'][0]['origin'], lang, 'name')}")
    if ci.get("carrier_mention"):
        info.append(f"{lab['via']}: {ci['carrier_mention']}")
    y = p.lines(40, y, info, size=8.5)
    p.text(W - 40, 70, lab["sign"], size=8, align="r", color=HexColor("#555555"))
    p.hline(W - 200, W - 40, 82, lw=0.4)
    if ci.get("hidden_instr"):
        p.hidden_text(40, 40, ci["hidden_instr"])
    return p.save()


def render_cf(ci, rng):
    """Fournisseur chinois : en-tête bilingue, grille complète, montants préfixés, total en lettres."""
    lab = L["en"]
    dev = ci["devise"]
    sup = ci["supplier"]
    num = "en"
    p = Pdf(title=f"Invoice {ci['numero']}", family="DV", lang_mark="en")
    W, H = p.W, p.H
    y = H - 46
    if sup.get("nom_local"):
        p.text(W / 2, y, sup["nom_local"], size=15, align="c", font="CJK")
        y -= 18
    p.text(W / 2, y, sup["nom"].upper(), size=12, style="B", align="c")
    p.text(W / 2, y - 13, ", ".join(sup["adresse"]) + "  " + sup["taxid"], size=7.5, align="c")
    y -= 36
    p.text(W / 2, y, ("PROFORMA INVOICE 形式发票" if ci["sous_type"] == "pro_forma" else "COMMERCIAL INVOICE 商业发票"), size=14, style="B",
           align="c", font="CJK")
    y -= 14
    # grille d'en-tête 2 x 3
    p.rect(36, y - 92, W - 72, 92, lw=0.7)
    p.vline(W / 2, y - 92, y)
    p.hline(36, W - 36, y - 46)
    ach = ci["acheteur"]
    p.text(42, y - 11, "TO (BUYER):", size=7.5, style="B")
    p.lines(42, y - 21, [ach["nom"], ", ".join(ach["adresse"]), f"VAT: {ach['tva']}"], size=7.5, leading=9)
    p.text(W / 2 + 6, y - 11, "INVOICE NO.:", size=7.5, style="B")
    p.text(W / 2 + 70, y - 11, ci["numero"], size=8.5, style="B")
    p.text(W / 2 + 6, y - 23, "DATE:", size=7.5, style="B")
    p.text(W / 2 + 70, y - 23, F.date(ci["date"], "ymd/"), size=8.5)
    p.text(W / 2 + 6, y - 35, "TERMS:", size=7.5, style="B")
    p.text(W / 2 + 70, y - 35, f"{ci['incoterm']} {ci['incoterm_lieu']}", size=8.5)
    p.text(42, y - 57, "FROM / TO:", size=7.5, style="B")
    p.text(42, y - 68, f"{sup['port']}, {F.country(sup['pays'], 'en', 'name')}  ->  FRANCE", size=8)
    tr = ci["transport"]
    p.text(W / 2 + 6, y - 57, {"air": "AWB:", "sea": "B/L:", "road": "CMR:"}[tr["mode"]], size=7.5, style="B")
    p.text(W / 2 + 70, y - 57, ci["ref_transport"] or "", size=8.5)
    p.text(W / 2 + 6, y - 69, "PAYMENT:", size=7.5, style="B")
    p.text(W / 2 + 70, y - 69, ci["payment_terms"], size=8)
    if ci.get("carrier_mention"):
        p.text(W / 2 + 6, y - 81, "FORWARDER:", size=7.5, style="B")
        p.text(W / 2 + 70, y - 81, ci["carrier_mention"], size=8)
    y -= 100
    cols_kind = ["no", "item", "desc"] + (["hs"] if ci["hs_digits"] else []) + (["orig"] if ci["origin_mode"] == "line" else []) + ["qtyu", "pu", "amount"]
    widths = {"no": 20, "item": 64, "desc": 0, "hs": 68, "orig": 34, "qtyu": 70, "pu": 70, "amount": 82}
    widths["desc"] = (W - 72) - sum(widths[k] for k in cols_kind if k != "desc")
    heads = {"no": "NO.", "item": "ITEM NO.", "desc": "DESCRIPTION OF GOODS", "hs": "H.S. CODE", "orig": "C/O",
             "qtyu": "QUANTITY", "pu": f"UNIT PRICE\n({dev})", "amount": f"AMOUNT\n({dev})"}
    al = {"no": "c", "qtyu": "r", "pu": "r", "amount": "r", "orig": "c"}
    cols = [(heads[k], widths[k], al.get(k, "l")) for k in cols_kind]
    rows = _lines_rows(ci, "en", num, cols_kind)
    y = p.table(36, y, cols, rows, size=7.3, grid="full", head_fill=HexColor("#f2f3f4"), wrap_col=cols_kind.index("desc"), bottom=150)
    for k, v in _footer_rows(ci, "en"):
        y -= 12
        p.text(W - 130, y, k.upper() + ":", size=8, align="r")
        p.text(W - 38, y, f"{dev} {F.money(v, dev, num)}", size=8, align="r")
    y -= 16
    p.rect(36, y - 6, W - 72, 18, lw=0.8)
    p.text(42, y, "TOTAL AMOUNT:", size=9, style="B")
    p.text(W - 40, y, f"{dev} {F.money(ci['total'], dev, num)}", size=10, style="B", align="r")
    y -= 22
    ip = int(D(ci["total"]))
    cents = int((D(ci["total"]) - ip) * 100)
    p.para(36, y, W - 72, f"SAY TOTAL {F.CUR_WORDS.get(dev, dev)} {F.words(ip)}" + (f" AND CENTS {F.words(cents)}" if cents else "") + " ONLY.",
           size=7.5, style="B")
    y -= 26
    p.lines(36, y, [f"TOTAL PACKAGES: {ci['colis']} CTNS", f"TOTAL N.W.: {F.mass(ci['net_total'], num)} KGS",
                    f"TOTAL G.W.: {F.mass(ci['gross_total'], num)} KGS"]
            + ([f"COUNTRY OF ORIGIN: {F.country(ci['lines'][0]['origin'], 'en', 'name')}"] if ci["origin_mode"] == "header" else []),
            size=8)
    p.text(W - 60, 90, "盖章 / COMPANY CHOP", size=8, align="r", font="CJK")
    p.stamp(W - 120, 120, sup["nom"].split()[0].upper(), size=11, angle=-8, color=HexColor("#c0392b"), alpha=0.5)
    if ci.get("hidden_instr"):
        p.hidden_text(36, 40, ci["hidden_instr"])
    return p.save()


def render_cg(ci, rng):
    """Totaux en tête (encadré récapitulatif) puis détail des lignes ; mention pro forma."""
    lab = L["en"]
    dev = ci["devise"]
    sup = ci["supplier"]
    num = "en"
    pf = ci["sous_type"] == "pro_forma"
    p = Pdf(title=f"{'Proforma' if pf else 'Invoice'} {ci['numero']}", family="Free", lang_mark="en")
    W, H = p.W, p.H
    acc = HexColor("#2e4053")
    y = H - 48
    p.text(40, y, sup["nom"], size=13, style="B", color=acc)
    p.text(40, y - 13, " | ".join(sup["adresse"]), size=7.5)
    p.text(40, y - 23, sup["taxid"], size=7.5)
    p.text(W - 40, y, "PROFORMA INVOICE" if pf else "INVOICE", size=20, style="B", align="r", color=acc)
    if pf:
        p.text(W - 40, y - 14, "Value declared for customs purposes", size=8, align="r", style="I")
    y -= 44
    # encadré récapitulatif en tête
    p.rect(40, y - 64, W - 80, 64, lw=0, fill=HexColor("#eaf2f8"), stroke=False)
    cells = [("Invoice number", ci["numero"]), ("Issue date", F.date(ci["date"], "us_long")),
             ("Incoterms", f"{ci['incoterm']} {ci['incoterm_lieu']}"), (f"Total due ({dev})", F.money(ci["total"], dev, num))]
    cw = (W - 80) / 4
    for i, (k, v) in enumerate(cells):
        p.text(48 + i * cw, y - 18, k, size=7.5, color=acc)
        p.text(48 + i * cw, y - 38, v, size=11 if i == 3 else 9.5, style="B")
    y -= 84
    ach = ci["acheteur"]
    p.text(40, y, "Customer", size=8, style="B", color=acc)
    p.lines(40, y - 12, [ach["nom"]] + ach["adresse"] + [f"VAT {ach['tva']}"], size=8.5)
    tr = ci["transport"]
    ship = [f"Ref. {ci['transport']['mode'].upper()}: {ci['ref_transport']}", f"Packages: {ci['colis']}",
            f"Net {F.mass(ci['net_total'], num)} kg / Gross {F.mass(ci['gross_total'], num)} kg"]
    if ci.get("carrier_mention"):
        ship.append(f"Carrier: {ci['carrier_mention']}")
    if ci["origin_mode"] == "header":
        ship.append(f"Origin of goods: {F.country(ci['lines'][0]['origin'], 'en', 'name')}")
    p.text(320, y, "Shipment", size=8, style="B", color=acc)
    p.lines(320, y - 12, ship, size=8.5)
    y -= 80
    cols_kind = ["item", "desc"] + (["hs"] if ci["hs_digits"] else []) + (["orig"] if ci["origin_mode"] == "line" else []) + ["qty", "unit", "pu", "amount"]
    widths = {"item": 66, "desc": 0, "hs": 66, "orig": 36, "qty": 46, "unit": 36, "pu": 62, "amount": 72}
    widths["desc"] = (W - 80) - sum(widths[k] for k in cols_kind if k != "desc")
    heads = {"item": "SKU", "desc": "Item", "hs": "Tariff no.", "orig": "COO", "qty": "Qty", "unit": "UoM", "pu": "Price", "amount": "Line total"}
    al = {"qty": "r", "pu": "r", "amount": "r", "orig": "c"}
    cols = [(heads[k], widths[k], al.get(k, "l")) for k in cols_kind]
    y = p.table(40, y, cols, _lines_rows(ci, "en", num, cols_kind), size=7.8, grid="h", head_fill=None, zebra=HexColor("#f4f6f7"),
                wrap_col=cols_kind.index("desc"), bottom=120)
    y -= 6
    for k, v in _footer_rows(ci, "en"):
        y -= 12
        p.text(W - 130, y, k, size=8, align="r")
        p.text(W - 42, y, F.money(v, dev, num), size=8, align="r")
    y -= 15
    p.text(W - 130, y, f"Total {dev}", size=9.5, style="B", align="r")
    p.text(W - 42, y, F.money(ci["total"], dev, num), size=9.5, style="B", align="r")
    p.text(40, 60, "We certify that this invoice is true and correct. Payment: " + ci["payment_terms"], size=7.5, style="I")
    if ci.get("hidden_instr"):
        p.hidden_text(40, 40, ci["hidden_instr"])
    return p.save()


def render_ci_pdf(ci, rng) -> bytes:
    lay = ci["layout"]
    if lay == "CF":
        return render_cf(ci, rng)
    if lay == "CG":
        return render_cg(ci, rng)
    return render_std(ci, rng)


# ---------------------------------------------------------------------------
# Tableur (feuilles « Facture » et « Colisage »)
# ---------------------------------------------------------------------------

def render_ci_xlsx(ci, rng) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    import datetime as _dt

    wb = Workbook()
    ws = wb.active
    ws.title = "Invoice"
    dev = ci["devise"]
    sup = ci["supplier"]
    ach = ci["acheteur"]
    ws["A1"] = FICTIF + " — fictitious test document"
    ws["A1"].font = Font(italic=True, color="888888")
    # Lignes d'abord (en-tête du tableau en ligne 3), métadonnées à droite (colonnes K-L)
    heads = ["Line", "Article", "Description"] + (["Tariff code"] if ci["hs_digits"] else []) + ["Origin", "Quantity", "UoM", f"Unit price {dev}", f"Amount {dev}"]
    for j, h in enumerate(heads, 1):
        ws.cell(row=3, column=j, value=h).font = Font(bold=True)
    r = 4
    for ln in ci["lines"]:
        vals = [ln["no"], ln["ref"], ln["desc"]] + ([F.hs(ln["hs10"], ci["hs_digits"], ci["hs_style"])] if ci["hs_digits"] else []) + \
               [ln["origin"], float(ln["qty"]) if ln["qty"] != ln["qty"].to_integral_value() else int(ln["qty"]), ln["unit_raw"],
                float(ln["pu"]), float(ln["amount"]) if cur_decimals(dev) else int(ln["amount"])]
        for j, v in enumerate(vals, 1):
            c = ws.cell(row=r, column=j, value=v)
            if isinstance(v, float):
                c.number_format = "#,##0.00" if j == len(vals) else "#,##0.00##"
        r += 1
    r += 1
    for k, v in _footer_rows(ci, "en"):
        ws.cell(row=r, column=len(heads) - 1, value=k)
        ws.cell(row=r, column=len(heads), value=float(v)).number_format = "#,##0.00"
        r += 1
    ws.cell(row=r, column=len(heads) - 1, value=f"TOTAL {dev}").font = Font(bold=True)
    c = ws.cell(row=r, column=len(heads), value=float(ci["total"]) if cur_decimals(dev) else int(ci["total"]))
    c.font = Font(bold=True)
    c.number_format = "#,##0.00" if cur_decimals(dev) else "#,##0"
    meta = [("Seller", sup["nom"]), ("Seller address", ", ".join(sup["adresse"])), ("Tax ID", sup["taxid"]),
            ("Invoice number", ci["numero"]), ("Invoice date", ci["date"].isoformat()), ("Currency", dev),
            ("Buyer", ach["nom"]), ("Buyer VAT", ach["tva"]), ("Buyer address", ", ".join(ach["adresse"])),
            ("Incoterm", f"{ci['incoterm']} {ci['incoterm_lieu']}"), ("Transport document", ci["ref_transport"] or ""),
            ("Packages", ci["colis"]), ("Net weight kg", float(ci["net_total"])), ("Gross weight kg", float(ci["gross_total"])),
            ("Payment", ci["payment_terms"])]
    if ci["sous_type"] == "pro_forma":
        meta.insert(0, ("Document", "PROFORMA INVOICE"))
    for i, (k, v) in enumerate(meta):
        ws.cell(row=3 + i, column=len(heads) + 2, value=k).font = Font(bold=True)
        ws.cell(row=3 + i, column=len(heads) + 3, value=v)
    ws2 = wb.create_sheet("Packing")
    ws2["A1"] = FICTIF
    ws2.append(["Line", "Article", "Net kg", "Gross kg"])
    for ln in ci["lines"]:
        ws2.append([ln["no"], ln["ref"], float(ln["net"]), float(ln["gross"])])
    fixed = _dt.datetime(2026, 1, 1, 0, 0, 0)
    wb.properties.created = fixed
    wb.properties.modified = fixed
    wb.properties.creator = "bench.generator2 (FICTIF)"
    wb.properties.lastModifiedBy = "bench.generator2"
    buf = io.BytesIO()
    wb.save(buf)
    return normalize_zip(buf.getvalue())


def normalize_zip(data: bytes) -> bytes:
    """Réécrit un ZIP avec dates fixes et ordre stable (octets identiques d'une exécution à l'autre)."""
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for name in src.namelist():
            zi = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            content = src.read(name)
            if name == "docProps/core.xml":
                # openpyxl impose l'heure courante comme date de modification : on la fige
                content = re.sub(rb"(<dcterms:modified[^>]*>)[^<]*(</dcterms:modified>)",
                                 rb"\g<1>2026-01-01T00:00:00Z\g<2>", content)
            dst.writestr(zi, content)
    return out.getvalue()


# ---------------------------------------------------------------------------
# UBL 2.1 (facture commerciale seule, sans PDF)
# ---------------------------------------------------------------------------

UBL_NS = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"


def _cbc(parent, tag, text=None, **attrs):
    el = etree.SubElement(parent, f"{{{CBC}}}{tag}", **{k: str(v) for k, v in attrs.items()})
    if text is not None:
        el.text = str(text)
    return el


def _cac(parent, tag):
    return etree.SubElement(parent, f"{{{CAC}}}{tag}")


def _party(parent, tag, name, lines, taxid, country):
    pt = _cac(_cac(parent, tag), "Party")
    _cbc(_cac(pt, "PartyName"), "Name", name)
    addr = _cac(pt, "PostalAddress")
    _cbc(addr, "StreetName", lines[0])
    _cbc(addr, "CityName", lines[1] if len(lines) > 1 else "")
    _cbc(_cac(addr, "Country"), "IdentificationCode", country)
    ts = _cac(pt, "PartyTaxScheme")
    _cbc(ts, "CompanyID", taxid)
    _cbc(_cac(ts, "TaxScheme"), "ID", "VAT")
    _cbc(_cac(pt, "PartyLegalEntity"), "RegistrationName", name)


def render_ci_ubl(ci, rng) -> bytes:
    dev = ci["devise"]
    dec = cur_decimals(dev)

    def m(v):
        return str(D(v).quantize(D(1).scaleb(-dec))) if dec else str(int(D(v)))

    root = etree.Element(f"{{{UBL_NS}}}Invoice", nsmap={None: UBL_NS, "cac": CAC, "cbc": CBC})
    _cbc(root, "UBLVersionID", "2.1")
    _cbc(root, "CustomizationID", "urn:fictif:bench:g2:commercial-invoice:1")
    _cbc(root, "ID", ci["numero"])
    _cbc(root, "IssueDate", ci["date"].isoformat())
    _cbc(root, "InvoiceTypeCode", "325" if ci["sous_type"] == "pro_forma" else "380")
    _cbc(root, "Note", FICTIF + " - document de test")
    _cbc(root, "Note", f"Gross weight {ci['gross_total']} KGM; Net weight {ci['net_total']} KGM; Packages {ci['colis']}")
    _cbc(root, "DocumentCurrencyCode", dev)
    adr = _cac(root, "AdditionalDocumentReference")
    _cbc(adr, "ID", ci["ref_transport"] or "")
    _cbc(adr, "DocumentType", {"air": "AWB", "sea": "BL", "road": "CMR"}[ci["transport"]["mode"]])
    sup = ci["supplier"]
    _party(root, "AccountingSupplierParty", sup["nom"], sup["adresse"], sup["taxid"], sup["pays"])
    ach = ci["acheteur"]
    _party(root, "AccountingCustomerParty", ach["nom"], ach["adresse"], ach["tva"], "FR")
    dl = _cac(root, "Delivery")
    _cbc(_cac(_cac(dl, "DeliveryLocation"), "Address"), "CityName", ci["incoterm_lieu"])
    dt = _cac(root, "DeliveryTerms")
    _cbc(dt, "ID", ci["incoterm"])
    _cbc(dt, "SpecialTerms", f"{ci['incoterm']} {ci['incoterm_lieu']} Incoterms 2020")
    for k, reason in (("fret", "Freight"), ("assurance", "Insurance"), ("emballage", "Packing")):
        if k in ci["sub"]:
            ac = _cac(root, "AllowanceCharge")
            _cbc(ac, "ChargeIndicator", "true")
            _cbc(ac, "AllowanceChargeReason", reason)
            _cbc(ac, "Amount", m(ci["sub"][k]), currencyID=dev)
    if "remise" in ci["sub"]:
        ac = _cac(root, "AllowanceCharge")
        _cbc(ac, "ChargeIndicator", "false")
        _cbc(ac, "AllowanceChargeReason", "Discount")
        _cbc(ac, "Amount", m(ci["sub"]["remise"]), currencyID=dev)
    tt = _cac(root, "TaxTotal")
    _cbc(tt, "TaxAmount", m(0), currencyID=dev)
    lmt = _cac(root, "LegalMonetaryTotal")
    _cbc(lmt, "LineExtensionAmount", m(ci["sub"]["marchandises"]), currencyID=dev)
    _cbc(lmt, "TaxExclusiveAmount", m(ci["total"]), currencyID=dev)
    _cbc(lmt, "TaxInclusiveAmount", m(ci["total"]), currencyID=dev)
    if "remise" in ci["sub"]:
        _cbc(lmt, "AllowanceTotalAmount", m(ci["sub"]["remise"]), currencyID=dev)
    ch = sum((ci["sub"].get(k, D(0)) for k in ("fret", "assurance", "emballage")), D(0))
    if ch:
        _cbc(lmt, "ChargeTotalAmount", m(ch), currencyID=dev)
    _cbc(lmt, "PayableAmount", m(ci["total"]), currencyID=dev)
    for ln in ci["lines"]:
        il = _cac(root, "InvoiceLine")
        _cbc(il, "ID", ln["no"])
        _cbc(il, "InvoicedQuantity", str(ln["qty"]), unitCode=ln["unit"])
        _cbc(il, "LineExtensionAmount", m(ln["amount"]), currencyID=dev)
        it = _cac(il, "Item")
        _cbc(it, "Description", ln["desc"])
        _cbc(it, "Name", ln["desc"][:40])
        _cbc(_cac(it, "SellersItemIdentification"), "ID", ln["ref"])
        _cbc(_cac(it, "OriginCountry"), "IdentificationCode", ln["origin"])
        if ci["hs_digits"]:
            _cbc(_cac(it, "CommodityClassification"), "ItemClassificationCode", F.hs(ln["hs10"], ci["hs_digits"], "plain"), listID="HS")
        tc = _cac(it, "ClassifiedTaxCategory")
        _cbc(tc, "ID", "Z")
        _cbc(tc, "Percent", "0")
        _cbc(_cac(tc, "TaxScheme"), "ID", "VAT")
        pr = _cac(il, "Price")
        _cbc(pr, "PriceAmount", str(ln["pu"]), currencyID=dev)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)
