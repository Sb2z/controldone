"""Présentations de déclaration M1 à M6.

M1  imprimé H1 (ou H7) sur deux pages, articles poursuivis en page 2 (page de suite sans en-tête complet)
M2  listing paysage tabulaire (un article par ligne) + tableau de liquidation
M3  « Customs clearance certificate » d'un commissionnaire, en anglais
M4  courriel texte seul (.eml) récapitulant la déclaration
M5  export XML (schéma inventé urn:fictif:g2:dedouanement:2)
M6  export CSV « ; », décimales à virgule, ligne de commentaire, une ligne par imposition
"""

from __future__ import annotations

import hashlib
from decimal import Decimal as D

from lxml import etree
from reportlab.lib.colors import HexColor

from . import fmtx as F
from .pdfkit import LIGHT, Pdf
from .util import FICTIF

PAY_FR = {"A": "comptant", "E": "différé (crédit d'enlèvement)", "G": "autoliquidation TVA"}
PAY_EN = {"A": "cash", "E": "deferred", "G": "postponed (reverse charge)"}
PAY_M4 = {"A": "payé comptant", "E": "paiement différé", "G": "autoliquidée"}
PAY_M6 = {"A": "COMPTANT", "E": "DIFFERE", "G": "AUTOLIQUIDATION"}
TAX_FR = {"A00": "Droits de douane", "A30": "Droit antidumping", "B00": "TVA import", "FPE": "Droit forfaitaire petits envois"}
TAX_EN = {"A00": "Customs duty", "A30": "Anti-dumping duty", "B00": "Import VAT", "FPE": "Flat-rate duty (low value)"}
REF_FR = {"N380": "Facture commerciale", "N325": "Facture pro forma", "N740": "LTA", "N705": "Connaissement", "N730": "CMR",
          "1008": "Autoliquidation TVA — n° TVA", "FR7": "Référence fiscale complémentaire"}
UNIT_SUP = {"C62": "p/st", "PR": "pa", "KGM": "kg"}


def rate_text(dec, lang, num):
    r = dec["rate"]
    if r is None:
        return None
    dv = dec["devise_taux"]
    s = F.amt(r, num, 5)
    if dec["sens"] == "devise_par_eur":
        return f"1 EUR = {s} {dv}" if lang == "fr" else f"EUR 1 = {dv} {s}"
    return f"1 {dv} = {s} EUR" if lang == "fr" else f"{dv} 1 = EUR {s}"


def desig(dec, art):
    s = art["desc"]
    if dec.get("desig_refs"):
        refs = art.get("refs_printed", art["refs"])
        s += " — réf. " + ", ".join(refs)
    return s


def _tax_rows_for(dec, art_no):
    return [t for t in dec["taxes"] if t["article"] == art_no]


def _type_totals(dec):
    return dec["type_totals"]


# ---------------------------------------------------------------------------
# M1 — imprimé sur deux pages
# ---------------------------------------------------------------------------

