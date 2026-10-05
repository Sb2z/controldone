"""Rendus de l'extension 2.1 (option --ext).

Factures du transitaire
  G13 PT  lignes de prestation exprimées TVA incluse (« c/ IVA »), récapitulatif de TVA par taux
  G14 PL  manutention facturée au kg, débours puis services, totaux sur une page récapitulative séparée
  G15 DE (Suisse)  relevé multi-envois, montants « 1'234.50 », lignes d'avoir (« Gutschrift ») mêlées aux débits
  G16 FR  paysage, regroupement par envoi (MRN) avec sous-totaux, livraison au kg, page récapitulative
Déclarations
  M7  en-tête + récapitulatif en page 1, articles en annexes (récapitulatif des taxes sur deux colonnes)
  M8  « état de liquidation » paysage d'un autre logiciel (une ligne par taxation, points de conduite)
  M9  export XML anglais (schéma inventé urn:fictif:g2:customs-entry:3, taxes hors des articles)
Factures commerciales
  CP  portugais, fret / assurance / emballage / remise en lignes du tableau
  CL  polonais (PLN ou EUR), contre-valeur dans une autre devise
  CM  anglais multipage : en-têtes répétés, totaux de page et reports
"""

from __future__ import annotations

from decimal import Decimal as D

from lxml import etree
from reportlab.lib.colors import HexColor

from . import fmtx as F
from .pdfkit import LIGHT, Pdf
from .render_ci import L as CI_L
from .render_ci import _tr_label
from .render_decl import REF_FR, TAX_EN, TAX_FR, UNIT_SUP, _tax_rows_for, _type_totals, desig, rate_text
from .render_ft import LBL, TITLES, _base, _is_av, _lib, _neg, _sections, _totals, tr_ref
from .util import FICTIF

TITLES.setdefault("pt", {"facture": "FATURA", "avoir": "NOTA DE CRÉDITO", "complementaire": "FATURA COMPLEMENTAR",
                         "debours": "FATURA DE DESPESAS", "prestations": "FATURA DE SERVIÇOS",
                         "complement_prestations": "FATURA — SERVIÇOS ADICIONAIS"})
TITLES.setdefault("pl", {"facture": "FAKTURA VAT", "avoir": "FAKTURA KORYGUJĄCA", "complementaire": "FAKTURA UZUPEŁNIAJĄCA",
                         "debours": "NOTA OBCIĄŻENIOWA (NALEŻNOŚCI)", "prestations": "FAKTURA ZA USŁUGI",
                         "complement_prestations": "FAKTURA — USŁUGI DODATKOWE"})

LBL_X = {
    "pt": {"no": "N.º", "date": "Data", "client": "Cliente", "tva": "NIF/IVA", "mrn": "MRN", "ref_tr": "AWB / B/L / CMR",
           "origin": "Fatura de origem", "motif": "Motivo"},
    "pl": {"no": "Nr", "date": "Data wystawienia", "client": "Nabywca", "tva": "NIP/VAT", "mrn": "MRN", "ref_tr": "AWB / B/L / CMR",
           "origin": "Faktura pierwotna", "motif": "Przyczyna korekty"},
    "de": {**LBL["de"], "client": "Kunde", "tva": "MWST-/USt-Nr."},
    "fr": LBL["fr"],
}


def _title(doc):
    lg = doc["lang"] if doc["lang"] != "fr_en" else "fr"
    return TITLES[lg][doc.get("title_kind", "facture")]


def _refs(doc, lab):
    out = []
    if doc.get("refs_mrn"):
        out.append(f"{lab['mrn']}: " + ", ".join(doc["refs_mrn"]))
    if doc.get("refs_transport"):
        out.append(f"{lab['ref_tr']}: " + ", ".join(tr_ref(r, doc.get("transport_ref_style", "raw")) for r in doc["refs_transport"]))
    if _is_av(doc):
        if doc["refs_facture_origine"]:
            out.append(f"{lab['origin']}: " + ", ".join(doc["refs_facture_origine"]))
        if doc.get("motif"):
            out.append(f"{lab['motif']}: {doc['motif']}")
    return out


def _end(p, doc, x=36, y=36):
    if doc.get("hidden_instr"):
        p.hidden_text(x, y, doc["hidden_instr"])
    return p.save()


# ---------------------------------------------------------------------------
# G13 — Trânsitos Imaginários (PT, lignes TVA incluse)
# ---------------------------------------------------------------------------

