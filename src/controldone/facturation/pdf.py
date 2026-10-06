"""PDF visuel d'une facture (ReportLab) et assemblage Factur-X (PDF/A-3 + XML CII embarqué).

Les polices TrueType (DejaVu Sans, licence libre) sont **embarquées** quand elles sont présentes sur le
système (exigence PDF/A) ; à défaut, Helvetica (non embarquée : le PDF reste lisible mais n'est pas
strictement PDF/A — à vérifier avec veraPDF avant la mise en production, voir ``docs/FACTURATION.md``).
"""

from __future__ import annotations

import io
from decimal import Decimal
from pathlib import Path

from controldone.facturation.modele import Facture, mentions_obligatoires
from controldone.formatage import format_montant

__all__ = ["assembler_facturx", "rendre_pdf"]

_POLICES = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
)


def _polices() -> tuple[str, str]:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    if all(p.exists() for p in _POLICES):
        if "CD-Sans" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("CD-Sans", str(_POLICES[0])))
            pdfmetrics.registerFont(TTFont("CD-Sans-Gras", str(_POLICES[1])))
        return "CD-Sans", "CD-Sans-Gras"
    return "Helvetica", "Helvetica-Bold"


def _eur(x: Decimal) -> str:
    return format_montant(Decimal(x), "EUR")


def _date(d: object) -> str:
    return d.strftime("%d/%m/%Y") if d else "—"  # type: ignore[attr-defined]