def render_m1(dec, rng):
    num = "fr"
    h7 = dec["h7"]
    p = Pdf(title=f"Déclaration {dec['mrn']}", family="Sans", lang_mark="fr", mark_pos="top")
    W, H = p.W, p.H
    acc = HexColor("#1f618d")
    y = H - 40
    p.text(36, y, "DÉCLARATION EN DOUANE — IMPORTATION", size=13, style="B", color=acc)
    p.text(36, y - 14, ("Données H7 — envois de faible valeur" if h7 else "Données H1 — mise en libre pratique et mise à la consommation"),
           size=8.5)
    p.text(W - 36, y, f"MRN {dec['mrn']}", size=11, style="B", align="r")
    p.text(W - 36, y - 13, f"LRN {dec['lrn']} — version {dec['version']}", size=8, align="r")
    p.text(W - 36, y - 24, f"Acceptée le {F.date(dec['date'], 'dmy/')}", size=8, align="r")
    y -= 40
    # cases d'en-tête
    boxes = [
        ("Importateur", [dec["importateur"]["nom"], f"TVA {dec['importateur']['tva']}", f"EORI {dec['importateur']['eori']}"]),
        ("Déclarant / représentant (représentation directe)", [dec["declarant"]["nom"], f"TVA {dec['declarant']['tva']}"]),
        ("Conditions de livraison", [f"{dec['incoterm']} {dec['incoterm_lieu']}", f"Pays d'expédition : {dec['pays_exp']}"]),
        ("Montant total facturé", [f"{F.money(dec['montant'], dec['devise'], num)} {dec['devise']}"] + ([f"Taux de change : {rate_text(dec, 'fr', num)}"] if dec["rate"] else [])),
        ("Masse brute totale / colis", [f"{F.mass(dec['gross_total'], num)} kg", f"{dec['colis_total']} colis"]),
        ("Nombre d'articles", [str(dec["n_articles"])]),
    ]
    bw = (W - 72) / 2
    for i, (t, ls) in enumerate(boxes):
        x = 36 + (i % 2) * bw
        yy = y - (i // 2) * 52
        p.rect(x, yy - 48, bw - 4, 48, lw=0.5)
        p.text(x + 4, yy - 9, t, size=6.8, color=HexColor("#555555"))
        p.lines(x + 4, yy - 21, ls, size=8.3, leading=10)
    y -= 3 * 52 + 10
    arts = dec["articles"]
    cut = max(1, (len(arts) + 1) // 2) if len(arts) > 1 else 1
    first, rest = arts[:cut], arts[cut:]

    def art_block(a, y):
        p.rect(36, y - 14, W - 72, 14, lw=0, fill=LIGHT, stroke=False)
        p.text(40, y - 10, f"Article {a['no']}", size=8.5, style="B")
        p.text(110, y - 10, f"Code marchandise {a['hs10']}", size=8.5)
        p.text(W - 40, y - 10, f"Origine {a['origin']}  Préf. {a['pref']}  Régime {a['regime']} {a['regime_c']}", size=8, align="r")
        y -= 26
        y = p.para(40, y, W - 80, desig(dec, a), size=8.2) - 2
        info = (f"Montant facturé : {F.money(a['amount'], dec['devise'], num)} {dec['devise']}   Valeur statistique : {F.amt(a['stat_value'], num)} EUR   "
                f"Masse nette : {F.mass(a['net'], num)} kg   Masse brute : {F.mass(a['gross'], num)} kg   Colis : {a['colis']}")
        y = p.para(40, y, W - 80, info, size=7.8) - 2
        if a["qty"] is not None:
            p.text(40, y, f"Quantité en unités supplémentaires : {F.qty(a['qty'], num)} {UNIT_SUP.get(a['qty_unit'], a['qty_unit'])}", size=7.8)
            y -= 11
        rows = [[t["type"], TAX_FR.get(t["type"], t["type"]), F.amt(t["base"], num) if t["base"] is not None else "",
                 F.rate(t["rate"], num) + " %", F.amt(t["montant"], num), F.amt(t["a_payer"], num), t["mode"]] for t in _tax_rows_for(dec, a["no"])]
        if rows:
            y = p.table(40, y, [("Type", 36, "l"), ("Libellé", 150, "l"), ("Base (EUR)", 90, "r"), ("Taux", 50, "r"), ("Montant", 80, "r"),
                                 ("À payer", 70, "r"), ("MP", 30, "c")], rows, size=7.6, grid="h", head_fill=None, bottom=40)
        return y - 10

    for a in first:
        y = art_block(a, y)
    # page 2 : suite
    p.new_page()
    y = H - 40
    p.text(36, y, f"Suite — déclaration MRN {dec['mrn']}", size=9, style="B", color=acc)
    p.text(W - 36, y, "page 2/2", size=8, align="r")
    y -= 24
    for a in rest:
        y = art_block(a, y)
    lvl = [t for t in dec["taxes"] if t["article"] is None]
    if lvl:
        p.text(36, y, "Impositions au niveau de la déclaration", size=9, style="B")
        y -= 4
        rows = []
        for t in lvl:
            base = F.amt(t["base"], num) if t["base"] is not None else f"{F.qty(t['base_qty'], num)} articles"
            taux = (F.amt(t["rate"], num) + " EUR/article") if t["nature"] == "specifique" else F.rate(t["rate"], num) + " %"
            rows.append([t["type"], TAX_FR.get(t["type"], t["type"]), base, taux, F.amt(t["montant"], num), F.amt(t["a_payer"], num), t["mode"]])
        y = p.table(36, y, [("Type", 36, "l"), ("Libellé", 160, "l"), ("Base", 90, "r"), ("Taux", 80, "r"), ("Montant", 70, "r"),
                             ("À payer", 60, "r"), ("MP", 30, "c")], rows, size=7.8, grid="h", head_fill=LIGHT)
        y -= 12
    p.text(36, y, "Documents produits / références", size=9, style="B")
    y -= 4
    y = p.table(36, y, [("Code", 50, "l"), ("Nature", 200, "l"), ("Référence", 200, "l")],
                [[r["code"], REF_FR.get(r["code"], ""), r["ref"]] for r in dec["refs"]], size=8, grid="h", head_fill=LIGHT)
    y -= 16
    p.text(36, y, "Récapitulatif de la liquidation", size=9, style="B")
    y -= 4
    rows = [[k, TAX_FR.get(k, k), F.amt(v, num)] for k, v in _type_totals(dec).items()]
    rows.append(["", "Total droits et taxes", F.amt(dec["total_droits_taxes"], num)])
    rows.append(["", "Total à payer ou à garantir", F.amt(dec["total_a_payer"], num)])
    y = p.table(36, y, [("Type", 50, "l"), ("Libellé", 250, "l"), ("Montant (EUR)", 120, "r")], rows, size=8, grid="h", head_fill=LIGHT)
    y -= 14
    p.text(36, y, "MP (mode de paiement) : A = comptant ; E = paiement différé ; G = TVA autoliquidée (art. 1695 CGI).", size=7, style="I")
    p.text(36, y - 10, "Mainlevée accordée. Document imprimé par le déclarant — " + FICTIF, size=7, style="I")
    if dec.get("hidden_instr"):
        p.hidden_text(36, 40, dec["hidden_instr"])
    return p.save()


# ---------------------------------------------------------------------------
# M2 — listing paysage
# ---------------------------------------------------------------------------

def render_m2(dec, rng):
    num = "frs"
    p = Pdf(land=True, title=f"Liquidation {dec['mrn']}", family="Mono", lang_mark="fr")
    W, H = p.W, p.H
    y = H - 34
    p.text(30, y, "SIMULOGICIEL DOUANE (FICTIF) — EDITION DE LA DECLARATION ACCEPTEE", size=9.5, style="B")
    p.text(W - 30, y, f"Edité le {F.date(dec['date'], 'dmy/')}", size=8, align="r")
    y -= 16
    hdr = [f"MRN: {dec['mrn']}   LRN: {dec['lrn']}   Version: {dec['version']}   Type: {'IM A / H7' if dec['h7'] else 'IM A / H1'}   Date d'acceptation: {F.date(dec['date'], 'dmy/')}",
           f"Importateur: {dec['importateur']['nom']}  TVA: {dec['importateur']['tva']}  EORI: {dec['importateur']['eori']}",
           f"Déclarant: {dec['declarant']['nom']}  TVA: {dec['declarant']['tva']}",
           f"Incoterm: {dec['incoterm']} {dec['incoterm_lieu']}   Pays d'expédition: {dec['pays_exp']}   Monnaie de facturation: {dec['devise']}   "
           f"Montant total facturé: {F.money(dec['montant'], dec['devise'], num)}" + (f"   Taux: {rate_text(dec, 'fr', num)}" if dec["rate"] else ""),
           f"Masse brute totale: {F.mass(dec['gross_total'], num)} kg   Colis: {dec['colis_total']}   Nombre d'articles: {dec['n_articles']}",
           "Documents: " + " | ".join(f"{r['code']} {r['ref']}" for r in dec["refs"])]
    y = p.lines(30, y, hdr, size=7.6, leading=10.5)
    y -= 6
    cols = [("Art", 26, "c"), ("Code NC", 70, "l"), ("Désignation", 210, "l"), ("Or.", 26, "c"), ("Pf", 24, "c"), ("Rég.", 40, "c"),
            ("Mt facturé", 78, "r"), ("Val. stat.", 70, "r"), ("Net kg", 62, "r"), ("Brut kg", 62, "r"), ("Qté sup.", 60, "r"), ("Colis", 36, "r")]
    rows = [[str(a["no"]), a["hs10"], desig(dec, a), a["origin"], a["pref"], a["regime"], F.money(a["amount"], dec["devise"], num),
             F.amt(a["stat_value"], num), F.mass(a["net"], num), F.mass(a["gross"], num),
             (F.qty(a["qty"], num) + " " + UNIT_SUP.get(a["qty_unit"], "")) if a["qty"] is not None else "", str(a["colis"])] for a in dec["articles"]]
    y = p.table(30, y, cols, rows, size=7, grid="full", head_fill=LIGHT, wrap_col=2, bottom=60, cell_font="Mono")
    y -= 12
    if y < 160:
        p.new_page()
        y = H - 40
    p.text(30, y, "LIQUIDATION", size=9, style="B")
    y -= 4
    rows = []
    for t in dec["taxes"]:
        base = F.amt(t["base"], num) if t["base"] is not None else f"{F.qty(t['base_qty'], num)} art."
        taux = F.amt(t["rate"], num) + " EUR/art." if t["nature"] == "specifique" else F.rate(t["rate"], num) + " %"
        rows.append([str(t["article"]) if t["article"] else "décl.", t["type"], base, taux, F.amt(t["montant"], num), F.amt(t["a_payer"], num), t["mode"]])
    y = p.table(30, y, [("Art", 40, "c"), ("Type", 40, "c"), ("Base", 100, "r"), ("Taux", 90, "r"), ("Montant", 90, "r"), ("A payer", 90, "r"), ("MP", 30, "c")],
                rows, size=7.4, grid="full", head_fill=LIGHT, cell_font="Mono", bottom=60)
    y -= 10
    tot = "   ".join(f"Total {k}: {F.amt(v, num)}" for k, v in _type_totals(dec).items())
    p.text(30, y, tot, size=7.6)
    p.text(30, y - 11, f"TOTAL DROITS ET TAXES: {F.amt(dec['total_droits_taxes'], num)} EUR     TOTAL A PAYER: {F.amt(dec['total_a_payer'], num)} EUR", size=8, style="B")
    p.text(30, y - 22, "MP: A=comptant E=différé G=autoliquidation", size=7)
    if dec.get("hidden_instr"):
        p.hidden_text(30, 30, dec["hidden_instr"])
    return p.save()


# ---------------------------------------------------------------------------
# M3 — certificat de dédouanement (anglais)
# ---------------------------------------------------------------------------

def render_m3(dec, rng):
    num = "en"
    p = Pdf(title=f"Clearance certificate {dec['mrn']}", family="FSerif", lang_mark="en")
    W, H = p.W, p.H
    acc = HexColor("#283747")
    y = H - 50
    p.text(W / 2, y, dec["declarant"]["nom"], size=13, style="B", align="c", color=acc)
    p.text(W / 2, y - 13, "Registered customs representative — VAT " + dec["declarant"]["tva"], size=8, align="c")
    y -= 40
    p.text(W / 2, y, "CERTIFICATE OF CUSTOMS CLEARANCE", size=15, style="B", align="c")
    p.text(W / 2, y - 14, "Import — release for free circulation" + (" (H7 low value consignment)" if dec["h7"] else ""), size=9, align="c")
    y -= 36
    p.para(40, y, W - 80, (f"We hereby certify that the goods described below were declared on behalf of {dec['importateur']['nom']} "
                           f"and released by French customs on {F.date(dec['date'], 'en_long')} under MRN {dec['mrn']}."), size=9)
    y -= 34
    kv = [("MRN", dec["mrn"]), ("Local reference", dec["lrn"]), ("Acceptance date", F.date(dec["date"], "iso")),
          ("Importer", f"{dec['importateur']['nom']} — VAT {dec['importateur']['tva']} — EORI {dec['importateur']['eori']}"),
          ("Delivery terms", f"{dec['incoterm']} {dec['incoterm_lieu']}"), ("Country of dispatch", dec["pays_exp"]),
          ("Invoice currency / total", f"{dec['devise']} {F.money(dec['montant'], dec['devise'], num)}"),
          ("Exchange rate applied", rate_text(dec, "en", num) or "n/a"),
          ("Gross mass / packages", f"{F.mass(dec['gross_total'], num)} kg / {dec['colis_total']} packages"),
          ("Number of items", str(dec["n_articles"])),
          ("Supporting documents", "; ".join(f"{r['code']} {r['ref']}" for r in dec["refs"]))]
    for k, v in kv:
        p.text(40, y, k, size=8.5, style="B")
        y = p.para(180, y, W - 220, v, size=8.5) - 3
    y -= 8
    rows = [[str(a["no"]), a["hs10"], desig(dec, a), a["origin"], F.mass(a["net"], num), F.mass(a["gross"], num),
             F.money(a["amount"], dec["devise"], num)] for a in dec["articles"]]
    y = p.table(40, y, [("Item", 30, "c"), ("Commodity code", 72, "l"), ("Description", 175, "l"), ("Origin", 40, "c"), ("Net kg", 60, "r"),
                         ("Gross kg", 60, "r"), (f"Value {dec['devise']}", 78, "r")], rows, size=7.6, grid="h", head_fill=LIGHT, wrap_col=2, bottom=80)
    y -= 14
    if y < 200:
        p.new_page()
        y = H - 50
    p.text(40, y, "Duties and taxes", size=10, style="B")
    y -= 4
    rows = []
    for t in dec["taxes"]:
        basis = ("EUR " + F.amt(t["base"], num)) if t["base"] is not None else f"{F.qty(t['base_qty'], num)} items"
        rate = (f"EUR {F.amt(t['rate'], num)} per item") if t["nature"] == "specifique" else F.rate(t["rate"], num) + "%"
        rows.append([str(t["article"]) if t["article"] else "all", f"{t['type']} {TAX_EN.get(t['type'], '')}", basis, rate,
                     F.amt(t["montant"], num), PAY_EN[t["mode"]]])
    y = p.table(40, y, [("Item", 30, "c"), ("Tax", 140, "l"), ("Basis", 90, "r"), ("Rate", 90, "r"), ("Amount EUR", 80, "r"), ("Payment", 85, "l")],
                rows, size=7.6, grid="h", head_fill=LIGHT, bottom=80)
    y -= 12
    for k, v in _type_totals(dec).items():
        p.text(W - 160, y, f"Total {k}", size=8.5, align="r")
        p.text(W - 44, y, "EUR " + F.amt(v, num), size=8.5, align="r")
        y -= 11
    p.text(W - 160, y, "Total duties and taxes", size=9, style="B", align="r")
    p.text(W - 44, y, "EUR " + F.amt(dec["total_droits_taxes"], num), size=9, style="B", align="r")
    y -= 12
    p.text(W - 160, y, "Total payable / secured", size=9, style="B", align="r")
    p.text(W - 44, y, "EUR " + F.amt(dec["total_a_payer"], num), size=9, style="B", align="r")
    p.stamp(140, 90, "RELEASED", size=18, angle=-10, color=HexColor("#1e8449"), alpha=0.5)
    if dec.get("hidden_instr"):
        p.hidden_text(40, 40, dec["hidden_instr"])
    return p.save()


# ---------------------------------------------------------------------------
# M4 — courriel texte seul
# ---------------------------------------------------------------------------

def render_m4(dec, rng, client_nom="", fwd_domain="transitaire-fictif.invalid") -> bytes:
    num = "frn"
    lines = []
    lines.append("Bonjour,")
    lines.append("")
    lines.append(f"Votre déclaration d'importation{' H7' if dec['h7'] else ''} a été acceptée par la douane le {F.date(dec['date'], 'fr_long')}.")
    lines.append("Voici le récapitulatif (le document officiel suit par voie postale).")
    lines.append("")
    lines.append(f"  MRN ..................... {dec['mrn']}")
    lines.append(f"  LRN ..................... {dec['lrn']} (version {dec['version']})")
    lines.append(f"  Importateur ............. {dec['importateur']['nom']}")
    lines.append(f"  N° TVA importateur ...... {dec['importateur']['tva']}")
    lines.append(f"  EORI .................... {dec['importateur']['eori']}")
    lines.append(f"  Déclarant ............... {dec['declarant']['nom']} (TVA {dec['declarant']['tva']})")
    lines.append(f"  Incoterm ................ {dec['incoterm']} {dec['incoterm_lieu']}")
    lines.append(f"  Pays d'expédition ....... {dec['pays_exp']}")
    lines.append(f"  Montant facturé ......... {F.money(dec['montant'], dec['devise'], num)} {dec['devise']}")
    if dec["rate"]:
        lines.append(f"  Taux de change .......... {rate_text(dec, 'fr', num)}")
    lines.append(f"  Masse brute totale ...... {F.mass(dec['gross_total'], num)} kg")
    lines.append(f"  Nombre de colis ......... {dec['colis_total']}")
    lines.append(f"  Nombre d'articles ....... {dec['n_articles']}")
    lines.append("  Documents cités ......... " + " ; ".join(f"{r['code']} {r['ref']}" for r in dec["refs"]))
    lines.append("")
    lines.append("ARTICLES")
    for a in dec["articles"]:
        lines.append(f"  [{a['no']}] {a['hs10']}  {desig(dec, a)}")
        lines.append(f"      origine {a['origin']} | montant facturé {F.money(a['amount'], dec['devise'], num)} {dec['devise']} | "
                     f"net {F.mass(a['net'], num)} kg | brut {F.mass(a['gross'], num)} kg | colis {a['colis']}")
        for t in _tax_rows_for(dec, a["no"]):
            lines.append(f"      {t['type']} {TAX_FR.get(t['type'], '')} : base {F.amt(t['base'], num)} EUR x {F.rate(t['rate'], num)} % = "
                         f"{F.amt(t['montant'], num)} EUR ({PAY_M4[t['mode']]})")
    lvl = [t for t in dec["taxes"] if t["article"] is None]
    if lvl:
        lines.append("")
        lines.append("IMPOSITIONS GLOBALES")
        for t in lvl:
            if t["nature"] == "specifique":
                lines.append(f"  {t['type']} {TAX_FR.get(t['type'], '')} : {F.qty(t['base_qty'], num)} articles x {F.amt(t['rate'], num)} EUR = "
                             f"{F.amt(t['montant'], num)} EUR ({PAY_M4[t['mode']]})")
            else:
                lines.append(f"  {t['type']} {TAX_FR.get(t['type'], '')} : base {F.amt(t['base'], num)} EUR x {F.rate(t['rate'], num)} % = "
                             f"{F.amt(t['montant'], num)} EUR ({PAY_M4[t['mode']]})")
    lines.append("")
    lines.append(f"Total droits et taxes : {F.amt(dec['total_droits_taxes'], num)} EUR")
    lines.append(f"Total à payer : {F.amt(dec['total_a_payer'], num)} EUR")
    lines.append("")
    lines.append("Cordialement,")
    lines.append(f"Le service déclarations — {dec['declarant']['nom']}")
    lines.append("")
    lines.append("-- ")
    lines.append(f"{FICTIF} — message de test généré, adresses et numéros inventés.")
    if dec.get("hidden_instr"):
        lines.append("")
        lines.append(dec["hidden_instr"])
    body = "\r\n".join(lines) + "\r\n"
    mid = hashlib.sha256(dec["mrn"].encode()).hexdigest()[:20]
    d = dec["date"]
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][d.weekday()]
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][d.month - 1]
    headers = [
        f"From: Service declarations <declarations@{fwd_domain}>",
        f"To: Import <import@client-fictif.invalid>",
        f"Subject: =?utf-8?q?Bon_=C3=A0_enlever_-_MRN_{dec['mrn']}?=",
        f"Date: {days}, {d.day:02d} {months} {d.year} 10:{rng.randint(10, 59):02d}:00 +0200",
        f"Message-ID: <{mid}@{fwd_domain}>",
        "MIME-Version: 1.0",
        "Content-Type: text/plain; charset=utf-8",
        "Content-Transfer-Encoding: 8bit",
        "X-Mention: DONNEES FICTIVES",
    ]
    return ("\r\n".join(headers) + "\r\n\r\n" + body).encode("utf-8")