def render_g13(doc, rng):
    lab = LBL_X["pt"]
    num = "frs"
    av = _is_av(doc)
    p = Pdf(title=f"{_title(doc)} {doc['numero']}", family="Sans", lang_mark="pt")
    W, H = p.W, p.H
    acc = HexColor("#0e6655")
    em, cl = doc["emetteur"], doc["client"]
    y = H - 46
    p.logo(36, y - 24, "TI", rng, color=acc, size=32)
    p.text(76, y - 2, em["nom"], size=14, style="B", color=acc)
    p.text(76, y - 15, " · ".join(em["adresse"]) + f" · NIF FR {em['tva']}", size=7.2)
    p.rect(W - 210, y - 52, 174, 48, lw=0.8, color=acc)
    ts = 12 if p.width(_title(doc), 12, "B") <= 160 else 160 * 12 / p.width(_title(doc), 12, "B")
    p.text(W - 202, y - 18, _title(doc), size=ts, style="B")
    p.text(W - 202, y - 31, f"{lab['no']} {doc['numero']}", size=9)
    p.text(W - 202, y - 43, f"{lab['date']}: {F.date(doc['date'], 'dmy-')}", size=9)
    y -= 72
    p.text(36, y, lab["client"], size=8, style="B", color=acc)
    p.lines(36, y - 12, [cl["nom"]] + cl["adresse"] + [f"{lab['tva']}: {cl['tva']}"], size=8.5)
    yr = y - 12
    for r in _refs(doc, lab):
        yr = p.para(320, yr, W - 356, r, size=8.0, leading=10)
    y = min(y - 26 - 11 * (len(cl["adresse"]) + 2), yr - 8)
    cols = [("Descrição", 175, "l"), ("MRN", 112, "l"), ("Qtd", 32, "r"), ("Preço unit. c/ IVA", 82, "r"), ("Taxa", 38, "r"),
            ("Total c/ IVA", 84, "r")]
    rows = []
    deb, srv = _sections(doc)
    for ln in deb + srv:
        ttc = ln["ht"] + ln["vat"]
        pu_ttc = ln["pu"] + (ln["pu"] * ln["vat_rate"] / 100).quantize(D("0.01")) if ln["vat_rate"] > 0 else ln["pu"]
        rows.append([_lib(ln, num) + _base(ln, num), ln["mrn"] or "", F.qty(ln["qty"], num), F.amt(pu_ttc, num) + " €",
                     ("isento" if ln["vat_rate"] == 0 else F.amt(ln["vat_rate"], num, 0) + "%"), _neg(ttc, num, "minus", av) + " €"])
    y = p.table(36, y, cols, rows, size=7.8, grid="h", head_fill=HexColor("#d1f2eb"), bottom=150, wrap_col=0)
    y -= 12
    # récapitulatif de TVA (base, imposto) : seule source des montants hors taxe des prestations
    taxable = [ln for ln in doc["lines"] if ln["vat_rate"] > 0]
    exempt = [ln for ln in doc["lines"] if ln["vat_rate"] == 0]
    rows = []
    if taxable:
        rows.append(["Taxa normal 20 % (FR)", F.amt(sum((x["ht"] for x in taxable), D(0)), num), F.amt(doc["total_tva"], num)])
    if exempt:
        rows.append(["Isento — despesas por conta do cliente (art. 267-II-2.º CGI)", F.amt(sum((x["ht"] for x in exempt), D(0)), num), "0,00"])
    p.text(36, y, "Quadro resumo do IVA", size=8.5, style="B", color=acc)
    y = p.table(36, y - 4, [("Taxa / motivo", 260, "l"), ("Base", 90, "r"), ("IVA", 80, "r")], rows, size=7.8, grid="h", head_fill=LIGHT)
    y -= 14
    t = _totals(doc)
    items = []
    if not av:
        items.append(("Total despesas (suplidos)", t["tot_deb"]))
    items += [("Total sem IVA", t["tot_ht"]), ("IVA", t["tva"]), ("Total com IVA", t["ttc"])]
    if not av:
        items.append(("Total a pagar", t["net"]))
    for i, (k, v) in enumerate(items):
        b = "B" if i == len(items) - 1 else ""
        p.text(W - 150, y, k, size=9, style=b, align="r")
        p.text(W - 38, y, _neg(v, num, "minus", av) + " €", size=9, style=b, align="r")
        y -= 13
    p.text(36, 56, "Preços de serviços com IVA incluído. Pagamento por transferência bancária.", size=7.2, style="I")
    return _end(p, doc)


# ---------------------------------------------------------------------------
# G14 — Spedycja Fikcyjna (PL, tarif au kg, page récapitulative)
# ---------------------------------------------------------------------------

def render_g14(doc, rng):
    lab = LBL_X["pl"]
    num = "frs"
    av = _is_av(doc)
    p = Pdf(title=f"{_title(doc)} {doc['numero']}", family="DV", lang_mark="pl")
    W, H = p.W, p.H
    acc = HexColor("#922b21")
    em, cl = doc["emetteur"], doc["client"]

    def header():
        y = H - 42
        p.text(36, y, em["nom"], size=13, style="B", color=acc)
        p.text(W - 36, y, f"{_title(doc)} {lab['no']} {doc['numero']}", size=11, style="B", align="r")
        p.text(W - 36, y - 13, f"{lab['date']}: {F.date(doc['date'], 'dmy.')}  —  str. {p.page_no}", size=8, align="r")
        return y - 30

    y = header()
    p.text(36, y, "Sprzedawca", size=7.5, style="B")
    p.lines(36, y - 11, em["adresse"] + [f"{lab['tva']}: {em['tva']}"], size=8)
    p.text(310, y, lab["client"], size=7.5, style="B")
    p.lines(310, y - 11, [cl["nom"]] + cl["adresse"] + [f"{lab['tva']}: {cl['tva']}"], size=8)
    y -= 22 + 11 * (len(cl["adresse"]) + 2)
    y = p.lines(36, y, _refs(doc, lab), size=8) - 8
    deb, srv = _sections(doc)
    pos = 0
    for title, sec, show_mrn in (("Należności celne i podatkowe (refaktura, poza VAT)", deb, True), ("Usługi", srv, False)):
        if not sec:
            continue
        p.text(36, y, title, size=8.5, style="B", color=acc)
        y -= 4
        cols = [("Lp.", 24, "c"), ("Nazwa", 168 if show_mrn else 278, "l")] + ([("MRN", 110, "l")] if show_mrn else []) + \
               [("Ilość", 50, "r"), ("J.m.", 30, "c"), ("Cena jedn.", 62, "r"), ("Wartość netto", 79, "r")]
        rows = []
        for ln in sec:
            pos += 1
            jm = "kg" if (ln["nature"] in ("manutention", "transport") and ln["qty"] > 1 and ln["pu"] < 1) else (
                "dni" if ln["nature"] == "magasinage" else "szt.")
            rows.append([str(pos), _lib(ln, num) + _base(ln, num)] + ([ln["mrn"] or ""] if show_mrn else []) +
                        [F.qty(ln["qty"], num), jm, F.amt(ln["pu"], num), _neg(ln["ht"], num, "minus", av)])
        y = p.table(36, y, cols, rows, size=7.6, grid="full", head_fill=HexColor("#f9ebea"), bottom=80, wrap_col=1,
                    on_break=lambda pp: (pp.new_page(), header())[1])
        y -= 12
    p.text(36, max(y, 70), "Kwoty w EUR. Podsumowanie na następnej stronie.", size=7.5, style="I")
    # page récapitulative
    p.new_page()
    y = header() - 10
    p.text(W / 2, y, "PODSUMOWANIE / RÉCAPITULATIF", size=13, style="B", align="c", color=acc)
    y -= 30
    t = _totals(doc)
    rows = []
    if not av:
        rows.append(["Razem należności (refaktura)", F.amt(t["tot_deb"], num) + " EUR"])
        rows.append(["Razem usługi netto", F.amt(t["tot_ht"] - t["tot_deb"], num) + " EUR"])
    rows += [["Razem netto", _neg(t["tot_ht"], num, "minus", av) + " EUR"], ["VAT 20 % (Francja)", _neg(t["tva"], num, "minus", av) + " EUR"],
             ["Razem brutto", _neg(t["ttc"], num, "minus", av) + " EUR"]]
    if not av:
        rows.append(["Do zapłaty", F.amt(t["net"], num) + " EUR"])
    y = p.table(120, y, [("Pozycja", 220, "l"), ("Kwota", 140, "r")], rows, size=9.5, grid="full", head_fill=LIGHT)
    p.text(120, y - 20, f"Dokument dotyczy: {', '.join(doc.get('refs_mrn') or [])}", size=8)
    return _end(p, doc)


