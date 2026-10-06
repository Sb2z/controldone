"""Fabriques de documents **fictifs** (PDF reportlab, tableur) pour les tests des extracteurs
« facture commerciale », « avoir » et « document support ».

Tous les noms, numéros et adresses sont inventés (FICTIF). Les numéros de TVA français ont une clé
valide calculée sur un SIREN fictif commençant par 000.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from dataclasses import dataclass, field

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from controldone.extract.base import ExtractionContext, ExtractionResult
from controldone.ids import IdGenerator
from controldone.ingest.pages import OptionsPages, extraire_pages
from controldone.model import Document, PageRef
from controldone.model.enums import TypeDocument
from controldone.normalize import tva_fr_depuis_siren

TVA_ACHETEUR = tva_fr_depuis_siren("000123459")
TVA_TRANSPORTEUR = tva_fr_depuis_siren("000555551")
TVA_DECLARANT = tva_fr_depuis_siren("000777772")

LARGEUR, HAUTEUR = A4


@dataclass
class Texte:
    x: float  # points depuis la gauche
    y: float  # points depuis le haut
    texte: str
    taille: float = 9
    droite: bool = False  # aligné à droite sur x
    gras: bool = False


@dataclass
class PagePdf:
    textes: list[Texte] = field(default_factory=list)

    def t(self, x: float, y: float, texte: str, **kw) -> PagePdf:
        self.textes.append(Texte(x, y, texte, **kw))
        return self

    def ligne(self, y: float, cellules: Sequence[tuple[float, str, bool]], taille: float = 9) -> PagePdf:
        """Ligne de tableau : (x, texte, aligné à droite)."""
        for x, texte, droite in cellules:
            self.textes.append(Texte(x, y, texte, taille=taille, droite=droite))
        return self


def pdf(pages: Sequence[PagePdf]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1)
    for p in pages:
        for t in p.textes:
            c.setFont("Helvetica-Bold" if t.gras else "Helvetica", t.taille)
            y = HAUTEUR - t.y
            if t.droite:
                c.drawRightString(t.x, y, t.texte)
            else:
                c.drawString(t.x, y, t.texte)
        c.drawString(200, 20, "DONNÉES FICTIVES — DOCUMENT DE TEST")
        c.showPage()
    c.save()
    return buf.getvalue()


def extraire(
    contenu: bytes,
    type_document: TypeDocument | str,
    *,
    mime: str = "application/pdf",
    sous_type: str | None = None,
    extracteur=None,
    pages: Sequence[int] | None = None,
) -> ExtractionResult:
    """Pages de l'ingestion (texte natif, sans OCR) -> extracteur déterministe du type."""
    from controldone.extract.deterministe import EXTRACTEURS_DETERMINISTES

    extraites = extraire_pages(contenu, type_mime=mime, options=OptionsPages(ocr=False, isoler=False))
    sel = [p for p in extraites if pages is None or p.page.numero in pages]
    td = TypeDocument(type_document)
    doc = Document(
        type=td,
        sous_type=sous_type,
        pages=[
            PageRef(fichier_id=p.page.fichier_id, numero=p.page.numero, qualite_texte=p.page.qualite_texte)
            for p in sel
        ],
    )
    ext = extracteur or EXTRACTEURS_DETERMINISTES[td.value]
    ctx = ExtractionContext(
        ids=IdGenerator.deterministe(7), options={"textes_pages": {p.page.numero: p.texte for p in sel}}
    )
    assert ext.supports(doc, [p.page for p in sel])
    return ext.extract(doc, [p.page for p in sel], ctx)


# --- factures commerciales -------------------------------------------------------------------------------

COLS_EN = [
    (42, "#", False),
    (60, "Item ref.", False),
    (125, "Description", False),
    (285, "HS code", False),
    (345, "Orig.", False),
    (405, "Qty", True),
    (412, "Unit", False),
    (500, "Unit price", True),
    (555, "Amount", True),
]