# ---------------------------------------------------------------------------
# M5 — export XML (schéma inventé)
# ---------------------------------------------------------------------------

NS5 = "urn:fictif:g2:dedouanement:2"


def render_m5(dec, rng) -> bytes:
    def e(parent, tag, text=None, **attrs):
        el = etree.SubElement(parent, f"{{{NS5}}}{tag}", **{k.replace("_", "-"): str(v) for k, v in attrs.items() if v is not None})
        if text is not None:
            el.text = str(text)
        return el

    root = etree.Element(f"{{{NS5}}}dedouanement", nsmap={None: NS5}, version="2.0")
    e(root, "mention", FICTIF + " — export de test")
    ds = e(root, "dossier", mrn=dec["mrn"], lrn=dec["lrn"], rang=dec["version"], jeu="H7" if dec["h7"] else "H1",
           acceptee_le=dec["date"].isoformat())
    ac = e(ds, "acteurs")
    e(ac, "importateur", dec["importateur"]["nom"], tva=dec["importateur"]["tva"], eori=dec["importateur"]["eori"])
    e(ac, "declarant", dec["declarant"]["nom"], tva=dec["declarant"]["tva"], representation="directe")
    e(ds, "livraison", incoterm=dec["incoterm"], lieu=dec["incoterm_lieu"], expedition=dec["pays_exp"])
    fa = e(ds, "facturation", monnaie=dec["devise"], total=dec["montant"])
    if dec["rate"] is not None:
        e(fa, "conversion", dec["rate"], monnaie=dec["devise_taux"],
          expression="unites_devise_pour_un_euro" if dec["sens"] == "devise_par_eur" else "euros_pour_une_unite_devise")
    e(ds, "colisage", masse_brute_kg=dec["gross_total"], colis=dec["colis_total"], positions=dec["n_articles"])
    pc = e(ds, "pieces")
    for r in dec["refs"]:
        e(pc, "piece", r["ref"], code=r["code"])
    ps = e(ds, "positions")
    for a in dec["articles"]:
        po = e(ps, "position", rang=a["no"])
        e(po, "nomenclature", a["hs10"])
        e(po, "libelle", desig(dec, a))
        e(po, "origine", a["origin"])
        e(po, "preference", a["pref"])
        e(po, "regime", a["regime"], complementaire=a["regime_c"])
        e(po, "montant-facture", a["amount"])
        e(po, "valeur-statistique", a["stat_value"])
        e(po, "masse", nette=a["net"], brute=a["gross"])
        if a["qty"] is not None:
            e(po, "quantite", a["qty"], unite=UNIT_SUP.get(a["qty_unit"], a["qty_unit"]))
        e(po, "colis", a["colis"])
        im = e(po, "impositions")
        for t in _tax_rows_for(dec, a["no"]):
            e(im, "imposition", code=t["type"], assiette=t["base"], taux=t["rate"], mode_calcul=t["nature"], montant=t["montant"],
              exigible=t["a_payer"], paiement=t["mode"])
    lvl = [t for t in dec["taxes"] if t["article"] is None]
    if lvl:
        ig = e(ds, "impositions-globales")
        for t in lvl:
            e(ig, "imposition", code=t["type"], assiette=t["base"], assiette_quantite=t["base_qty"],
              unite_assiette=t["base_unit"], taux=t["rate"], mode_calcul=t["nature"], montant=t["montant"], exigible=t["a_payer"],
              paiement=t["mode"], libelle=TAX_FR.get(t["type"]))
    rc = e(ds, "recapitulatif")
    for k, v in _type_totals(dec).items():
        e(rc, "total", v, code=k)
    e(rc, "total-droits-taxes", dec["total_droits_taxes"])
    e(rc, "total-a-acquitter", dec["total_a_payer"])
    if dec.get("hidden_instr"):
        e(root, "commentaire-libre", dec["hidden_instr"])
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)


