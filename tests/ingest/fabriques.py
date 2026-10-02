"""Fabriques de documents **fictifs** pour les tests d'ingestion (PDF reportlab, XML, CSV, tableurs, e-mails).

Tous les noms, numéros et adresses sont inventés (marqués FICTIF).
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Sequence
from email.message import EmailMessage

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

TVA_CLIENT = "FR32000123459"  # TVA calculée sur un SIREN fictif commençant par 000


def pdf(pages: Sequence[Sequence[str]], *, titres: Sequence[str | None] | None = None,
        texte_blanc: str | None = None, invisible: str | None = None, metadonnees: dict | None = None,
        micro: str | None = None) -> bytes:
    """PDF natif : une page par liste de lignes ; ``titres[i]`` en grand corps en haut de page."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1)
    if metadonnees:
        c.setTitle(metadonnees.get("title", ""))
        c.setSubject(metadonnees.get("subject", ""))
        c.setKeywords(metadonnees.get("keywords", ""))
    for i, lignes in enumerate(pages):
        y = 800
        titre = titres[i] if titres and i < len(titres) else None
        if titre:
            c.setFont("Helvetica-Bold", 18)
            c.drawString(50, y, titre)
            y -= 34
        c.setFont("Helvetica", 10)
        for ligne in lignes:
            c.drawString(50, y, ligne)
            y -= 16
        if texte_blanc:
            c.setFillColorRGB(1, 1, 1)
            c.setFont("Helvetica-Bold", 18)
            c.drawString(50, 790 if not titre else 300, texte_blanc)
            c.setFillColorRGB(0, 0, 0)
        if invisible:
            t = c.beginText(50, 200)
            t.setFont("Helvetica-Bold", 20)
            t.setTextRenderMode(3)
            t.textLine(invisible)
            c.drawText(t)
        if micro:
            c.setFont("Helvetica", 1)
            c.drawString(50, 100, micro)
        c.showPage()
    c.save()
    return buf.getvalue()


def ajouter_xmp(contenu: bytes, xmp_texte: str) -> bytes:
    """Ajoute des métadonnées (dictionnaire Info + flux XMP) contenant ``xmp_texte``."""
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import DecodedStreamObject, NameObject

    r = PdfReader(io.BytesIO(contenu))
    w = PdfWriter()
    for p in r.pages:
        w.add_page(p)
    w.add_metadata({"/Subject": xmp_texte, "/Keywords": xmp_texte})
    xmp = (
        '<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?><x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description '
        f'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:description>{xmp_texte}</dc:description>'
        '</rdf:Description></rdf:RDF></x:xmpmeta><?xpacket end="w"?>'
    ).encode()
    flux = DecodedStreamObject()
    flux.set_data(xmp)
    flux.update({NameObject("/Type"): NameObject("/Metadata"), NameObject("/Subtype"): NameObject("/XML")})
    w._root_object[NameObject("/Metadata")] = w._add_object(flux)
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


def chiffrer(contenu: bytes, mot_de_passe: str = "secret") -> bytes:
    from pypdf import PdfReader, PdfWriter

    r = PdfReader(io.BytesIO(contenu))
    w = PdfWriter()
    for p in r.pages:
        w.add_page(p)
    w.encrypt(mot_de_passe)
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