def facture_en(
    *,
    lignes=None,
    pied=None,
    total: str | None = "USD 12,540.00",
    devise_libelle: str | None = "USD",
    titre: str = "COMMERCIAL INVOICE",
) -> bytes:
    """Facture anglaise : vendeur (TVA GB), pavé acheteur (TVA FR), pavé « Notify / carrier » avec une
    autre TVA FR, tableau, pied (poids à gauche, totaux à droite)."""
    p = PagePdf()
    p.t(42, 40, "Thames Mock Supplies Ltd (FICTITIOUS)", taille=11, gras=True)
    p.t(42, 54, "Unit 0, Fictional Business Park, Sampleford")
    p.t(42, 66, "VAT No.: GB000000000   Tel: +44 0000 000000")
    p.t(330, 40, titre, taille=14, gras=True)
    p.t(42, 100, "Buyer / Bill to", gras=True)
    p.t(42, 112, "Lumen Industrie SAS (FICTIF)")
    p.t(42, 124, "18 rue Imaginaire, 69999 Villefictive")
    p.t(
        42,
        136,
        f"VAT No.: FR {TVA_ACHETEUR[2:4]} {TVA_ACHETEUR[4:7]} {TVA_ACHETEUR[7:10]} {TVA_ACHETEUR[10:]}",
    )
    p.t(330, 100, "Invoice No.:")
    p.t(420, 100, "INV-2026-0815")
    p.t(330, 112, "Invoice date:")
    p.t(420, 112, "Aug 14, 2026")
    p.t(330, 124, "B/L No.:")
    p.t(420, 124, "DEMO123456789")
    p.t(330, 136, "Incoterms:")
    p.t(420, 136, "FOB Felixstowe")
    if devise_libelle:
        p.t(330, 148, "Currency:")
        p.t(420, 148, devise_libelle)
    p.t(42, 172, "Notify party / Carrier", gras=True)
    p.t(42, 184, "Transporteur Démo Kilo (FICTIF)")
    p.t(42, 196, f"VAT: {TVA_TRANSPORTEUR}   SIREN 000555551   Tel 0102030405")
    p.ligne(230, COLS_EN)
    lignes = (
        lignes
        if lignes is not None
        else [
            ("1", "TH-7511-A", "Terry towel 50x100", "6302.60.00", "GB", "4,930", "pcs", "1.20", "5,916.00"),
            ("2", "TH-9029-B", "Fruit juice drink 1L", "2202 99 99", "GB", "1,000", "L", "2.50", "2,500.00"),
            ("3", "TH-6859-X", "Steel hex screws M8", "731815", "CN", "1,000", "kg", "3.124", "3,124.00"),
        ]
    )
    y = 248
    for ln in lignes:
        no, ref, desc, code, orig, qte, unite, pu, mt = ln
        p.ligne(
            y,
            [
                (42, no, False),
                (60, ref, False),
                (125, desc, False),
                (285, code, False),
                (345, orig, False),
                (405, qte, True),
                (412, unite, False),
                (500, pu, True),
                (555, mt, True),
            ],
        )
        y += 18
    y += 14
    p.t(42, y, "Total gross weight: 4,749.595 kg")
    p.t(42, y + 14, "Total net weight: 4,123.911 kg")
    p.t(42, y + 28, "Number of packages: 220 cartons")
    pied = (
        pied
        if pied is not None
        else [("Subtotal (goods)", "USD 11,540.00"), ("Freight", "USD 1,250.00"), ("Discount", "USD -250.00")]
    )
    yy = y
    for lib, val in pied:
        p.t(330, yy, lib)
        p.t(555, yy, val, droite=True)
        yy += 14
    if total is not None:
        p.t(330, yy, "TOTAL AMOUNT", gras=True)
        p.t(555, yy, total, droite=True, gras=True)
    p.t(42, yy + 50, "We hereby certify that this invoice is true and correct.")
    return pdf([p])


COLS_FR = [
    (42, "N°", False),
    (60, "Référence", False),
    (125, "Désignation", False),
    (285, "Code SH", False),
    (345, "Orig.", False),
    (405, "Qté", True),
    (412, "Unité", False),
    (500, "Prix unitaire", True),
    (555, "Montant", True),
]


