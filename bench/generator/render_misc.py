"""Rendu des documents support (LTA, connaissement, liste de colisage, lettre, CG) et des documents
non exploitables intitulés « facture » (pré-alerte, devis, bon de commande…)."""

from __future__ import annotations

from .common import d_en, d_fr, fmt_kg, fmt_qty
from .pdfkit import DARK, GREY, LIGHT, Pen
from .refdata import UNIT_LABELS

CG_TEXT = [
    "Article 1 - Objet. Les présentes conditions générales (FICTIVES) régissent les prestations de transport, de "
    "dédouanement et de logistique réalisées par le transitaire de démonstration pour le compte de ses clients. "
    "Elles sont rédigées pour un banc de test et n'ont aucune valeur contractuelle.",
    "Article 2 - Débours. Les droits, taxes et autres sommes avancés pour le compte du client sont refacturés à "
    "l'identique, sur justificatif, et donnent lieu à des frais d'avance de fonds selon le tarif convenu.",
    "Article 3 - Tarifs. Les prestations sont facturées selon la grille tarifaire en vigueur à la date de "
    "l'opération. Toute prestation non prévue fait l'objet d'un accord préalable écrit.",
    "Article 4 - Paiement. Les factures sont payables à trente jours date de facture, sans escompte. Les pénalités "
    "de retard mentionnées ici sont fictives et données à titre d'exemple de mise en page.",
    "Article 5 - Magasinage. Les marchandises non enlevées à l'issue de la franchise donnent lieu à facturation "
    "de frais de magasinage par jour calendaire selon la grille.",
    "Article 6 - Responsabilité. La responsabilité du transitaire de démonstration est limitée dans les conditions "
    "prévues par les textes applicables ; le présent texte est un simple contenu de remplissage.",
    "Article 7 - Réclamations. Toute réclamation doit être adressée par écrit au service client fictif dont les "
    "coordonnées figurent en tête de facture.",
    "Article 8 - Données. Les données figurant sur ce document sont entièrement fictives et générées "
    "automatiquement pour l'évaluation d'un logiciel.",
    "Article 9 - Montants d'exemple. À titre d'illustration, un dossier type de 1 250,00 EUR de débours donne lieu "
    "à des frais d'avance de fonds de 31,25 EUR ; ce montant n'est pas une ligne facturée.",
    "Article 10 - Juridiction. Le tribunal de commerce de la ville fictive de Villefictive est seul compétent pour "
    "les besoins de cet exemple.",
]


def render_awb(pen: Pen, s, dm, variant):
    d = s.data
    pen.set_theme("mono" if variant % 2 else "sans")
    if d["kind"] == "awb":
        pen.text(12, 14, "AIR WAYBILL (NOT NEGOTIABLE) - FICTIF", size=12, bold=True)
        pen.text(198, 14, d["ref"], size=12, bold=True, align="right")
        lab = "AWB No."
    else:
        pen.text(12, 14, "BILL OF LADING - FICTIF", size=12, bold=True)
        pen.text(198, 14, d["ref"], size=12, bold=True, align="right")
        lab = "B/L No."
    pen.rect(10, 20, 95, 28)
    pen.text(12, 24, "Shipper", size=7, color=GREY)
    pen.lines(12, 28, [d["shipper"].name] + list(d["shipper"].addr), size=7.8, maxw=90)
    pen.rect(105, 20, 95, 28)
    pen.text(107, 24, "Consignee", size=7, color=GREY)
    pen.lines(107, 28, [d["consignee"].name] + list(d["consignee"].addr) + [f"VAT {d['consignee'].vat}"], size=7.8,
              maxw=90)
    pen.rect(10, 48, 95, 16)
    pen.text(12, 52, "Issuing carrier's agent", size=7, color=GREY)
    pen.text(12, 57, d["agent"], size=7.8, maxw=90)
    pen.rect(105, 48, 95, 16)
    pen.text(107, 52, "Routing", size=7, color=GREY)
    pen.text(107, 57, f"{d['origin_port']} -> {d['dest']}", size=7.8)
    y = pen.table(10, 70, [(lab, 50, "left"), ("Pieces", 25, "right"), ("Gross weight (kg)", 40, "right"),
                           ("Chargeable weight (kg)", 40, "right"), ("Date", 35, "center")],
                  [[d["ref"], str(d["packages"]), fmt_kg(d["gross"], "en"),
                    fmt_kg(max(d["gross"], d["gross"] * 1), "en"), d_en(d["date"])]], size=8, row_h=6)
    pen.text(12, y + 8, "Nature and quantity of goods: as per commercial invoice. Freight charges: as agreed.",
             size=7.5)
    pen.text(12, y + 13, "Documents attached: commercial invoice, packing list.", size=7.5)