# ---------------------------------------------------------------------------
# G15 — Zollagentur Phantasie (DE/CH, relevé avec lignes d'avoir)
# ---------------------------------------------------------------------------

def render_g15(doc, rng):
    lab = LBL_X["de"]
    num = "ch"
    av = _is_av(doc)
    p = Pdf(title=f"{_title(doc)} {doc['numero']}", family="Serif", lang_mark="de")
    W, H = p.W, p.H
    acc = HexColor("#7b241c")
    em, cl = doc["emetteur"], doc["client"]
    y = H - 44
    p.rect(36, y - 34, W - 72, 40, lw=0, fill=HexColor("#fdedec"), stroke=False)
    p.text(46, y - 12, em["nom"], size=15, style="B", color=acc)
    p.text(46, y - 26, " | ".join(em["adresse"]) + f" | {em['tva']}", size=7.2)
    y -= 56
    head = ("KONTOAUSZUG / SAMMELRECHNUNG" if doc.get("est_releve") else _title(doc).upper())
    p.text(36, y, head, size=13, style="B")
    p.text(W - 36, y, f"{lab['no']} {doc['numero']}", size=10, style="B", align="r")
    p.text(W - 36, y - 13, f"{lab['date']}: {F.date(doc['date'], 'dmy.')}", size=9, align="r")
    y -= 26
    p.lines(36, y, [cl["nom"]] + cl["adresse"] + [f"{lab['tva']}: {cl['tva']}"], size=8.5)
    y -= 12 * (len(cl["adresse"]) + 2) + 6
    y = p.lines(36, y, _refs(doc, lab), size=8.3) - 6
    cols = [("Sendung / MRN", 130, "l"), ("Leistung", 235, "l"), ("Menge", 45, "r"), ("Soll / Haben", 113, "r")]
    order = []
    mrns = list(dict.fromkeys([ln["mrn"] for ln in doc["lines"] if ln["mrn"]]))
    for m in mrns:
        order += [ln for ln in doc["lines"] if ln["mrn"] == m]
    order += [ln for ln in doc["lines"] if not ln["mrn"]]
    rows = []
    for ln in order:
        v = ln["ht"]
        s = _neg(v, num, "minus", av) if v >= 0 else "-" + F.amt(-v, num)
        rows.append([ln["mrn"] or "—", _lib(ln, num) + _base(ln, num), F.qty(ln["qty"], num), s + " EUR"])
    y = p.table(36, y, cols, rows, size=7.8, grid="h", head_fill=HexColor("#f2d7d5"), bottom=150, wrap_col=1)
    y -= 12
    t = _totals(doc)
    items = []
    if not av:
        items.append(("Total Auslagen (Zoll/EUSt, MWST-frei)", t["tot_deb"]))
    items += [("Total netto", t["tot_ht"]), ("MWST Frankreich 20 %", t["tva"]), ("Total EUR", t["ttc"])]
    for i, (k, v) in enumerate(items):
        b = "B" if i == len(items) - 1 else ""
        p.text(W - 150, y, k, size=9, style=b, align="r")
        p.text(W - 38, y, _neg(v, num, "minus", av) + " EUR", size=9, style=b, align="r")
        y -= 13
    p.text(36, 60, "Gutschriften sind im Kontoauszug verrechnet. Zahlbar innert 30 Tagen netto.", size=7.5, style="I")
    return _end(p, doc)


# ---------------------------------------------------------------------------
# G16 — Hypothèse Transports & Douane (FR, paysage, regroupement par envoi)
# ---------------------------------------------------------------------------

def render_g16(doc, rng):
    lab = LBL["fr"]
    num = "frs"
    av = _is_av(doc)
    p = Pdf(land=True, title=f"{_title(doc)} {doc['numero']}", family="Free", lang_mark="fr")
    W, H = p.W, p.H
    acc = HexColor("#1b4f72")
    em, cl = doc["emetteur"], doc["client"]

    def header():
        y = H - 40
        p.text(36, y, em["nom"], size=14, style="B", color=acc)
        p.text(36, y - 13, " — ".join(em["adresse"]) + f" — TVA {em['tva']}", size=7.2)
        p.text(W - 36, y, f"{_title(doc)} {doc['numero']}", size=13, style="B", align="r")
        p.text(W - 36, y - 13, f"Émise le {F.date(doc['date'], 'fr_long')} — page {p.page_no}", size=8, align="r")
        return y - 30

    y = header()
    p.lines(W - 330, y, [cl["nom"]] + cl["adresse"] + [f"N° TVA : {cl['tva']}"], size=8.5)
    p.lines(36, y, _refs(doc, lab), size=8.5)
    y -= 12 * (len(cl["adresse"]) + 2) + 10
    cols = [("Désignation", 300, "l"), ("Qté", 50, "r"), ("Unité", 40, "c"), ("P.U. HT", 70, "r"), ("Montant HT", 90, "r"),
            ("TVA %", 50, "r"), ("TVA", 70, "r"), ("TTC", 99, "r")]
    groups = []
    mrns = list(dict.fromkeys([ln["mrn"] for ln in doc["lines"] if ln["mrn"]]))
    for m in mrns:
        groups.append((f"Envoi — MRN {m}", [ln for ln in doc["lines"] if ln["mrn"] == m]))
    rest = [ln for ln in doc["lines"] if not ln["mrn"]]
    if rest:
        groups.append(("Prestations communes au dossier", rest))
    for title, lns in groups:
        if y < 120:
            p.new_page()
            y = header()
        p.text(36, y, title, size=9, style="B", color=acc)
        y -= 4
        rows = []
        for ln in lns:
            unit = "kg" if (ln["nature"] in ("transport", "manutention") and ln["pu"] < 1 and ln["qty"] > 1) else (
                "jour" if ln["nature"] == "magasinage" else "u.")
            rows.append([_lib(ln, num) + _base(ln, num), F.qty(ln["qty"], num), unit, F.amt(ln["pu"], num, 2 if ln["pu"] >= 1 else 2),
                         _neg(ln["ht"], num, "minus", av), F.amt(ln["vat_rate"], num), F.amt(ln["vat"], num),
                         _neg(ln["ht"] + ln["vat"], num, "minus", av)])
        sub = sum((x["ht"] for x in lns), D(0))
        rows.append(["Sous-total de l'envoi", None, None, None, _neg(sub, num, "minus", av), None, None, None])
        y = p.table(36, y, cols, rows, size=7.8, grid="h", head_fill=HexColor("#d6eaf8"), bottom=70,
                    on_break=lambda pp: (pp.new_page(), header())[1])
        y -= 12
    p.new_page()
    y = header() - 10
    p.text(W / 2, y, "RÉCAPITULATIF DE LA FACTURE", size=13, style="B", align="c", color=acc)
    y -= 30
    t = _totals(doc)
    rows = []
    if not av:
        rows.append(["Total débours (hors champ de TVA)", F.amt(t["tot_deb"], num) + " €"])
    rows += [["Total HT", _neg(t["tot_ht"], num, "minus", av) + " €"], ["TVA 20 %", _neg(t["tva"], num, "minus", av) + " €"],
             ["Total TTC", _neg(t["ttc"], num, "minus", av) + " €"]]
    if not av:
        rows.append(["Net à payer", F.amt(t["net"], num) + " €"])
    p.table(W / 2 - 180, y, [("Rubrique", 240, "l"), ("Montant", 120, "r")], rows, size=10, grid="full", head_fill=LIGHT)
    return _end(p, doc)


