"""Documents support (liste de colisage, LTA, lettre d'accompagnement, conditions générales) et faux
document intitulé « invoice » (pré-alerte, P2)."""

from __future__ import annotations

from reportlab.lib.colors import HexColor

from . import fmtx as F
from .pdfkit import LIGHT, Pdf


def render_packing(doc, rng):
    ci = doc["ci"]
    lang = ci["lang"] if ci["lang"] in ("en", "fr", "de", "it", "es", "nl") else "en"
    t = {"en": ("PACKING LIST", "Net kg", "Gross kg", "Total"), "fr": ("LISTE DE COLISAGE", "Net kg", "Brut kg", "Total"),
         "de": ("PACKLISTE", "Netto kg", "Brutto kg", "Summe"), "it": ("DISTINTA DI IMBALLO", "Netto kg", "Lordo kg", "Totale"),
         "es": ("LISTA DE EMPAQUE", "Neto kg", "Bruto kg", "Total"), "nl": ("PAKLIJST", "Netto kg", "Bruto kg", "Totaal")}[lang]
    num = "en" if lang in ("en", "es") else "de"
    p = Pdf(title=t[0], family="Sans", lang_mark=lang)
    W, H = p.W, p.H
    y = H - 50
    p.text(40, y, ci["supplier"]["nom"], size=12, style="B")
    p.text(W - 40, y, t[0], size=15, style="B", align="r")
    y -= 18
    p.text(40, y, f"Ref. invoice / facture: {ci['numero']}   —   {F.date(ci['date'], 'iso')}", size=9)
    p.text(40, y - 12, f"Consignee: {ci['acheteur']['nom']}", size=9)
    p.text(40, y - 24, f"Transport: {ci['ref_transport']}", size=9)
    y -= 46
    rows = [[str(ln["no"]), ln["ref"], ln["desc"], F.qty(ln["qty"], num), F.mass(ln["net"], num), F.mass(ln["gross"], num)] for ln in ci["lines"]]
    rows.append(["", "", t[3], "", F.mass(ci["net_total"], num), F.mass(ci["gross_total"], num)])
    y = p.table(40, y, [("#", 24, "c"), ("Item", 70, "l"), ("Description", 230, "l"), ("Qty", 50, "r"), (t[1], 70, "r"), (t[2], 70, "r")],
                rows, size=8, grid="full", head_fill=LIGHT, wrap_col=2)
    y -= 16
    p.text(40, y, f"Packages / colis: {ci['colis']}", size=9.5, style="B")
    return p.save()