def render_packing(pen: Pen, s, dm, variant):
    d = s.data
    lang = s.language
    pen.set_theme("sans" if variant % 2 else "dejavu")
    title = {"en": "PACKING LIST", "fr": "LISTE DE COLISAGE", "es": "LISTA DE EMPAQUE"}[lang]
    pen.text(12, 15, d["seller"].name, size=11, bold=True, maxw=120)
    pen.lines(12, 20, list(d["seller"].addr), size=7.5)
    pen.text(198, 15, title, size=12, bold=True, align="right")
    pen.text(198, 21, f"Ref. {d['ref']}", size=8.5, align="right")
    pen.text(198, 25.5, d_en(d["date"]), size=8, align="right")
    pen.lines(12, 34, ["Consignee: " + d["buyer"].name] + list(d["buyer"].addr), size=8, maxw=120)
    pen.text(12, 52, f"AWB/BL: {d['transport_ref']}", size=8)
    ul = UNIT_LABELS[lang if lang in UNIT_LABELS else "en"]
    rows = [[str(l.no), l.ref, l.desc, fmt_qty(l.qty, "en"), ul.get(l.unit, l.unit), fmt_kg(l.net, "en"),
             fmt_kg(l.gross, "en")] for l in d["lines"]]
    y = pen.table(12, 56, [("#", 8, "center"), ("Ref.", 26, "left"), ("Description", 70, "left"), ("Qty", 16, "right"),
                           ("Unit", 12, "center"), ("Net kg", 22, "right"), ("Gross kg", 22, "right")], rows,
                  size=7.5, row_h=5.2) + 5
    pen.lines(12, y, [f"Total packages: {d['packages']}", f"Total net weight: {fmt_kg(d['net'], 'en')} kg",
                      f"Total gross weight: {fmt_kg(d['gross'], 'en')} kg"], size=8.5, leading=4.6)


def render_cover_letter(pen: Pen, s, dm, variant):
    d = s.data
    pen.set_theme("serif")
    fw = dm.fw
    pen.text(12, 18, fw.name, size=12, bold=True)
    pen.lines(12, 23, list(dm.fw_party().addr), size=8)
    c = dm.entity
    pen.lines(120, 40, [c.name] + list(c.addr), size=9)
    pen.text(120, 60, f"{fw.city.split('-')[0]}, le {d_fr(d['date'])}", size=9)
    pen.text(12, 75, f"Objet : envoi de notre facture n° {d['ft_numero']}", size=9.5, bold=True)
    body = (f"Madame, Monsieur, veuillez trouver ci-joint notre facture n° {d['ft_numero']} relative au "
            f"dédouanement de votre envoi, accompagnée de la copie de la déclaration en douane et de nos conditions "
            f"générales. Le montant de cette facture est à régler à réception selon les conditions habituelles. "
            f"Nous restons à votre disposition pour toute question. Ce courrier est fictif et généré pour un "
            f"banc de test.")
    y = pen.paragraph(12, 86, body, 180, size=9.5, leading=5)
    pen.text(12, y + 12, "Le service facturation (FICTIF)", size=9.5)


def render_cg(pen: Pen, s, dm, variant):
    pen.set_theme("serif")
    pen.text(105, 14, "CONDITIONS GÉNÉRALES DE VENTE (FICTIVES)", size=11, bold=True, align="center")
    y = 24
    for i, para in enumerate(CG_TEXT):
        y = pen.paragraph(12, y, para, 186, size=8.4, leading=4.2) + 3
        if y > 265 and i < len(CG_TEXT) - 1:
            pen.new_page()
            pen.text(105, 14, "CONDITIONS GÉNÉRALES (suite)", size=10, bold=True, align="center")
            y = 24


def render_nx(pen: Pen, s, dm, variant):
    """Document intitulé facture mais non exploitable (P2)."""
    d = s.data
    ci = d["ci"]
    pen.set_theme("sans")
    pen.text(12, 15, ci.seller.name, size=11, bold=True, maxw=120)
    pen.lines(12, 20, list(ci.seller.addr), size=7.5)
    pen.text(198, 15, d["title"], size=12, bold=True, align="right", maxw=90)
    pen.text(198, 21, f"Ref. PRE-{ci.numero}", size=8.5, align="right")
    pen.text(198, 25.5, d_en(d["date"]), size=8, align="right")
    pen.lines(12, 34, ["To: " + ci.buyer.name] + list(ci.buyer.addr), size=8, maxw=120)
    kind = s.sous_type
    notes = {
        "pre_alerte": "Pre-alert: shipment ready for pick-up. Estimated departure and arrival below. "
                      "This is NOT a payable document - commercial invoice to follow.",
        "liste_expedition": "Shipping details only - no commercial value stated. Commercial invoice sent separately.",
        "devis": "Quotation valid 30 days. Prices indicative only, subject to confirmation. Not a request for payment.",
        "bon_commande": "Purchase order confirmation - goods to be invoiced upon shipment.",
        "bon_livraison_sans_valeur": "Bon de livraison - document sans valeur commerciale.",
    }[kind]
    pen.paragraph(12, 56, notes, 180, size=8.5, leading=4.3)
    rows = [[str(l.no), l.ref, l.desc, fmt_qty(l.qty, "en"), "" if kind != "devis" else "TBC"] for l in ci.lines]
    y = pen.table(12, 68, [("#", 8, "center"), ("Ref.", 28, "left"), ("Description", 92, "left"), ("Qty", 20, "right"),
                           ("Price", 28, "right")], rows, size=7.6, row_h=5.2) + 6
    pen.text(12, y, f"Packages: {ci.packages}   Gross weight: {fmt_kg(ci.gross_total, 'en')} kg   "
                    f"AWB/BL: {ci.transport_ref}", size=8)