def facture_fr_multipage() -> bytes:
    """Facture française sur deux pages : « 1 234,56 » (espace fine insécable), total de page, total
    pour la douane, poids imprimé à gauche du total."""
    nb = " "
    pages = []
    for k, rangees in enumerate(
        [
            [
                (
                    "1",
                    "GE-8754-B",
                    "Commutateur réseau",
                    "8517 62 00",
                    "CH",
                    f"1{nb}000",
                    "pce",
                    "59,90",
                    f"59{nb}900,00",
                )
            ],
            [
                (
                    "2",
                    "GE-8314-B",
                    "Moniteur LCD 27 pouces",
                    "8528 52",
                    "CH",
                    "32",
                    "pce",
                    "183,64",
                    f"5{nb}876,48",
                )
            ],
        ]
    ):
        p = PagePdf()
        p.t(42, 40, "Atelier Démo Léman SA (FICTIF)", taille=11, gras=True)
        p.t(330, 40, "FACTURE COMMERCIALE", taille=14, gras=True)
        if k == 0:
            p.t(42, 100, "Acheteur / Facturé à", gras=True)
            p.t(42, 112, "Maison Vellum Textile SAS (FICTIF)")
            p.t(42, 124, "5 quai de la Maquette, 59999 Roubaix-Fictif")
            p.t(42, 136, f"N° TVA : {TVA_ACHETEUR}")
        p.t(330, 100, "Facture n° :")
        p.t(420, 100, "00090/26")
        p.t(330, 112, "Date :")
        p.t(420, 112, "08/05/2026")
        p.t(330, 124, "Incoterm :")
        p.t(420, 124, "FCA Genève")
        p.t(330, 136, "Devise :")
        p.t(420, 136, "CHF")
        p.t(330, 148, f"Page : {k + 1}/2")
        p.ligne(180, COLS_FR)
        y = 198
        for no, ref, desc, code, orig, qte, unite, pu, mt in rangees:
            p.ligne(
                y,
                [
                    (42, no, False),
                    (60, ref, False),
                    (125, desc, False),
                    (285, code, False),
                    (345, orig, False),
                    (405, qte, True),
                    (412, unite, False),
                    (500, pu, True),
                    (555, mt, True),
                ],
            )
            y += 18
        if k == 0:
            p.t(330, y + 20, "Total de la page")
            p.t(555, y + 20, f"CHF 59{nb}900,00", droite=True)
        else:
            p.t(42, y + 20, f"Poids brut total : 1{nb}120,773 kg")
            p.t(42, y + 34, "Nombre de colis : 82 cartons")
            p.t(330, y + 20, "TOTAL À PAYER")
            p.t(555, y + 20, f"CHF 65{nb}776,48", droite=True)
            p.t(330, y + 34, "Valeur pour la douane")
            p.t(555, y + 34, f"CHF 65{nb}776,48", droite=True)
        pages.append(p)
    return pdf(pages)


def facture_es_jpy() -> bytes:
    """Factura española en JPY (sin decimales, separador de miles) ; total debajo de su etiqueta."""
    p = PagePdf()
    p.t(42, 40, "Osaka Dummy Precision K.K. (FICTITIOUS)", taille=11, gras=True)
    p.t(330, 40, "FACTURA COMERCIAL", taille=14, gras=True)
    p.t(42, 100, "Comprador / Facturar a", gras=True)
    p.t(42, 112, "Brindille Cosmétiques SAS (FICTIF)")
    p.t(42, 124, f"N.º IVA: {TVA_ACHETEUR}")
    p.t(330, 100, "Factura n.º:")
    p.t(420, 100, "SZ26000210")
    p.t(330, 112, "Fecha:")
    p.t(420, 112, "28 de enero de 2026")
    p.t(330, 124, "Incoterm:")
    p.t(420, 124, "CIF Marseille-Fos")
    p.t(330, 136, "Moneda:")
    p.t(420, 136, "JPY")
    p.ligne(
        170,
        [
            (42, "N.º", False),
            (60, "Referencia", False),
            (125, "Descripción", False),
            (285, "Partida", False),
            (345, "Orig.", False),
            (405, "Cant.", True),
            (412, "Ud.", False),
            (500, "Precio unit.", True),
            (555, "Importe", True),
        ],
    )
    p.ligne(
        188,
        [
            (42, "1", False),
            (60, "OS-5737-WH", False),
            (125, "Lámpara LED", False),
            (285, "9405 42 00", False),
            (345, "JP", False),
            (405, "46", True),
            (412, "uds", False),
            (500, "1,718", True),
            (555, "79,028", True),
        ],
    )
    p.ligne(
        206,
        [
            (42, "2", False),
            (60, "OS-7755-A", False),
            (125, "Bomba centrífuga", False),
            (285, "8413 70 21", False),
            (345, "JP", False),
            (405, "35", True),
            (412, "uds", False),
            (500, "12,812", True),
            (555, "448,420", True),
        ],
    )
    p.t(42, 240, "Peso bruto total: 48.750 kg")
    p.t(42, 254, "Número de bultos: 3 cajas")
    p.t(330, 240, "TOTAL", gras=True)
    p.t(555, 254, "JPY 527,448", droite=True, gras=True)
    return pdf([p])