# ---------------------------------------------------------------------------
# M6 — CSV dénormalisé
# ---------------------------------------------------------------------------

M6_COLS = ["mrn", "lrn", "rang", "date_acceptation", "importateur", "tva_importateur", "eori_importateur", "declarant",
           "tva_declarant", "incoterm", "lieu_livraison", "pays_expedition", "monnaie_facture", "total_facture", "taux_change",
           "base_taux", "masse_brute_totale", "colis_total", "nb_positions", "pieces_jointes", "position", "code_nc",
           "designation", "origine", "preference", "regime", "montant_facture_position", "valeur_statistique", "masse_nette",
           "masse_brute", "quantite", "unite_quantite", "colis_position", "type_imposition", "libelle_imposition", "assiette",
           "assiette_quantite", "unite_assiette", "taux", "mode_calcul", "montant", "montant_exigible", "mode_paiement",
           "total_droits_taxes", "total_a_acquitter"]


def _c(v):
    if v is None:
        return ""
    if isinstance(v, D):
        return format(v, "f").replace(".", ",")
    s = str(v)
    if ";" in s or '"' in s:
        s = '"' + s.replace('"', '""') + '"'
    return s


def render_m6(dec, rng) -> bytes:
    out = [f"# Export liquidation Simulogiciel (FICTIF) — {FICTIF} — séparateur ; décimales virgule"]
    out.append(";".join(M6_COLS))
    pieces = "|".join(f"{r['code']}:{r['ref']}" for r in dec["refs"])
    head = [dec["mrn"], dec["lrn"], dec["version"], dec["date"].strftime("%d/%m/%Y"), dec["importateur"]["nom"],
            dec["importateur"]["tva"], dec["importateur"]["eori"], dec["declarant"]["nom"], dec["declarant"]["tva"],
            dec["incoterm"], dec["incoterm_lieu"], dec["pays_exp"], dec["devise"], dec["montant"],
            dec["rate"], ("1EUR" if dec.get("sens") == "devise_par_eur" else "1DEVISE") if dec["rate"] else None,
            dec["gross_total"], dec["colis_total"], dec["n_articles"], pieces]
    tail = [dec["total_droits_taxes"], dec["total_a_payer"]]
    arts = {a["no"]: a for a in dec["articles"]}
    for t in dec["taxes"]:
        a = arts.get(t["article"])
        if a is not None:
            art = [a["no"], a["hs10"], desig(dec, a), a["origin"], a["pref"], a["regime"], a["amount"], a["stat_value"], a["net"], a["gross"],
                   a["qty"], UNIT_SUP.get(a["qty_unit"]) if a["qty"] is not None else None, a["colis"]]
        else:
            art = [None] * 13
        tx = [t["type"], TAX_FR.get(t["type"]), t["base"], t["base_qty"], t["base_unit"], t["rate"], t["nature"], t["montant"],
              t["a_payer"], PAY_M6[t["mode"]]]
        out.append(";".join(_c(v) for v in head + art + tx + tail))
    # articles sans imposition (H7) : une ligne descriptive
    taxed = {t["article"] for t in dec["taxes"]}
    for a in dec["articles"]:
        if a["no"] not in taxed:
            art = [a["no"], a["hs10"], desig(dec, a), a["origin"], a["pref"], a["regime"], a["amount"], a["stat_value"], a["net"], a["gross"],
                   a["qty"], UNIT_SUP.get(a["qty_unit"]) if a["qty"] is not None else None, a["colis"]]
            out.append(";".join(_c(v) for v in head + art + [None] * 10 + tail))
    if dec.get("hidden_instr"):
        out.append("# " + dec["hidden_instr"])
    return ("\r\n".join(out) + "\r\n").encode("cp1252", errors="replace")


def render_decl(dec, rng, **kw):
    lay = dec["layout"]
    if lay == "M1":
        return render_m1(dec, rng)
    if lay == "M2":
        return render_m2(dec, rng)
    if lay == "M3":
        return render_m3(dec, rng)
    if lay == "M4":
        return render_m4(dec, rng, **kw)
    if lay == "M5":
        return render_m5(dec, rng)
    return render_m6(dec, rng)