FT_RENDERERS = {"G13": render_g13, "G14": render_g14, "G15": render_g15, "G16": render_g16}


def render_ft_ext(doc, rng) -> bytes:
    return FT_RENDERERS[doc["family"]](doc, rng)


# ---------------------------------------------------------------------------
# M7 — en-tête + annexes
# ---------------------------------------------------------------------------

def _dec_boxes(dec, num):
    rep = dec.get("fiscal_rep")
    out = [("Importateur", [dec["importateur"]["nom"], f"TVA {dec['importateur']['tva']} — EORI {dec['importateur']['eori']}"]
            + ([f"Représentant fiscal : {rep['nom']} — TVA {rep['tva']}"] if rep else [])),
           ("Déclarant", [dec["declarant"]["nom"], f"TVA {dec['declarant']['tva']}"]),
           ("Livraison / expédition", [f"{dec['incoterm']} {dec['incoterm_lieu']}", f"Pays d'expédition {dec['pays_exp']}"]),
           ("Facturation", [f"{F.money(dec['montant'], dec['devise'], num)} {dec['devise']}"] + ([rate_text(dec, "fr", num)] if dec["rate"] else [])),
           ("Masse brute / colis / articles", [f"{F.mass(dec['gross_total'], num)} kg — {dec['colis_total']} colis — {dec['n_articles']} article(s)"])]
    return out