def image_scan(contenu_pdf: bytes, *, page: int = 0, rotation: int = 0, inclinaison: float = 0.0,
               dpi: int = 200, fmt: str = "PNG") -> bytes:
    """« Scan » d'une page PDF : rendu en niveaux de gris, rotation et inclinaison simulées."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(contenu_pdf)
    try:
        im = doc[page].render(scale=dpi / 72).to_pil().convert("L")
    finally:
        doc.close()
    if rotation:
        im = im.rotate(rotation, expand=True, fillcolor=255)
    if inclinaison:
        im = im.rotate(inclinaison, expand=True, fillcolor=255)
    b = io.BytesIO()
    im.save(b, format=fmt, dpi=(dpi, dpi))
    return b.getvalue()


def tiff_multipage(images_png: Sequence[bytes]) -> bytes:
    from PIL import Image

    ims = [Image.open(io.BytesIO(b)) for b in images_png]
    b = io.BytesIO()
    ims[0].save(b, format="TIFF", save_all=True, append_images=ims[1:], dpi=(200, 200))
    return b.getvalue()


def pdf_depuis_images(images_png: Sequence[bytes]) -> bytes:
    from PIL import Image

    ims = [Image.open(io.BytesIO(b)).convert("RGB") for b in images_png]
    b = io.BytesIO()
    ims[0].save(b, format="PDF", save_all=True, append_images=ims[1:], resolution=200)
    return b.getvalue()


def zip_octets(entrees: dict[str, bytes], *, compression=zipfile.ZIP_DEFLATED) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", compression=compression) as z:
        for nom, data in entrees.items():
            z.writestr(nom, data)
    return b.getvalue()


def eml(*, expediteur: str, sujet: str, corps: str, pieces: dict[str, bytes] | None = None,
        message_id: str = "<fictif-001@exemple.invalid>") -> bytes:
    m = EmailMessage()
    m["From"] = expediteur
    m["To"] = "depot-fictif@controldone.invalid"
    m["Subject"] = sujet
    m["Message-ID"] = message_id
    m.set_content(corps)
    for nom, data in (pieces or {}).items():
        if nom.endswith(".pdf"):
            m.add_attachment(data, maintype="application", subtype="pdf", filename=nom)
        else:
            m.add_attachment(data, maintype="application", subtype="octet-stream", filename=nom)
    return bytes(m)


# --- documents types (texte) -------------------------------------------------------------------------------

FACTURE_COMMERCIALE = [
    "Invoice No: INV-2026-0815        Date: 14/08/2026",
    "Seller / Exporter: FICTIF ELECTRONICS CO LTD, 88 Fictive Road, Shenzhen, China",
    f"Buyer / Sold to: SOCIETE FICTIVE SAS, 1 rue Imaginaire, 75000 Paris  VAT {TVA_CLIENT}",
    "Incoterm: FOB Shanghai      Shipped via FICTIF EXPRESS (integrator)  AWB 176-12345675",
    "Item  Description            HS code     Origin  Qty   Unit price   Amount",
    "1     Laptop computer        8471.30     CN      10    1,254.00     12,540.00",
    "Total gross weight: 45.000 kg      Packages: 3",
    "TOTAL AMOUNT DUE  USD 12,540.00",
]

FACTURE_TRANSITAIRE = [
    "Facture N° FT-2026-00042          Date : 20/08/2026",
    "FICTIF TRANSIT SARL - commissionnaire en douane - TVA FR40000987651",
    f"Client : SOCIETE FICTIVE SAS - TVA {TVA_CLIENT}",
    "Dossier : LTA 176-12345675     MRN 26FR000000000001A1",
    "Libellé                                 Montant HT   TVA",
    "Droits de douane (débours)              313.50       0,00",
    "TVA import (débours)                    2 508,00     0,00",
    "Frais de dédouanement                   65,00        13,00",
    "Avance de fonds 2,5 %                   70,53        14,11",
    "Total HT 2 957,03   TVA 27,11   Total TTC 2 984,14",
]

DECLARATION = [
    "MRN : 26FR000000000001A1                 Date d'acceptation : 18/08/2026",
    f"Importateur : SOCIETE FICTIVE SAS  TVA {TVA_CLIENT}   EORI FR00012345900000",
    "Déclarant : FICTIF TRANSIT SARL   Bureau de douane : FR000999",
    "Régime : 4000   Montant total facturé : 12540,00 USD   Taux de change : 0,91234",
    "Article 1  Code marchandise 8471300000  Pays d'origine CN  Masse nette 40,000",
    "Type de taxe  Base d'imposition  Taux   Montant   Mode de paiement",
    "A00           11440,74            0,00   0,00      E",
    "B00           11754,24            20,00  2350,85   G",
]

AVOIR = [
    "Credit note No CN-2026-007      Date: 02/09/2026",
    "FICTIF TRANSIT SARL",
    "Reference invoice: FT-2026-00042",
    "Frais de dédouanement   65.00",
    "Total credited  78.00",
]

CONDITIONS_GENERALES = [
    "Article 1 - Objet. Les présentes conditions s'appliquent à toutes les prestations.",
    "Article 2 - Responsabilité. La responsabilité du commissionnaire est limitée.",
    "Article 3 - Paiement. Les factures sont payables à 30 jours.",
    "Article 4 - Juridiction. Tribunal de commerce de Fictiville.",
    "Article 5 - Force majeure.",
]

LETTRE = [
    "Objet : envoi de documents",
    "Madame, Monsieur,",
    "Veuillez trouver ci-joint notre facture ainsi que les documents de l'expédition.",
    "Nous restons à votre disposition.",
    "Cordialement,",
    "Service client FICTIF TRANSIT",
]

LTA = [
    "Shipper: FICTIF ELECTRONICS CO LTD",
    "Consignee: SOCIETE FICTIVE SAS",
    "AWB 176-12345675   Pieces 3   Gross weight 45.0 kg   Chargeable weight 52.0 kg",
]

PACKING_LIST = [
    "Invoice ref: INV-2026-0815",
    "Carton 1-3   Laptop computer   10 pcs   Gross weight 45.000 kg",
]

DEVIS = [
    "Devis N° DV-2026-12     Date : 01/07/2026",
    "Offre de prix valable 30 jours - ceci n'est pas une facture",
    "Laptop computer   10   1 254,00   12 540,00",
    "Total HT 12 540,00 EUR",
]


# --- XML de facture électronique ---------------------------------------------------------------------------

_NS_CII = (
    'xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100" '
    'xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100" '
    'xmlns:qdt="urn:un:unece:uncefact:data:standard:QualifiedDataType:100" '
    'xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100"'
)


def cii(*, numero="INV-2026-0815", type_code="380", devise="USD", lignes=None, vendeur="FICTIF ELECTRONICS CO LTD",
        tva_vendeur="CN000000000000001", acheteur="SOCIETE FICTIVE SAS", tva_acheteur=TVA_CLIENT,
        refs_doc: Sequence[str] = (), ref_origine: str | None = None, note: str | None = None,
        incoterm: str | None = "FOB") -> bytes:
    """CII D16B (profil EN 16931) minimal et valide au schéma. ``lignes`` : (libellé, qté, pu, montant, code SH,
    origine, taux TVA)."""
    lignes = lignes or [("Laptop computer", "10", "1254.00", "12540.00", "847130", "CN", "0")]
    xl = []
    total = sum(float(x[3]) for x in lignes)  # données de test seulement
    tva_total = sum(float(x[3]) * float(x[6]) / 100 for x in lignes)
    for i, (lib, q, pu, mt, sh, origine, taux) in enumerate(lignes, start=1):
        cls = f"<ram:DesignatedProductClassification><ram:ClassCode listID=\"HS\">{sh}</ram:ClassCode>" \
              f"</ram:DesignatedProductClassification>" if sh else ""
        orig = f"<ram:OriginTradeCountry><ram:ID>{origine}</ram:ID></ram:OriginTradeCountry>" if origine else ""
        cat = "S" if float(taux) > 0 else "Z"
        xl.append(
            f"<ram:IncludedSupplyChainTradeLineItem><ram:AssociatedDocumentLineDocument><ram:LineID>{i}</ram:LineID>"
            f"</ram:AssociatedDocumentLineDocument><ram:SpecifiedTradeProduct><ram:SellerAssignedID>REF{i}"
            f"</ram:SellerAssignedID><ram:Name>{lib}</ram:Name>{cls}{orig}</ram:SpecifiedTradeProduct>"
            f"<ram:SpecifiedLineTradeAgreement><ram:NetPriceProductTradePrice><ram:ChargeAmount>{pu}</ram:ChargeAmount>"
            f"</ram:NetPriceProductTradePrice></ram:SpecifiedLineTradeAgreement><ram:SpecifiedLineTradeDelivery>"
            f"<ram:BilledQuantity unitCode=\"C62\">{q}</ram:BilledQuantity></ram:SpecifiedLineTradeDelivery>"
            f"<ram:SpecifiedLineTradeSettlement><ram:ApplicableTradeTax><ram:TypeCode>VAT</ram:TypeCode>"
            f"<ram:CategoryCode>{cat}</ram:CategoryCode><ram:RateApplicablePercent>{taux}</ram:RateApplicablePercent>"
            f"</ram:ApplicableTradeTax><ram:SpecifiedTradeSettlementLineMonetarySummation><ram:LineTotalAmount>{mt}"
            f"</ram:LineTotalAmount></ram:SpecifiedTradeSettlementLineMonetarySummation>"
            f"</ram:SpecifiedLineTradeSettlement></ram:IncludedSupplyChainTradeLineItem>"
        )
    refs = "".join(f"<ram:AdditionalReferencedDocument><ram:IssuerAssignedID>{r}</ram:IssuerAssignedID>"
                   f"<ram:TypeCode>130</ram:TypeCode></ram:AdditionalReferencedDocument>" for r in refs_doc)
    inc = (f"<ram:ApplicableTradeDeliveryTerms><ram:DeliveryTypeCode>{incoterm}</ram:DeliveryTypeCode>"
           f"</ram:ApplicableTradeDeliveryTerms>") if incoterm else ""
    origine = (f"<ram:InvoiceReferencedDocument><ram:IssuerAssignedID>{ref_origine}</ram:IssuerAssignedID>"
               f"</ram:InvoiceReferencedDocument>") if ref_origine else ""
    note_x = f"<ram:IncludedNote><ram:Content>{note}</ram:Content></ram:IncludedNote>" if note else ""
    taxes = {}
    for x in lignes:
        taxes.setdefault(x[6], 0.0)
        taxes[x[6]] += float(x[3])
    tax_x = "".join(
        f"<ram:ApplicableTradeTax><ram:CalculatedAmount>{b * float(t) / 100:.2f}</ram:CalculatedAmount>"
        f"<ram:TypeCode>VAT</ram:TypeCode>{'<ram:ExemptionReason>Débours</ram:ExemptionReason>' if float(t) == 0 else ''}"
        f"<ram:BasisAmount>{b:.2f}</ram:BasisAmount><ram:CategoryCode>{'S' if float(t) > 0 else 'Z'}"
        f"</ram:CategoryCode><ram:RateApplicablePercent>{t}</ram:RateApplicablePercent></ram:ApplicableTradeTax>"
        for t, b in sorted(taxes.items()))
    return (
        f'<?xml version="1.0" encoding="UTF-8"?><rsm:CrossIndustryInvoice {_NS_CII}>'
        "<rsm:ExchangedDocumentContext><ram:GuidelineSpecifiedDocumentContextParameter><ram:ID>urn:cen.eu:en16931:2017#conformant#urn:factur-x.eu:1p0:extended"
        "</ram:ID></ram:GuidelineSpecifiedDocumentContextParameter></rsm:ExchangedDocumentContext>"
        f"<rsm:ExchangedDocument><ram:ID>{numero}</ram:ID><ram:TypeCode>{type_code}</ram:TypeCode><ram:IssueDateTime>"
        f'<udt:DateTimeString format="102">20260814</udt:DateTimeString></ram:IssueDateTime>{note_x}'
        "</rsm:ExchangedDocument>"
        f"<rsm:SupplyChainTradeTransaction>{''.join(xl)}<ram:ApplicableHeaderTradeAgreement>"
        f"<ram:SellerTradeParty><ram:Name>{vendeur}</ram:Name><ram:PostalTradeAddress><ram:LineOne>88 Fictive Road"
        "</ram:LineOne><ram:CountryID>CN</ram:CountryID></ram:PostalTradeAddress><ram:SpecifiedTaxRegistration>"
        f'<ram:ID schemeID="VA">{tva_vendeur}</ram:ID></ram:SpecifiedTaxRegistration></ram:SellerTradeParty>'
        f"<ram:BuyerTradeParty><ram:Name>{acheteur}</ram:Name><ram:PostalTradeAddress><ram:LineOne>1 rue Imaginaire"
        "</ram:LineOne><ram:CountryID>FR</ram:CountryID></ram:PostalTradeAddress><ram:SpecifiedTaxRegistration>"
        f'<ram:ID schemeID="VA">{tva_acheteur}</ram:ID></ram:SpecifiedTaxRegistration></ram:BuyerTradeParty>'
        f"{inc}{refs}</ram:ApplicableHeaderTradeAgreement><ram:ApplicableHeaderTradeDelivery/>"
        f"<ram:ApplicableHeaderTradeSettlement><ram:InvoiceCurrencyCode>{devise}</ram:InvoiceCurrencyCode>"
        f"{tax_x}<ram:SpecifiedTradeSettlementHeaderMonetarySummation><ram:LineTotalAmount>{total:.2f}"
        f"</ram:LineTotalAmount><ram:TaxBasisTotalAmount>{total:.2f}</ram:TaxBasisTotalAmount>"
        f'<ram:TaxTotalAmount currencyID="{devise}">{tva_total:.2f}</ram:TaxTotalAmount>'
        f"<ram:GrandTotalAmount>{total + tva_total:.2f}</ram:GrandTotalAmount><ram:DuePayableAmount>"
        f"{total + tva_total:.2f}</ram:DuePayableAmount></ram:SpecifiedTradeSettlementHeaderMonetarySummation>"
        f"{origine}</ram:ApplicableHeaderTradeSettlement></rsm:SupplyChainTradeTransaction></rsm:CrossIndustryInvoice>"
    ).encode()


def ubl(*, avoir: bool = False, numero="UBL-2026-001", devise="EUR", lignes=None, ref_origine: str | None = None,
        note: str | None = None) -> bytes:
    """UBL 2.1 Invoice ou CreditNote minimal et valide au schéma. ``lignes`` : (libellé, qté, montant, code SH, origine)."""
    lignes = lignes or [("Laptop computer", "10", "12540.00", "847130", "CN")]
    racine = "CreditNote" if avoir else "Invoice"
    ns = f"urn:oasis:names:specification:ubl:schema:xsd:{racine}-2"
    qte = "CreditedQuantity" if avoir else "InvoicedQuantity"
    ligne_tag = "CreditNoteLine" if avoir else "InvoiceLine"
    total = sum(float(x[2]) for x in lignes)
    xl = []
    for i, (lib, q, mt, sh, origine) in enumerate(lignes, start=1):
        cls = (f"<cac:CommodityClassification><cbc:ItemClassificationCode listID=\"HS\">{sh}</cbc:ItemClassificationCode>"
               f"</cac:CommodityClassification>") if sh else ""
        orig = f"<cac:OriginCountry><cbc:IdentificationCode>{origine}</cbc:IdentificationCode></cac:OriginCountry>" \
            if origine else ""
        xl.append(
            f"<cac:{ligne_tag}><cbc:ID>{i}</cbc:ID><cbc:{qte} unitCode=\"C62\">{q}</cbc:{qte}>"
            f"<cbc:LineExtensionAmount currencyID=\"{devise}\">{mt}</cbc:LineExtensionAmount><cac:Item><cbc:Name>{lib}"
            f"</cbc:Name>{orig}{cls}<cac:ClassifiedTaxCategory><cbc:ID>Z</cbc:ID><cbc:Percent>0</cbc:Percent>"
            "<cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:ClassifiedTaxCategory></cac:Item>"
            f"<cac:Price><cbc:PriceAmount currencyID=\"{devise}\">{float(mt) / float(q):.2f}</cbc:PriceAmount>"
            f"</cac:Price></cac:{ligne_tag}>"
        )
    type_code = "" if avoir else "<cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>"
    note_x = f"<cbc:Note>{note}</cbc:Note>" if note else ""
    bill = (f"<cac:BillingReference><cac:InvoiceDocumentReference><cbc:ID>{ref_origine}</cbc:ID>"
            "</cac:InvoiceDocumentReference></cac:BillingReference>") if ref_origine else ""

    def partie(nom, tva):
        return (f"<cac:Party><cac:PartyName><cbc:Name>{nom}</cbc:Name></cac:PartyName><cac:PostalAddress>"
                "<cbc:StreetName>Rue Fictive</cbc:StreetName><cac:Country><cbc:IdentificationCode>FR"
                "</cbc:IdentificationCode></cac:Country></cac:PostalAddress><cac:PartyTaxScheme><cbc:CompanyID>"
                f"{tva}</cbc:CompanyID><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:PartyTaxScheme>"
                f"<cac:PartyLegalEntity><cbc:RegistrationName>{nom}</cbc:RegistrationName></cac:PartyLegalEntity>"
                "</cac:Party>")

    return (
        f'<?xml version="1.0" encoding="UTF-8"?><{racine} xmlns="{ns}" '
        'xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2" '
        'xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">'
        f"<cbc:ID>{numero}</cbc:ID><cbc:IssueDate>2026-08-14</cbc:IssueDate>{type_code}{note_x}"
        f"<cbc:DocumentCurrencyCode>{devise}</cbc:DocumentCurrencyCode>{bill}"
        f"<cac:AccountingSupplierParty>{partie('FICTIF ELECTRONICS CO LTD', 'CN000000000000001')}"
        f"</cac:AccountingSupplierParty><cac:AccountingCustomerParty>{partie('SOCIETE FICTIVE SAS', TVA_CLIENT)}"
        "</cac:AccountingCustomerParty>"
        f"<cac:TaxTotal><cbc:TaxAmount currencyID=\"{devise}\">0.00</cbc:TaxAmount></cac:TaxTotal>"
        f"<cac:LegalMonetaryTotal><cbc:LineExtensionAmount currencyID=\"{devise}\">{total:.2f}</cbc:LineExtensionAmount>"
        f"<cbc:TaxExclusiveAmount currencyID=\"{devise}\">{total:.2f}</cbc:TaxExclusiveAmount>"
        f"<cbc:TaxInclusiveAmount currencyID=\"{devise}\">{total:.2f}</cbc:TaxInclusiveAmount>"
        f"<cbc:PayableAmount currencyID=\"{devise}\">{total:.2f}</cbc:PayableAmount></cac:LegalMonetaryTotal>"
        f"{''.join(xl)}</{racine}>"
    ).encode()


def facturx_pdf(xml: bytes, lignes_visuelles: Sequence[str] = FACTURE_COMMERCIALE) -> bytes:
    from facturx import generate_from_binary

    base = pdf([lignes_visuelles], titres=["COMMERCIAL INVOICE"])
    return generate_from_binary(base, xml, check_xsd=False)