# --- avoirs ---------------------------------------------------------------------------------------------------


def avoir_transitaire() -> bytes:
    p = PagePdf()
    p.t(160, 40, "Transitaire Démo Foxtrot Services (FICTIF)", taille=10, gras=True)
    p.t(500, 40, "AVOIR", taille=14, gras=True)
    p.t(160, 52, "15 avenue du Fret Imaginaire, 74999 Lille-Fictif")
    p.t(160, 64, "TVA FR81000179861")
    p.t(500, 64, "AV-2610035")
    p.t(42, 100, "Date")
    p.t(110, 100, "24/07/2026")
    p.t(42, 112, "Facture d'origine")
    p.t(130, 112, "FAC-2610035")
    p.t(42, 124, "MRN")
    p.t(110, 124, "26FRKQBPO7AS03MIMY")
    p.t(42, 136, "Motif")
    p.t(110, 136, "Geste commercial")
    p.t(320, 100, "Lumen Distribution SARL (FICTIF)")
    p.t(320, 112, "ZA du Banc d'Essai, 69998 Villefictive-Est")
    p.t(320, 124, f"TVA {TVA_ACHETEUR}")
    p.ligne(170, [(42, "Désignation", False), (250, "MRN", False), (470, "HT", True), (555, "TVA", True)])
    p.ligne(
        188,
        [
            (42, "Frais de dédouanement", False),
            (250, "26FRKQBPO7AS03MIMY", False),
            (470, "40,00", True),
            (555, "8,00", True),
        ],
    )
    p.t(330, 220, "Total HT crédité")
    p.t(555, 220, "40,00", droite=True)
    p.t(330, 234, "TVA")
    p.t(555, 234, "8,00", droite=True)
    p.t(330, 248, "Total TTC crédité")
    p.t(555, 248, "48,00", droite=True)
    return pdf([p])


def avoir_fournisseur() -> bytes:
    """« Credit note » d'un vendeur de marchandises : tableau d'articles, montants négatifs imprimés."""
    p = PagePdf()
    p.t(42, 40, "Hanoi Sample Garment JSC (FICTITIOUS)", taille=11, gras=True)
    p.t(330, 40, "CREDIT NOTE", taille=14, gras=True)
    p.t(42, 100, "Buyer / Bill to", gras=True)
    p.t(42, 112, "Lumen Distribution SARL (FICTIF)")
    p.t(42, 124, f"VAT No.: {TVA_ACHETEUR}")
    p.t(330, 100, "Credit note No.:")
    p.t(430, 100, "CN-2026-0042")
    p.t(330, 112, "Date:")
    p.t(430, 112, "Jun 30, 2026")
    p.t(330, 124, "Original invoice:")
    p.t(430, 124, "FAC/2026/0005-0")
    p.t(330, 136, "Currency:")
    p.t(430, 136, "USD")
    p.t(42, 150, "Reason: damaged goods")
    p.ligne(180, COLS_EN)
    p.ligne(
        198,
        [
            (42, "1", False),
            (60, "HA-5986-S", False),
            (125, "Cotton T-shirt", False),
            (285, "6109.10", False),
            (345, "VN", False),
            (405, "100", True),
            (412, "pcs", False),
            (500, "2.60", True),
            (555, "-260.00", True),
        ],
    )
    p.t(330, 230, "TOTAL CREDIT", gras=True)
    p.t(555, 230, "USD -260.00", droite=True, gras=True)
    return pdf([p])