def rendre_pdf(f: Facture, *, non_valable: bool = False) -> bytes:
    """PDF lisible de la facture (une page A4 en général). ``non_valable`` : bandeau « NON VALABLE »
    (identité du vendeur incomplète)."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    normal, gras = _polices()
    st = ParagraphStyle("n", fontName=normal, fontSize=9, leading=12)
    st_g = ParagraphStyle("g", parent=st, fontName=gras)
    st_titre = ParagraphStyle("t", parent=st, fontName=gras, fontSize=15, leading=19)
    st_petit = ParagraphStyle("p", parent=st, fontSize=7.5, leading=10)
    st_alerte = ParagraphStyle("a", parent=st_g, textColor=colors.HexColor("#b00020"), fontSize=10)

    def P(texte: str, style: ParagraphStyle = st) -> Paragraph:
        from xml.sax.saxutils import escape

        return Paragraph(escape(texte).replace("\n", "<br/>"), style)

    tampon = io.BytesIO()
    titre = "AVOIR" if f.est_avoir else "FACTURE"
    doc = SimpleDocTemplate(
        tampon,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"{titre} {f.numero}",
        author=f.vendeur.raison_sociale,
        subject=f"{titre} {f.numero}",
        creator="ControlDOne",
    )
    v, a = f.vendeur, f.acheteur
    elems: list[object] = []
    if non_valable:
        elems += [
            P("DOCUMENT NON VALABLE : identité du vendeur à compléter (champs « À COMPLÉTER »).", st_alerte),
            Spacer(1, 3 * mm),
        ]
    elems += [
        P(f"{titre} n° {f.numero}", st_titre),
        Spacer(1, 2 * mm),
        P(
            f"Date d'émission : {_date(f.date_emission)}"
            + (f" — Échéance : {_date(f.date_echeance)}" if not f.est_avoir else "")
            + (f" — Date de la prestation : {_date(f.date_prestation)}" if f.date_prestation else "")
        ),
        Spacer(1, 4 * mm),
    ]
    vendeur_txt = (
        f"{v.raison_sociale}\n{v.forme_juridique}\n{v.adresse_ligne}\n{v.code_postal} {v.ville}\n"
        f"SIREN {v.siren} — {v.rcs}\n"
        + (f"N° TVA intracommunautaire : {v.tva_intracom}\n" if f.tva.tva_applicable else "")
        + f"{v.email}"
    )
    acheteur_txt = (
        f"{a.raison_sociale}\n{a.adresse_ligne}\n{a.code_postal} {a.ville}\n"
        f"SIREN {a.siren or '—'}" + (f"\nN° TVA : {a.tva_intracom}" if a.tva_intracom else "")
    )
    if a.adresse_livraison_differente:
        acheteur_txt += (
            f"\nAdresse de livraison : {a.livraison_ligne}, {a.livraison_code_postal} {a.livraison_ville}"
        ).rstrip()
    t = Table(
        [[P("Émetteur", st_g), P("Client", st_g)], [P(vendeur_txt), P(acheteur_txt)]],
        colWidths=[87 * mm, 87 * mm],
    )
    t.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 1), (0, 1), 0.5, colors.grey),
                ("BOX", (1, 1), (1, 1), 0.5, colors.grey),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 6),
            ]
        )
    )
    elems += [t, Spacer(1, 4 * mm)]
    if f.objet:
        elems += [P(f"Objet : {f.objet}"), Spacer(1, 2 * mm)]
    if f.facture_origine:
        elems += [
            P(f"Avoir se rapportant à la facture n° {f.facture_origine} du {_date(f.date_facture_origine)}."),
            Spacer(1, 2 * mm),
        ]
    lignes = [[P("Désignation", st_g), P("Qté", st_g), P("PU HT", st_g), P("Montant HT", st_g)]]
    for x in f.lignes:
        lignes.append(
            [
                P(x.libelle),
                P(f"{Decimal(x.quantite).normalize():f}"),
                P(_eur(x.prix_unitaire_ht)),
                P(_eur(x.montant_ht)),
            ]
        )
    for r in f.remises:
        lignes.append([P(f"Remise : {r.libelle}"), P(""), P(""), P("− " + _eur(r.montant))])
    tl = Table(lignes, colWidths=[104 * mm, 14 * mm, 28 * mm, 28 * mm], repeatRows=1)
    tl.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.black),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("LINEBELOW", (0, -1), (-1, -1), 0.3, colors.grey),
            ]
        )
    )
    elems += [tl, Spacer(1, 3 * mm)]
    lib_tva = f"TVA {Decimal(f.taux_tva).normalize():f} %" if f.tva.tva_applicable else "TVA"
    totaux = [["Total HT", _eur(f.base_ht)], [lib_tva, _eur(f.montant_tva)], ["Total TTC", _eur(f.total_ttc)]]
    if f.deja_paye:
        totaux.append(["Déjà payé", _eur(f.deja_paye)])
    totaux.append(["Net à payer" if not f.est_avoir else "Montant de l'avoir", _eur(f.net_a_payer)])
    tt = Table([[P(k, st_g), P(val)] for k, val in totaux], colWidths=[40 * mm, 30 * mm], hAlign="RIGHT")
    tt.setStyle(
        TableStyle([("ALIGN", (1, 0), (1, -1), "RIGHT"), ("LINEABOVE", (0, -1), (-1, -1), 0.6, colors.black)])
    )
    elems += [tt, Spacer(1, 5 * mm)]
    m = mentions_obligatoires(f)
    conditions = [m["CAT"]]
    if "TXD" in m:
        conditions.append(m["TXD"])
    if not f.est_avoir:
        conditions += [
            f"Conditions de paiement : à {f.paiement.delai_jours} jours, au plus tard le "
            f"{_date(f.date_echeance)}. {f.paiement.moyen}".strip()
        ]
        if v.iban:
            conditions.append(f"IBAN : {v.iban} — BIC : {v.bic}")
        if f.reference_paiement:
            conditions.append(f"Référence de paiement : {f.reference_paiement}")
    conditions += [m["PMD"], m["PMT"], m["AAB"]]
    conditions += list(f.notes)
    for c in conditions:
        if c:
            elems.append(P(c, st_petit))
    elems += [Spacer(1, 3 * mm), P(m["REG"], st_petit)]
    doc.build(elems)
    return tampon.getvalue()


def assembler_facturx(pdf: bytes, xml: bytes, *, numero: str, vendeur: str, titre: str = "Facture") -> bytes:
    """Embarque le XML CII dans le PDF (``factur-x.xml``, PDF/A-3, profil EN 16931) ; XSD vérifié."""
    import facturx

    meta = {
        "author": vendeur,
        "keywords": "Factur-X, facture",
        "title": f"{titre} {numero}",
        "subject": f"{titre} {numero}",
    }
    return facturx.generate_from_binary(
        pdf, xml, flavor="factur-x", level="en16931", check_xsd=True, pdf_metadata=meta, lang="fr-FR"
    )