def render_m7(dec, rng):
    num = "frs"
    p = Pdf(title=f"Declaration {dec['mrn']}", family="DVM", lang_mark="fr", mark_pos="top")
    W, H = p.W, p.H
    acc = HexColor("#145a32")
    arts = dec["articles"]
    per = 3
    n_ann = max(1, (len(arts) + per - 1) // per)
    y = H - 40
    p.text(36, y, "DOUANESOFT (FICTIF) — DÉCLARATION " + ("H7" if dec["h7"] else "H1") + " — FEUILLET D'EN-TÊTE", size=10, style="B", color=acc)
    p.text(W - 36, y, f"1/{n_ann + 1}", size=8, align="r")
    y -= 18
    p.text(36, y, f"MRN {dec['mrn']}    LRN {dec['lrn']}    rang {dec['version']}    acceptée le {F.date(dec['date'], 'dmy/')}", size=8.5)
    y -= 16
    for t, ls in _dec_boxes(dec, num):
        p.rect(36, y - 12 * len(ls) - 8, W - 72, 12 * len(ls) + 8, lw=0.4)
        p.text(40, y - 9, t, size=7, style="B", color=acc)
        p.lines(170, y - 9, ls, size=7.8, leading=12)
        y -= 12 * len(ls) + 10
    y -= 6
    p.text(36, y, "Documents", size=8.5, style="B")
    y = p.table(36, y - 4, [("Code", 50, "l"), ("Nature", 210, "l"), ("Référence", 263, "l")],
                [[r["code"], REF_FR.get(r["code"], ""), r["ref"]] for r in dec["refs"]], size=7.6, grid="h", head_fill=LIGHT) - 10
    lvl = [t for t in dec["taxes"] if t["article"] is None]
    if lvl:
        p.text(36, y, "Impositions globales", size=8.5, style="B")
        rows = []
        for t in lvl:
            base = F.amt(t["base"], num) if t["base"] is not None else f"{F.qty(t['base_qty'], num)} art."
            taux = (F.amt(t["rate"], num) + " EUR/art.") if t["nature"] == "specifique" else F.rate(t["rate"], num) + " %"
            rows.append([t["type"], base, taux, F.amt(t["montant"], num), F.amt(t["a_payer"], num), t["mode"]])
        y = p.table(36, y - 4, [("Type", 50, "l"), ("Base", 120, "r"), ("Taux", 110, "r"), ("Montant", 90, "r"), ("À payer", 90, "r"),
                                ("MP", 63, "c")], rows, size=7.6, grid="h", head_fill=LIGHT) - 10
    p.text(36, y, "Récapitulatif de la liquidation", size=8.5, style="B")
    rows = [[k, TAX_FR.get(k, k), F.amt(v, num)] for k, v in _type_totals(dec).items()]
    rows += [["", "TOTAL DROITS ET TAXES", F.amt(dec["total_droits_taxes"], num)], ["", "TOTAL À PAYER / À GARANTIR", F.amt(dec["total_a_payer"], num)]]
    y = p.table(36, y - 4, [("Type", 60, "l"), ("Libellé", 300, "l"), ("Montant EUR", 163, "r")], rows, size=7.8, grid="full", head_fill=LIGHT)
    p.text(36, y - 16, f"Détail des {len(arts)} article(s) : voir annexes A1 à A{n_ann}.", size=8, style="I")
    for k in range(n_ann):
        p.new_page()
        y = H - 40
        p.text(36, y, f"ANNEXE A{k + 1} — MRN {dec['mrn']}", size=10, style="B", color=acc)
        p.text(W - 36, y, f"{k + 2}/{n_ann + 1}", size=8, align="r")
        y -= 22
        for a in arts[k * per:(k + 1) * per]:
            p.rect(36, y - 13, W - 72, 13, lw=0, fill=LIGHT, stroke=False)
            p.text(40, y - 9, f"Article {a['no']} — {a['hs10']} — origine {a['origin']} — préf. {a['pref']} — régime {a['regime']}/{a['regime_c']}", size=7.8, style="B")
            y -= 24
            y = p.para(40, y, W - 80, desig(dec, a), size=7.6) - 1
            info = [f"Montant facturé {F.money(a['amount'], dec['devise'], num)} {dec['devise']} — valeur statistique {F.amt(a['stat_value'], num)} EUR",
                    f"Masse nette {F.mass(a['net'], num)} kg — masse brute {F.mass(a['gross'], num)} kg — colis {a['colis']}"
                    + (f" — quantité {F.qty(a['qty'], num)} {UNIT_SUP.get(a['qty_unit'], a['qty_unit'])}" if a["qty"] is not None else "")]
            y = p.lines(40, y, info, size=7.4, leading=10) - 2
            taxes = _tax_rows_for(dec, a["no"])
            left = [t for t in taxes if t["cat"] != "tva"]
            right = [t for t in taxes if t["cat"] == "tva"]
            cols = [("Taxe", 34, "l"), ("Base", 64, "r"), ("Taux", 40, "r"), ("Montant", 58, "r"), ("MP", 22, "c")]
            yl = yr = y
            if left:
                p.text(40, y, "Droits et autres taxes", size=7, style="I")
                yl = p.table(40, y - 3, cols, [[t["type"], F.amt(t["base"], num), F.rate(t["rate"], num) + "%", F.amt(t["montant"], num), t["mode"]]
                                                for t in left], size=7.2, grid="h", head_fill=None, bottom=40)
            if right:
                p.text(300, y, "TVA à l'importation", size=7, style="I")
                yr = p.table(300, y - 3, cols, [[t["type"], F.amt(t["base"], num), F.rate(t["rate"], num) + "%", F.amt(t["montant"], num), t["mode"]]
                                                 for t in right], size=7.2, grid="h", head_fill=None, bottom=40)
            y = min(yl, yr) - 14
    return _end(p, dec, 36, 30)


# ---------------------------------------------------------------------------
# M8 — état de liquidation paysage
# ---------------------------------------------------------------------------

def _leader(p, x, y, k, v, w, size=8):
    p.text(x, y, k, size=size)
    kw = p.width(k, size)
    vw = p.width(v, size)
    dots = "." * max(2, int((w - kw - vw - 6) / max(1, p.width(".", size))))
    p.text(x + kw + 2, y, dots, size=size, color=HexColor("#888888"))
    p.text(x + w, y, v, size=size, align="r")


def render_m8(dec, rng):
    num = "frs"
    p = Pdf(land=True, title=f"Etat de liquidation {dec['mrn']}", family="FSerif", lang_mark="fr")
    W, H = p.W, p.H
    y = H - 38
    p.text(W / 2, y, "ÉTAT DE LIQUIDATION DES DROITS ET TAXES — LOGICIEL TRANSITLOG (FICTIF)", size=11, style="B", align="c")
    y -= 20
    left = [("N° MRN", dec["mrn"]), ("LRN / rang", f"{dec['lrn']} / {dec['version']}"), ("Date d'acceptation", F.date(dec["date"], "dmy/")),
            ("Importateur", dec["importateur"]["nom"]), ("TVA importateur", dec["importateur"]["tva"]), ("EORI", dec["importateur"]["eori"])]
    if dec.get("fiscal_rep"):
        left.append(("Représentant fiscal", f"{dec['fiscal_rep']['nom']} — {dec['fiscal_rep']['tva']}"))
    right = [("Déclarant", dec["declarant"]["nom"]), ("TVA déclarant", dec["declarant"]["tva"]),
             ("Incoterm", f"{dec['incoterm']} {dec['incoterm_lieu']}"), ("Pays d'expédition", dec["pays_exp"]),
             ("Montant facturé", f"{F.money(dec['montant'], dec['devise'], num)} {dec['devise']}")]
    if dec["rate"]:
        right.append(("Taux de change", rate_text(dec, "fr", num)))
    right += [("Masse brute totale", f"{F.mass(dec['gross_total'], num)} kg"), ("Colis / articles", f"{dec['colis_total']} / {dec['n_articles']}")]
    yy = y
    for k, v in left:
        _leader(p, 36, yy, k, v, 360)
        yy -= 12
    yr = y
    for k, v in right:
        _leader(p, 430, yr, k, v, 370)
        yr -= 12
    y = min(yy, yr) - 6
    p.text(36, y, "Documents : " + " ; ".join(f"{r['code']} {r['ref']}" for r in dec["refs"]), size=7.8)
    y -= 10
    cols = [("Art.", 26, "c"), ("Code NC", 64, "l"), ("Or.", 24, "c"), ("Désignation", 160, "l"), ("Mt facturé", 66, "r"),
            ("Net kg", 52, "r"), ("Brut kg", 52, "r"), ("Colis", 30, "r"), ("Taxe", 34, "c"), ("Base", 64, "r"), ("Taux", 50, "r"),
            ("Montant", 60, "r"), ("À payer", 56, "r"), ("MP", 31, "c")]
    rows = []
    for a in dec["articles"]:
        taxes = _tax_rows_for(dec, a["no"])
        info = [str(a["no"]), a["hs10"], a["origin"], desig(dec, a), F.money(a["amount"], dec["devise"], num), F.mass(a["net"], num),
                F.mass(a["gross"], num), str(a["colis"])]
        if not taxes:
            rows.append(info + [None] * 6)
        for j, t in enumerate(taxes):
            rows.append((info if j == 0 else [None] * 8) + [t["type"], F.amt(t["base"], num), F.rate(t["rate"], num) + " %",
                                                           F.amt(t["montant"], num), F.amt(t["a_payer"], num), t["mode"]])
    for t in [t for t in dec["taxes"] if t["article"] is None]:
        base = F.amt(t["base"], num) if t["base"] is not None else f"{F.qty(t['base_qty'], num)} art."
        taux = (F.amt(t["rate"], num) + " €/art") if t["nature"] == "specifique" else F.rate(t["rate"], num) + " %"
        rows.append(["—", None, None, "Imposition globale", None, None, None, None, t["type"], base, taux, F.amt(t["montant"], num),
                     F.amt(t["a_payer"], num), t["mode"]])
    y = p.table(36, y, cols, rows, size=7, grid="full", head_fill=HexColor("#eaeded"), bottom=90, wrap_col=3)
    y -= 12
    tt = "   ".join(f"Total {k} : {F.amt(v, num)}" for k, v in _type_totals(dec).items())
    p.text(36, y, tt, size=8)
    p.text(W - 36, y, f"TOTAL DROITS ET TAXES {F.amt(dec['total_droits_taxes'], num)} EUR — TOTAL À PAYER {F.amt(dec['total_a_payer'], num)} EUR",
           size=8.5, style="B", align="r")
    p.text(36, y - 12, "MP : A comptant — E crédit d'enlèvement — G TVA autoliquidée", size=7, style="I")
    return _end(p, dec, 36, 28)


# ---------------------------------------------------------------------------
# M9 — export XML anglais
# ---------------------------------------------------------------------------

NS9 = "urn:fictif:g2:customs-entry:3"


def render_m9(dec, rng) -> bytes:
    def e(parent, tag, text=None, **attrs):
        el = etree.SubElement(parent, f"{{{NS9}}}{tag}", **{k: str(v) for k, v in attrs.items() if v is not None})
        if text is not None:
            el.text = str(text)
        return el

    root = etree.Element(f"{{{NS9}}}CustomsEntry", nsmap={None: NS9}, schemaVersion="3.0")
    e(root, "Notice", FICTIF + " — test export, fictitious data")
    h = e(root, "Header")
    e(h, "MRN", dec["mrn"])
    e(h, "LRN", dec["lrn"])
    e(h, "Version", dec["version"])
    e(h, "DataSet", "H7" if dec["h7"] else "H1")
    e(h, "AcceptanceDate", dec["date"].isoformat())
    im = e(h, "Importer")
    e(im, "Name", dec["importateur"]["nom"])
    e(im, "VATNumber", dec["importateur"]["tva"])
    e(im, "EORI", dec["importateur"]["eori"])
    de = e(h, "Declarant", representation="DIRECT")
    e(de, "Name", dec["declarant"]["nom"])
    e(de, "VATNumber", dec["declarant"]["tva"])
    if dec.get("fiscal_rep"):
        fr = e(h, "FiscalRepresentative")
        e(fr, "Name", dec["fiscal_rep"]["nom"])
        e(fr, "VATNumber", dec["fiscal_rep"]["tva"])
    e(h, "DeliveryTerms", code=dec["incoterm"], place=dec["incoterm_lieu"])
    e(h, "DispatchCountry", dec["pays_exp"])
    e(h, "InvoiceCurrency", dec["devise"])
    e(h, "InvoiceTotal", dec["montant"])
    if dec["rate"] is not None:
        e(h, "ExchangeRate", dec["rate"], currency=dec["devise_taux"],
          basis="CURRENCY_PER_EUR" if dec["sens"] == "devise_par_eur" else "EUR_PER_CURRENCY")
    e(h, "GrossMass", dec["gross_total"], unit="KGM")
    e(h, "Packages", dec["colis_total"])
    e(h, "ItemCount", dec["n_articles"])
    sd = e(root, "SupportingDocuments")
    for r in dec["refs"]:
        e(sd, "Document", r["ref"], type=r["code"])
    its = e(root, "Items")
    for a in dec["articles"]:
        it = e(its, "Item", seq=a["no"])
        e(it, "CommodityCode", a["hs10"])
        e(it, "Description", desig(dec, a))
        e(it, "Origin", a["origin"])
        e(it, "Preference", a["pref"])
        e(it, "Procedure", f"{a['regime']}/{a['regime_c']}")
        e(it, "InvoicedAmount", a["amount"], currency=dec["devise"])
        e(it, "StatisticalValue", a["stat_value"], currency="EUR")
        e(it, "NetMass", a["net"], unit="KGM")
        e(it, "GrossMass", a["gross"], unit="KGM")
        if a["qty"] is not None:
            e(it, "SupplementaryUnits", a["qty"], unit=UNIT_SUP.get(a["qty_unit"], a["qty_unit"]))
        e(it, "Packages", a["colis"])
    du = e(root, "Duties")
    for t in dec["taxes"]:
        d = e(du, "Duty", item=t["article"] if t["article"] is not None else "", type=t["type"],
              method="AD_VALOREM" if t["nature"] == "ad_valorem" else "SPECIFIC", label=TAX_EN.get(t["type"]))
        if t["base"] is not None:
            e(d, "Base", t["base"], currency="EUR")
        if t["base_qty"] is not None:
            e(d, "BaseQuantity", t["base_qty"], unit=t["base_unit"] or "item")
        e(d, "Rate", t["rate"])
        e(d, "Amount", t["montant"])
        e(d, "Payable", t["a_payer"])
        e(d, "Payment", t["mode"])
    sm = e(root, "Summary")
    for k, v in _type_totals(dec).items():
        e(sm, "TypeTotal", v, type=k)
    e(sm, "TotalDutiesAndTaxes", dec["total_droits_taxes"])
    e(sm, "TotalPayable", dec["total_a_payer"])
    if dec.get("hidden_instr"):
        e(root, "Remark", dec["hidden_instr"])
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)