# --- documents support ---------------------------------------------------------------------------------------


def lta() -> bytes:
    p = PagePdf()
    p.t(42, 40, "AIR WAYBILL (NOT NEGOTIABLE) - FICTIF", taille=12, gras=True)
    p.t(400, 40, "999-70166073", taille=12, gras=True)
    p.t(42, 80, "Shipper", gras=True)
    p.t(300, 80, "Consignee", gras=True)
    p.t(42, 92, "Pacific Sample Trading Inc. (FICTITIOUS)")
    p.t(300, 92, "Lumen Industrie SAS (FICTIF)")
    p.t(42, 104, "1200 Imaginary Blvd, Testville")
    p.t(300, 104, "18 rue Imaginaire, 69999 Villefictive")
    p.t(300, 116, f"VAT {TVA_ACHETEUR}")
    p.t(42, 150, "HAWB No.: HWB-0042-77")
    p.ligne(
        190,
        [
            (42, "AWB No.", False),
            (150, "Pieces", False),
            (230, "Gross weight (kg)", False),
            (350, "Chargeable weight (kg)", False),
            (480, "Date", False),
        ],
    )
    p.ligne(
        208,
        [
            (42, "999-70166073", False),
            (150, "13", False),
            (230, "258.806", False),
            (350, "312.500", False),
            (480, "Aug 13, 2026", False),
        ],
    )
    p.t(42, 240, "Nature and quantity of goods: as per commercial invoice. Freight charges: as agreed.")
    return pdf([p])


def liste_colisage() -> bytes:
    p = PagePdf()
    p.t(42, 40, "Izmir Ornek Tekstil A.S. (FICTITIOUS)", taille=11, gras=True)
    p.t(400, 40, "PACKING LIST", taille=14, gras=True)
    p.t(400, 56, "Ref. FAC/2026/0012-0")
    p.t(42, 90, "Consignee: Brindille Cosmétiques SAS (FICTIF)")
    p.t(42, 102, "7 chemin des Échantillons, 13999 Aix-Fictive")
    p.t(42, 130, "AWB/BL: DEMO307604768")
    p.ligne(
        160,
        [
            (42, "#", False),
            (60, "Ref.", False),
            (130, "Description", False),
            (330, "Qty", True),
            (340, "Unit", False),
            (440, "Net kg", True),
            (540, "Gross kg", True),
        ],
    )
    p.ligne(
        178,
        [
            (42, "1", False),
            (60, "IZ-3087-WH", False),
            (130, "Office chair", False),
            (330, "70", True),
            (340, "pcs", False),
            (440, "878.911", True),
            (540, "1,060.466", True),
        ],
    )
    p.ligne(
        196,
        [
            (42, "2", False),
            (60, "IZ-6842-X", False),
            (130, "Face cream 50ml", False),
            (330, "290", True),
            (340, "pcs", False),
            (440, "19.854", True),
            (540, "21.223", True),
        ],
    )
    p.t(42, 230, "Total packages: 329")
    p.t(42, 244, "Total net weight: 898.765 kg")
    p.t(42, 258, "Total gross weight: 1,081.689 kg")
    return pdf([p])


def lettre_accompagnement() -> bytes:
    p = PagePdf()
    p.t(42, 40, "Transitaire Démo Foxtrot Services (FICTIF)")
    p.t(330, 100, "Maison Vellum Textile SAS (FICTIF)")
    p.t(42, 160, "Objet : envoi de notre facture n° FAC-2610007")
    p.t(
        42,
        180,
        "Veuillez trouver ci-joint notre facture n° FAC-2610007 relative au dédouanement de votre envoi",
    )
    p.t(42, 192, "de 12 colis, poids brut 250,000 kg, LTA 999-12345675.")
    return pdf([p])