def render_awb(doc, rng):
    ci = doc["ci"]
    p = Pdf(title="Air Waybill", family="DV", lang_mark="en")
    W, H = p.W, p.H
    y = H - 50
    tr = ci["transport"]
    titre = {"air": "AIR WAYBILL (copy — not negotiable)", "sea": "BILL OF LADING (copy)", "road": "CMR — LETTRE DE VOITURE (copie)"}[tr["mode"]]
    p.text(40, y, titre, size=13, style="B")
    p.text(W - 40, y, tr["ref"], size=15, style="B", align="r")
    y -= 30
    boxes = [("Shipper", [ci["supplier"]["nom"]] + ci["supplier"]["adresse"][:2]),
             ("Consignee", [ci["acheteur"]["nom"]] + ci["acheteur"]["adresse"][:2]),
             ("Airport of departure / Port of loading", [ci["supplier"]["port"]]), ("Destination", ["Paris CDG (FR)" if tr["mode"] == "air" else "Le Havre (FR)"]),
             ("No. of pieces", [str(ci["colis"])]), ("Gross weight kg", [F.mass(ci["gross_total"], "en")]),
             ("Nature and quantity of goods", ["CONSOLIDATED GOODS — see invoice " + ci["numero"]]), ("Carrier", ["FICTIVE AIR CARGO 999"])]
    for i, (k, v) in enumerate(boxes):
        x = 40 + (i % 2) * ((W - 80) / 2)
        yy = y - (i // 2) * 60
        p.rect(x, yy - 54, (W - 80) / 2 - 4, 54, lw=0.6)
        p.text(x + 4, yy - 10, k, size=7, color=HexColor("#555555"))
        p.lines(x + 4, yy - 24, v, size=9)
    return p.save()


def render_letter(doc, rng):
    ft = doc["ft"]
    lang = doc["lang"]
    p = Pdf(title="Lettre", family="Serif", lang_mark=lang)
    W, H = p.W, p.H
    y = H - 60
    em = ft["emetteur"]
    p.text(50, y, em["nom"], size=13, style="B")
    p.lines(50, y - 14, em["adresse"], size=8.5)
    y -= 80
    cl = ft["client"]
    p.lines(W - 250, y, [cl["nom"]] + cl["adresse"], size=9.5)
    y -= 70
    txt = {
        "fr": [f"Objet : envoi de nos factures — dossier {', '.join(ft['refs_transport'])}", "", "Madame, Monsieur,",
               "Veuillez trouver ci-joint nos factures relatives au dédouanement de votre envoi ainsi que la copie de la déclaration.",
               "Nous restons à votre disposition pour toute question.", "", "Le service comptabilité"],
        "en": [f"Re: our invoices — shipment {', '.join(ft['refs_transport'])}", "", "Dear Sir or Madam,",
               "Please find enclosed our invoices for the customs clearance of your shipment together with a copy of the entry.",
               "Kind regards,", "", "Accounts department"],
        "de": [f"Betreff: Rechnungen zur Sendung {', '.join(ft['refs_transport'])}", "", "Sehr geehrte Damen und Herren,",
               "anbei erhalten Sie unsere Rechnungen zur Verzollung Ihrer Sendung.", "Mit freundlichen Grüßen", "", "Buchhaltung"],
        "it": [f"Oggetto: fatture spedizione {', '.join(ft['refs_transport'])}", "", "Spettabile cliente,",
               "in allegato le nostre fatture relative allo sdoganamento della Vostra spedizione.", "Distinti saluti", "", "Amministrazione"],
        "es": [f"Asunto: facturas del envío {', '.join(ft['refs_transport'])}", "", "Estimados señores:",
               "Adjuntamos nuestras facturas correspondientes al despacho de su envío.", "Atentamente,", "", "Administración"],
        "nl": [f"Betreft: facturen zending {', '.join(ft['refs_transport'])}", "", "Geachte heer, mevrouw,",
               "Bijgaand ontvangt u onze facturen voor de inklaring van uw zending.", "Met vriendelijke groet,", "", "Administratie"],
        "pt": [f"Assunto: faturas da remessa {', '.join(ft['refs_transport'])}", "", "Exmos. Senhores,",
               "Junto enviamos as nossas faturas relativas ao desalfandegamento da vossa remessa.", "Com os melhores cumprimentos,", "",
               "Contabilidade"],
        "pl": [f"Dotyczy: faktury za przesyłkę {', '.join(ft['refs_transport'])}", "", "Szanowni Państwo,",
               "w załączeniu przesyłamy faktury dotyczące odprawy celnej Państwa przesyłki.", "Z poważaniem,", "", "Księgowość"],
    }[lang]
    for ln in txt:
        y = p.para(50, y, W - 100, ln, size=10) - 4
    return p.save()


def render_cgv(doc, rng):
    ft = doc["ft"]
    lang = doc["lang"]
    p = Pdf(title="CGV", family="Sans", lang_mark=lang)
    W, H = p.W, p.H
    y = H - 50
    p.text(W / 2, y, {"fr": "CONDITIONS GÉNÉRALES DE VENTE", "en": "GENERAL TERMS AND CONDITIONS", "de": "ALLGEMEINE GESCHÄFTSBEDINGUNGEN",
                      "it": "CONDIZIONI GENERALI", "es": "CONDICIONES GENERALES", "nl": "ALGEMENE VOORWAARDEN",
                      "pt": "CONDIÇÕES GERAIS", "pl": "OGÓLNE WARUNKI ŚWIADCZENIA USŁUG"}[lang], size=12, style="B", align="c")
    y -= 24
    para = ("Article {n}. Les prestations sont exécutées conformément aux usages de la profession (texte fictif de démonstration). "
            "Les débours avancés pour le compte du client lui sont refacturés à l'identique. Toute réclamation doit être formulée par écrit. "
            "Exemple de montant figurant dans les conditions : pénalité forfaitaire de 40,00 EUR, taux d'intérêt de 3 fois le taux légal.")
    for n in range(1, 12):
        y = p.para(40, y, (W - 100) / 2, para.format(n=n), size=6.5) - 4
        if y < 80:
            break
    return p.save()


def render_prealert(doc, rng):
    ci = doc["ci"]
    p = Pdf(title="Pre-alert", family="Sans", lang_mark="en")
    W, H = p.W, p.H
    y = H - 50
    p.text(40, y, "INVOICE / PRE-ALERT", size=16, style="B")
    p.text(40, y - 16, "Shipment pre-advice — this document is NOT a commercial invoice", size=9, style="I")
    y -= 50
    p.lines(40, y, [f"Shipper: {ci['supplier']['nom']}", f"Consignee: {ci['acheteur']['nom']}", f"Expected AWB: {ci['ref_transport']}",
                    f"Estimated departure: {F.date(ci['date'], 'iso')}", f"Pieces: {ci['colis']} — approx. gross weight {F.mass(ci['gross_total'], 'en', 1)} kg",
                    "Commercial invoice will follow by e-mail."], size=10)
    y -= 100
    rows = [[ln["ref"], ln["desc"], F.qty(ln["qty"], "en")] for ln in ci["lines"]]
    p.table(40, y, [("Item", 90, "l"), ("Description", 300, "l"), ("Qty (approx.)", 90, "r")], rows, size=8.5, grid="h", head_fill=LIGHT)
    return p.save()


def render_misc(doc, rng):
    lay = doc["layout"]
    return {"PL": render_packing, "AWB": render_awb, "LTR": render_letter, "CGV": render_cgv, "XPA": render_prealert}[lay](doc, rng)