def render_decl_ext(dec, rng) -> bytes:
    return {"M7": render_m7, "M8": render_m8, "M9": render_m9}[dec["layout"]](dec, rng)


# ---------------------------------------------------------------------------
# Factures commerciales CP, CL, CM
# ---------------------------------------------------------------------------

CI_LX = {
    "pt": {"inv": "FATURA COMERCIAL", "pf": "FATURA PRÓ-FORMA", "no": "Fatura n.º", "date": "Data", "seller": "Vendedor / Exportador",
           "buyer": "Faturar a", "consignee": "Entregar a", "item": "Ref.", "desc": "Descrição", "hs": "Código pautal",
           "orig": "Origem", "qty": "Qtd.", "unit": "Un.", "pu": "Preço unit.", "amount": "Valor", "goods": "Total mercadorias",
           "fret": "Frete", "assurance": "Seguro", "emballage": "Embalagem", "remise": "Desconto", "total": "TOTAL",
           "terms": "Condições de entrega", "awb": "Carta de porte aéreo", "bl": "Conhecimento de embarque", "cmr": "CMR",
           "net": "Peso líquido", "gross": "Peso bruto", "pkgs": "Volumes", "pay": "Pagamento", "vat": "NIF / N.º IVA",
           "via": "Transitário", "corig": "País de origem", "sign": "Assinatura", "equiv": "Contravalor indicativo",
           "equiv_note": "apenas para informação, moeda da fatura"},
    "pl": {"inv": "FAKTURA EKSPORTOWA", "pf": "FAKTURA PRO FORMA", "no": "Faktura nr", "date": "Data wystawienia",
           "seller": "Sprzedawca / Eksporter", "buyer": "Nabywca", "consignee": "Odbiorca", "item": "Indeks", "desc": "Nazwa towaru",
           "hs": "Kod CN", "orig": "Pochodzenie", "qty": "Ilość", "unit": "J.m.", "pu": "Cena jedn.", "amount": "Wartość",
           "goods": "Wartość towarów", "fret": "Fracht", "assurance": "Ubezpieczenie", "emballage": "Opakowanie", "remise": "Rabat",
           "total": "RAZEM DO ZAPŁATY", "terms": "Warunki dostawy", "awb": "Lotniczy list przewozowy", "bl": "Konosament",
           "cmr": "List przewozowy CMR", "net": "Masa netto", "gross": "Masa brutto", "pkgs": "Liczba opakowań", "pay": "Płatność",
           "vat": "NIP / VAT", "via": "Spedytor", "corig": "Kraj pochodzenia", "sign": "Podpis", "equiv": "Równowartość informacyjna",
           "equiv_note": "wyłącznie informacyjnie, waluta faktury"},
}


def _ci_lab(ci):
    if ci["lang"] in CI_LX:
        return CI_LX[ci["lang"]]
    return {**CI_L["en"], "equiv": "Indicative equivalent", "equiv_note": "informative only, invoice currency"}


def _ci_parties(p, ci, lab, y, num, acc):
    sup = ci["supplier"]
    ach = ci["acheteur"]
    buyer = [ach.get("nom_affiche", ach["nom"])] + ach["adresse"] + [f"{lab['vat']}: {ach.get('tva_affichee', ach['tva'])}"] + \
            ([f"EORI: {ci['eori']}"] if ci.get("eori") else [])
    dst = ci.get("destinataire") or {"nom": ach["nom"], "adresse": ach["adresse"]}
    p.text(40, y, lab["buyer"], size=7.8, style="B", color=acc)
    p.lines(40, y - 11, buyer, size=8.2)
    p.text(310, y, lab["consignee"], size=7.8, style="B", color=acc)
    p.lines(310, y - 11, [dst["nom"]] + dst["adresse"], size=8.2)
    return y - 11 - 10.5 * len(buyer) - 10


def _ci_info(ci, lab, num):
    dev = ci["devise"]
    info = [f"{lab['terms']}: {ci['incoterm']} {ci['incoterm_lieu']} (Incoterms® 2020)"]
    if ci.get("ref_transport"):
        lab_tr = {"air": lab["awb"], "sea": lab["bl"], "road": lab["cmr"]}[ci["transport"]["mode"]]
        info.append(f"{lab_tr}: {ci['ref_transport']}")
    info.append(f"{lab['net']}: {F.mass(ci['net_total'], num)} kg   {lab['gross']}: {F.mass(ci['gross_total'], num)} kg   {lab['pkgs']}: {ci['colis']}")
    if ci["origin_mode"] == "header":
        info.append(f"{lab['corig']}: {ci['lines'][0]['origin']}")
    if ci.get("carrier_mention"):
        info.append(f"{lab['via']}: {ci['carrier_mention']}")
    if ci.get("equiv"):
        q = ci["equiv"]
        info.append(f"{lab['equiv']}: {F.amt(q['montant'], num)} {q['devise']} (1 EUR = {F.amt(q['taux'], num, 4)} "
                    f"{dev if dev != 'EUR' else q['devise']}) — {lab['equiv_note']} {dev}")
    return info


def _ci_rows(ci, num, with_hs=True):
    dev = ci["devise"]
    rows = []
    for ln in ci["lines"]:
        rows.append([str(ln["no"]), ln["ref"], ln["desc"]] + ([F.hs(ln["hs10"], ci["hs_digits"], ci["hs_style"])] if (with_hs and ci["hs_digits"]) else [])
                    + ([ln["origin"]] if ci["origin_mode"] == "line" else []) + [F.qty(ln["qty"], num), ln["unit_raw"],
                    F.pu(ln["pu"], dev, num), F.money(ln["amount"], dev, num)])
    return rows


def _ci_cols(ci, lab, W, desc_min=120):
    dev = ci["devise"]
    ks = [("#", 22, "c"), (lab["item"], 84 if ci["layout"] == "CM" else 66, "l"), (lab["desc"], 0, "l")] + ([(lab["hs"], 70, "l")] if ci["hs_digits"] else []) + \
         ([(lab["orig"], 40, "c")] if ci["origin_mode"] == "line" else []) + [(lab["qty"], 46, "r"), (lab["unit"], 36, "l"),
                                                                              (f"{lab['pu']} {dev}", 66, "r"), (f"{lab['amount']} {dev}", 78, "r")]
    tw = W - 80
    rest = tw - sum(w for _, w, _ in ks)
    return [(t, (rest if w == 0 else w), a) for t, w, a in ks]


def render_cp(ci, rng):
    lab = _ci_lab(ci)
    num = "frs"
    dev = ci["devise"]
    sup = ci["supplier"]
    p = Pdf(title=f"{lab['inv']} {ci['numero']}", family="Sans", lang_mark=ci["lang"] if ci["lang"] in ("pt", "pl") else "en")
    W, H = p.W, p.H
    acc = HexColor("#a04000")
    y = H - 48
    p.text(40, y, sup["nom"], size=13, style="B", color=acc)
    p.lines(40, y - 13, sup["adresse"] + [sup["taxid"]], size=8)
    p.text(W - 40, y, lab["pf"] if ci["sous_type"] == "pro_forma" else lab["inv"], size=15, style="B", align="r")
    p.text(W - 40, y - 15, f"{lab['no']} {ci['numero']}", size=9.5, align="r")
    p.text(W - 40, y - 27, f"{lab['date']}: {F.date(ci['date'], 'dmy-')}", size=9, align="r")
    p.text(W - 40, y - 39, f"{lab['pay']}: {ci['payment_terms']}", size=8, align="r")
    y -= 80
    y = _ci_parties(p, ci, lab, y, num, acc)
    cols = _ci_cols(ci, lab, W)
    rows = _ci_rows(ci, num)
    # frais de pied intégrés au tableau (lignes sans quantité)
    n = len(cols)
    sub = ci["sub"]
    if len(sub) > 1:
        rows.append([None, None, lab["goods"]] + [None] * (n - 4) + [F.money(sub["marchandises"], dev, num)])
        for k in ("fret", "assurance", "emballage"):
            if k in sub:
                rows.append([None, None, lab[k]] + [None] * (n - 4) + [F.money(sub[k], dev, num)])
        if "remise" in sub:
            rows.append([None, None, lab["remise"]] + [None] * (n - 4) + ["-" + F.money(sub["remise"], dev, num)])
    rows.append([None, None, f"{lab['total']} {dev}"] + [None] * (n - 4) + [F.money(ci["total"], dev, num)])
    y = p.table(40, y, cols, rows, size=7.5, grid="full", head_fill=HexColor("#fae5d3"), wrap_col=2, bottom=130)
    y -= 12
    y = p.lines(40, y, _ci_info(ci, lab, num), size=8.2)
    p.text(W - 40, 70, lab["sign"], size=8, align="r")
    return _end(p, ci, 40, 40)


def render_cl(ci, rng):
    lab = _ci_lab(ci)
    num = "frs"
    dev = ci["devise"]
    sup = ci["supplier"]
    p = Pdf(title=f"{lab['inv']} {ci['numero']}", family="DV", lang_mark=ci["lang"] if ci["lang"] in ("pt", "pl") else "en")
    W, H = p.W, p.H
    acc = HexColor("#6c3483")
    y = H - 46
    p.rect(40, y - 36, W - 80, 42, lw=1.0, color=acc)
    p.text(48, y - 12, (lab["pf"] if ci["sous_type"] == "pro_forma" else lab["inv"]) + f"  {lab['no']} {ci['numero']}", size=12, style="B")
    p.text(48, y - 28, f"{lab['date']}: {F.date(ci['date'], 'dmy.')}", size=9)
    y -= 54
    p.text(40, y, lab["seller"], size=7.8, style="B", color=acc)
    p.lines(40, y - 11, [sup["nom"]] + sup["adresse"] + [sup["taxid"]], size=8.2)
    y -= 70
    y = _ci_parties(p, ci, lab, y, num, acc)
    y = p.table(40, y, _ci_cols(ci, lab, W), _ci_rows(ci, num), size=7.5, grid="h", head_fill=HexColor("#ebdef0"), wrap_col=2, bottom=150)
    y -= 10
    sub = ci["sub"]
    items = []
    if len(sub) > 1:
        items.append((lab["goods"], sub["marchandises"]))
        for k in ("fret", "assurance", "emballage"):
            if k in sub:
                items.append((lab[k], sub[k]))
        if "remise" in sub:
            items.append((lab["remise"], -sub["remise"]))
    for k, v in items:
        p.text(W - 160, y, k, size=8.5, align="r")
        p.text(W - 42, y, F.money(v, dev, num) + f" {dev}", size=8.5, align="r")
        y -= 12
    p.text(W - 160, y - 2, lab["total"], size=10, style="B", align="r")
    p.text(W - 42, y - 2, F.money(ci["total"], dev, num) + f" {dev}", size=10, style="B", align="r")
    y -= 24
    y = p.lines(40, y, _ci_info(ci, lab, num), size=8.2)
    return _end(p, ci, 40, 40)


def render_cm(ci, rng):
    """Multipage : en-tête de colonnes répété, total de page et report à chaque saut de page."""
    lab = _ci_lab(ci)
    num = "en" if ci["lang"] not in ("pt", "pl") else "frs"
    dev = ci["devise"]
    sup = ci["supplier"]
    p = Pdf(title=f"{lab['inv']} {ci['numero']}", family="Sans", lang_mark=ci["lang"] if ci["lang"] in ("pt", "pl") else "en")
    W, H = p.W, p.H
    acc = HexColor("#1a5276")
    cols = _ci_cols(ci, lab, W)
    rows = _ci_rows(ci, num)
    first_rows, other_rows = 14, 26
    n_pages = 1 if len(rows) <= first_rows else 1 + (len(rows) - first_rows + other_rows - 1) // other_rows

    def page_head(first):
        y = H - 44
        p.text(40, y, sup["nom"], size=12, style="B", color=acc)
        p.text(W - 40, y, (lab["pf"] if ci["sous_type"] == "pro_forma" else lab["inv"]) + ("" if first else " (continued)"),
               size=13, style="B", align="r")
        p.text(W - 40, y - 13, f"{lab['no']} {ci['numero']} — {F.date(ci['date'], 'en_long')} — Page {p.page_no}/{n_pages}", size=8, align="r")
        return y - 28

    y = page_head(True)
    p.lines(40, y, sup["adresse"] + [sup["taxid"]], size=8)
    y -= 56
    y = _ci_parties(p, ci, lab, y, num, acc)
    idx = 0
    carried = D(0)
    page_rows = first_rows
    while idx < len(rows):
        chunk = rows[idx: idx + page_rows]
        lines = ci["lines"][idx: idx + page_rows]
        if idx > 0:
            chunk = [[None, None, f"Brought forward"] + [None] * (len(cols) - 4) + [F.money(carried, dev, num)]] + chunk
        y = p.table(40, y, cols, chunk, size=7.4, grid="h", head_fill=LIGHT, bottom=40, wrap_col=2)
        page_sum = sum((ln["amount"] for ln in lines), D(0))
        carried += page_sum
        idx += page_rows
        if idx < len(rows):
            p.text(W - 42, y - 12, f"Page total {F.money(page_sum, dev, num)} {dev} — carried forward {F.money(carried, dev, num)} {dev}",
                   size=7.8, style="I", align="r")
            p.new_page()
            y = page_head(False)
            page_rows = other_rows
    y -= 14
    for k, v in [(lab["goods"], ci["sub"]["marchandises"])] + [(lab[k], ci["sub"][k]) for k in ("fret", "assurance", "emballage") if k in ci["sub"]] + \
            ([(lab["remise"], -ci["sub"]["remise"])] if "remise" in ci["sub"] else []):
        if len(ci["sub"]) == 1:
            break
        p.text(W - 150, y, k, size=8.5, align="r")
        p.text(W - 42, y, F.money(v, dev, num), size=8.5, align="r")
        y -= 12
    p.text(W - 150, y - 2, f"INVOICE TOTAL {dev}", size=10, style="B", align="r")
    p.text(W - 42, y - 2, F.money(ci["total"], dev, num), size=10, style="B", align="r")
    y -= 22
    if y < 110:
        p.new_page()
        y = page_head(False)
    p.lines(40, y, _ci_info(ci, lab, num), size=8)
    return _end(p, ci, 40, 30)


def render_ci_ext(ci, rng) -> bytes:
    return {"CP": render_cp, "CL": render_cl, "CM": render_cm}[ci["layout"]](ci, rng)
