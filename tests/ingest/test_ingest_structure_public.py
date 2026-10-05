"""Écarts trouvés sur le corpus public de factures électroniques (``scripts/corpus_public.py``, D-1500 à D-1508).

Chaque cas est reproduit par un XML minimal écrit à la main (données FICTIVES) : aucun fichier tiers n'est copié.
"""

from __future__ import annotations

import io

import fabriques as fab
from lxml import etree
from pypdf import PdfReader, PdfWriter

from controldone.extract.base import ExtractionContext
from controldone.ids import IdGenerator
from controldone.ingest import (
    ExtracteurFactureXML,
    FicheCorrespondance,
    OptionsPages,
    analyser_contenu_structure,
    decouper_fichier,
    detecter_type,
    recevoir_octets,
    xml_facturx,
)
from controldone.ingest.sniff import MIME_CSV, MIME_XML
from controldone.ingest.structure import _chemin_xpath, piece_xml_facture
from controldone.model import Document
from controldone.model.enums import MotifNonExploitable, SigneImprime, TypeDocument, TypeSousTotal

LOCAL = OptionsPages(isoler=False)


def _extraire(contenu: bytes, nom: str):
    rec = recevoir_octets([(nom, contenu)])
    fr = rec.fichiers[0]
    r = decouper_fichier(fr.fichier, fr.contenu, options=LOCAL, fiches=())
    doc = r.documents[0]
    ctx = ExtractionContext(contenu_fichier=fr.contenu, type_mime=fr.fichier.type_mime, ids=IdGenerator.deterministe(3))
    return doc, ExtracteurFactureXML().extract(doc, r.pages, ctx)


# --- ZUGFeRD 1.0 ---------------------------------------------------------------------------------------------


def zf1(*, total: str = "134.00", ligne: str = "100.00", logistique: str | None = "15.00", extra: str = "") -> bytes:
    """ZUGFeRD 1.0 COMFORT minimal, valide au schéma ZUGFeRD 1.0 (données fictives)."""
    log = (f'<ram:SpecifiedLogisticsServiceCharge><ram:Description>Transportkosten FICTIF</ram:Description>'
           f'<ram:AppliedAmount currencyID="EUR">{logistique}</ram:AppliedAmount></ram:SpecifiedLogisticsServiceCharge>'
           ) if logistique else ""
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryDocument xmlns:rsm="urn:ferd:CrossIndustryDocument:invoice:1p0"
 xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:12"
 xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:15">
<rsm:SpecifiedExchangedDocumentContext><ram:GuidelineSpecifiedDocumentContextParameter>
<ram:ID>urn:ferd:CrossIndustryDocument:invoice:1p0:comfort</ram:ID></ram:GuidelineSpecifiedDocumentContextParameter>
</rsm:SpecifiedExchangedDocumentContext>
<rsm:HeaderExchangedDocument>{extra}<ram:ID>ZF1-FICTIF-7</ram:ID><ram:Name>RECHNUNG</ram:Name>
<ram:TypeCode>380</ram:TypeCode><ram:IssueDateTime><udt:DateTimeString format="102">20260301</udt:DateTimeString>
</ram:IssueDateTime></rsm:HeaderExchangedDocument>
<rsm:SpecifiedSupplyChainTradeTransaction>
<ram:ApplicableSupplyChainTradeAgreement>
<ram:SellerTradeParty><ram:Name>FICTIF LIEFERANT GMBH</ram:Name><ram:PostalTradeAddress>
<ram:LineOne>Fiktivstrasse 1</ram:LineOne><ram:CountryID>DE</ram:CountryID></ram:PostalTradeAddress>
<ram:SpecifiedTaxRegistration><ram:ID schemeID="FC">201/113/40209</ram:ID></ram:SpecifiedTaxRegistration>
<ram:SpecifiedTaxRegistration><ram:ID schemeID="VA">DE000000001</ram:ID></ram:SpecifiedTaxRegistration>
</ram:SellerTradeParty>
<ram:BuyerTradeParty><ram:Name>SOCIETE FICTIVE SAS</ram:Name></ram:BuyerTradeParty>
</ram:ApplicableSupplyChainTradeAgreement>
<ram:ApplicableSupplyChainTradeDelivery/>
<ram:ApplicableSupplyChainTradeSettlement>
<ram:InvoiceCurrencyCode>EUR</ram:InvoiceCurrencyCode>
<ram:ApplicableTradeTax><ram:CalculatedAmount currencyID="EUR">19.00</ram:CalculatedAmount><ram:TypeCode>VAT</ram:TypeCode>
<ram:BasisAmount currencyID="EUR">100.00</ram:BasisAmount><ram:CategoryCode>S</ram:CategoryCode>
<ram:ApplicablePercent>19.00</ram:ApplicablePercent></ram:ApplicableTradeTax>
{log}
<ram:SpecifiedTradeSettlementMonetarySummation><ram:LineTotalAmount currencyID="EUR">{ligne}</ram:LineTotalAmount>
<ram:ChargeTotalAmount currencyID="EUR">0.00</ram:ChargeTotalAmount>
<ram:AllowanceTotalAmount currencyID="EUR">0.00</ram:AllowanceTotalAmount>
<ram:TaxBasisTotalAmount currencyID="EUR">100.00</ram:TaxBasisTotalAmount>
<ram:TaxTotalAmount currencyID="EUR">19.00</ram:TaxTotalAmount>
<ram:GrandTotalAmount currencyID="EUR">{total}</ram:GrandTotalAmount>
<ram:DuePayableAmount currencyID="EUR">{total}</ram:DuePayableAmount></ram:SpecifiedTradeSettlementMonetarySummation>
</ram:ApplicableSupplyChainTradeSettlement>
<ram:IncludedSupplyChainTradeLineItem><ram:AssociatedDocumentLineDocument><ram:LineID>1</ram:LineID>
</ram:AssociatedDocumentLineDocument><ram:SpecifiedSupplyChainTradeAgreement><ram:NetPriceProductTradePrice>
<ram:ChargeAmount currencyID="EUR">10.00</ram:ChargeAmount></ram:NetPriceProductTradePrice>
</ram:SpecifiedSupplyChainTradeAgreement><ram:SpecifiedSupplyChainTradeDelivery>
<ram:BilledQuantity unitCode="C62">10</ram:BilledQuantity></ram:SpecifiedSupplyChainTradeDelivery>
<ram:SpecifiedSupplyChainTradeSettlement><ram:ApplicableTradeTax><ram:TypeCode>VAT</ram:TypeCode>
<ram:CategoryCode>S</ram:CategoryCode><ram:ApplicablePercent>19.00</ram:ApplicablePercent></ram:ApplicableTradeTax>
<ram:SpecifiedTradeSettlementMonetarySummation><ram:LineTotalAmount currencyID="EUR">{ligne}</ram:LineTotalAmount>
</ram:SpecifiedTradeSettlementMonetarySummation></ram:SpecifiedSupplyChainTradeSettlement>
<ram:SpecifiedTradeProduct><ram:SellerAssignedID>ART-1</ram:SellerAssignedID><ram:Name>Article fictif</ram:Name>
</ram:SpecifiedTradeProduct></ram:IncludedSupplyChainTradeLineItem>
</rsm:SpecifiedSupplyChainTradeTransaction>
</rsm:CrossIndustryDocument>'''.encode()


def test_zugferd1_lu_et_valide_au_schema():
    info = analyser_contenu_structure(zf1(), MIME_XML, fiches=())
    assert info is not None and info.format == "zugferd1" and info.schema_valide
    assert info.type is TypeDocument.facture_commerciale
    _doc, res = _extraire(zf1(), "rechnung.xml")
    c = res.champs
    assert c.numero.valeur == "ZF1-FICTIF-7" and c.date.valeur == "2026-03-01" and c.devise.valeur == "EUR"
    assert c.total_facture.valeur == "134.00" and c.vendeur.tva.valeur == "DE000000001"  # schéma VA, pas FC
    assert len(c.lignes) == 1 and c.lignes[0].montant_ligne.valeur == "100.00"
    assert c.lignes[0].quantite.unite == "C62"
    # frais logistiques : un frais de transport, pas une remise
    assert [(s.type, s.montant.valeur) for s in c.sous_totaux] == [(TypeSousTotal.fret, "15.00")]
    assert all(v.confiance == 1.0 for v in res.valeurs if v.valeur is not None)
    assert c.numero.texte_contexte == "/CrossIndustryDocument/HeaderExchangedDocument/ID"


def test_zugferd1_non_valide_confiance_095():
    xml = zf1(extra="<ram:Inconnu/>")
    info = analyser_contenu_structure(xml, MIME_XML, fiches=())
    assert info is not None and not info.schema_valide
    _doc, res = _extraire(xml, "rechnung.xml")
    assert "schema_non_valide" in res.avertissements
    assert all(v.confiance == 0.95 for v in res.valeurs if v.valeur is not None)


# --- pièce jointe XML d'un PDF hybride -------------------------------------------------------------------------


def _pdf_avec_pieces(pieces: list[tuple[str, bytes]]) -> bytes:
    w = PdfWriter(clone_from=PdfReader(io.BytesIO(fab.pdf([["RECHNUNG FICTIF"]]))))
    for nom, data in pieces:
        w.add_attachment(nom, data)
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


def test_pdf_hybride_noms_de_piece_jointe():
    xml = fab.cii()
    for nom in ("xrechnung.xml", "ZUGFeRD-invoice.xml", "zugferd-invoice.xml", "factur-x.xml", "facture.xml"):
        pdf = _pdf_avec_pieces([("notes.xml", b"<notes><n>FICTIF</n></notes>"), (nom, xml)])
        assert piece_xml_facture(pdf) == (nom, xml), nom
        info = analyser_contenu_structure(pdf, "application/pdf", fiches=())
        assert info is not None and info.format == "facturx" and info.type is TypeDocument.facture_commerciale
    # préférence : factur-x.xml avant un autre XML de facture
    pdf = _pdf_avec_pieces([("autre.xml", fab.ubl()), ("factur-x.xml", xml)])
    assert piece_xml_facture(pdf)[0] == "factur-x.xml"
    # aucune facture jointe : pas de XML
    assert xml_facturx(_pdf_avec_pieces([("notes.xml", b"<notes/>")])) is None


def test_pdf_zugferd1_embarque_extrait():
    pdf = _pdf_avec_pieces([("ZUGFeRD-invoice.xml", zf1())])
    _doc, res = _extraire(pdf, "rechnung.pdf")
    assert res.champs is not None and res.champs.total_facture.valeur == "134.00"


# --- totaux, TVA, signes -------------------------------------------------------------------------------------


def test_tva_totale_dans_la_devise_de_facture_cii():
    """BT-110 (devise de facture) et non BT-111 (devise de comptabilisation), quel que soit l'ordre."""
    xml = fab.cii(type_code="381", devise="USD", incoterm=None,
                  lignes=[("Frais de dédouanement", "1", "100.00", "100.00", None, None, "20")])
    xml = xml.replace(b'<ram:TaxTotalAmount currencyID="USD">',
                      b'<ram:TaxTotalAmount currencyID="EUR">18.40</ram:TaxTotalAmount>'
                      b'<ram:TaxTotalAmount currencyID="USD">')
    _doc, res = _extraire(xml, "av.xml")
    assert res.champs.total_tva.valeur == "20.00" and res.champs.total_tva.unite == "USD"


def test_ubl_tva_totale_et_schema_vat():
    xml = fab.ubl(avoir=True, devise="USD", lignes=[("Frais de dédouanement", "1", "65.00", None, None)])
    # BT-111 placé avant BT-110 ; immatriculation fiscale (schéma FC) avant le numéro de TVA
    xml = xml.replace(b'<cac:TaxTotal><cbc:TaxAmount currencyID="USD">0.00',
                      b'<cac:TaxTotal><cbc:TaxAmount currencyID="EUR">9.99</cbc:TaxAmount></cac:TaxTotal>'
                      b'<cac:TaxTotal><cbc:TaxAmount currencyID="USD">0.00')
    xml = xml.replace(b"<cac:PartyTaxScheme><cbc:CompanyID>CN000000000000001",
                      b"<cac:PartyTaxScheme><cbc:CompanyID>FICTIF-123</cbc:CompanyID><cac:TaxScheme><cbc:ID>FC"
                      b"</cbc:ID></cac:TaxScheme></cac:PartyTaxScheme><cac:PartyTaxScheme><cbc:CompanyID>"
                      b"DE000000001")
    _doc, res = _extraire(xml, "cn.xml")
    assert res.champs.total_tva.valeur == "0.00" and res.champs.total_tva.unite == "USD"
    assert res.champs.emetteur.tva.valeur == "DE000000001"


def test_facture_380_a_total_negatif_classee_avoir():
    xml = fab.cii(devise="EUR", lignes=[("Article fictif", "-2", "50.00", "-100.00", "847130", "CN", "0")])
    info = analyser_contenu_structure(xml, MIME_XML, fiches=())
    assert info is not None and info.type is TypeDocument.avoir
    doc, res = _extraire(xml, "f.xml")
    assert doc.type is TypeDocument.avoir
    c = res.champs
    assert c.total_credite_ttc.valeur == "100.00" and c.total_credite_ttc.signe_imprime is SigneImprime.negatif
    ligne = c.lignes[0]
    assert ligne.montant_ht.valeur == "100.00" and ligne.montant_ht.signe_imprime is SigneImprime.negatif
    assert ligne.quantite.valeur == "2"


def test_avoir_381_quantites_negatives():
    xml = fab.cii(type_code="381", devise="EUR", incoterm=None,
                  lignes=[("Retour article fictif", "-3", "10.00", "30.00", None, None, "0")])
    _doc, res = _extraire(xml, "av.xml")
    assert res.champs.total_credite_ttc.valeur == "30.00" and res.champs.total_credite_ttc.signe_imprime is None
    assert res.champs.lignes[0].montant_ht.valeur == "30.00"


def test_codes_motif_de_frais_ubl():
    xml = fab.ubl().replace(
        b"<cac:TaxTotal>",
        b"<cac:AllowanceCharge><cbc:ChargeIndicator>true</cbc:ChargeIndicator>"
        b"<cbc:AllowanceChargeReasonCode>FC</cbc:AllowanceChargeReasonCode>"
        b'<cbc:Amount currencyID="EUR">40.00</cbc:Amount></cac:AllowanceCharge>'
        b"<cac:AllowanceCharge><cbc:ChargeIndicator>false</cbc:ChargeIndicator>"
        b"<cbc:AllowanceChargeReasonCode>95</cbc:AllowanceChargeReasonCode>"
        b'<cbc:Amount currencyID="EUR">5.00</cbc:Amount></cac:AllowanceCharge><cac:TaxTotal>', 1)
    _doc, res = _extraire(xml, "f.xml")
    assert [(s.type, s.montant.valeur) for s in res.champs.sous_totaux] == [
        (TypeSousTotal.fret, "40.00"), (TypeSousTotal.remise, "5.00")]


# --- réception, classement -----------------------------------------------------------------------------------


def test_xml_avec_commentaire_de_tete_reconnu():
    xml = fab.ubl().split(b"?>", 1)[1]
    assert detecter_type(b"<!--\n  Licence FICTIVE, ligne, avec, virgules\n-->\n" + xml) == MIME_XML
    assert detecter_type(b"\xef\xbb\xbf\r\n<!-- a --><!-- b -->\r\n<racine attr=\"1\">x</racine>") == MIME_XML
    assert detecter_type(b"<!-- seulement un commentaire -->\nbonjour") != MIME_XML
    doc, res = _extraire(b"<!-- Licence FICTIVE -->\n" + xml, "facture.xml")
    assert doc.type is TypeDocument.facture_commerciale and res.champs.total_facture.valeur == "12540.00"


def test_order_x_classe_bon_de_commande():
    order = (b'<?xml version="1.0"?><rsm:SCRDMCCBDACIOMessageStructure '
             b'xmlns:rsm="urn:un:unece:uncefact:data:SCRDMCCBDACIOMessageStructure:100">'
             b"<rsm:ExchangedDocument/></rsm:SCRDMCCBDACIOMessageStructure>")
    ubl_order = (b'<Order xmlns="urn:oasis:names:specification:ubl:schema:xsd:Order-2" '
                 b'xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">'
                 b"<cbc:ID>PO-FICTIF-1</cbc:ID></Order>")
    for contenu in (order, ubl_order):
        rec = recevoir_octets([("commande.xml", contenu)])
        fr = rec.fichiers[0]
        r = decouper_fichier(fr.fichier, fr.contenu, options=LOCAL, fiches=())
        doc = r.documents[0]
        assert doc.type is TypeDocument.document_non_exploitable
        assert doc.motif_non_exploitable is MotifNonExploitable.bon_commande
        assert not ExtracteurFactureXML().supports(doc, r.pages)


def test_csv_a_champ_demesure_sans_exception():
    fiche = FicheCorrespondance.depuis_dict({
        "format_id": "fictif_csv", "type": "csv", "detection": {"colonnes_requises": ["MRN"]},
        "entete": {"mrn": "MRN"}, "listes": {}})
    contenu = b"MRN;X\n26FR000000000000F1;" + b"A" * 200_000 + b"\n"
    assert not fiche.reconnait(contenu, MIME_CSV)
    assert analyser_contenu_structure(contenu, MIME_CSV, fiches=[fiche]) is None


# --- grandes factures ---------------------------------------------------------------------------------------


def test_chemin_xpath_avec_cache_identique_et_lineaire():
    racine = etree.fromstring(b"<r>" + b"".join(b"<l><v>%d</v></l>" % i for i in range(500)) + b"<s/></r>")
    cache: dict = {}
    for el in racine.iter("v"):
        assert _chemin_xpath(el, cache) == _chemin_xpath(el)
    assert _chemin_xpath(racine[-1], cache) == "/r/s"
    assert _chemin_xpath(racine[499][0], cache) == "/r/l[500]/v"
    assert set(cache) == {racine, *racine[:500]}  # chaque parent parcouru une fois


def test_facture_ubl_de_2000_lignes():
    lignes = [(f"Article fictif {i}", "1", "1.00", None, None) for i in range(2000)]
    contenu = fab.ubl(lignes=lignes)
    info = analyser_contenu_structure(contenu, MIME_XML, fiches=())
    doc = Document(type=info.type, pages=[])
    res = ExtracteurFactureXML().extract(doc, [], ExtractionContext(contenu_fichier=contenu, type_mime=MIME_XML))
    assert len(res.champs.lignes) == 2000
    assert res.champs.lignes[-1].montant_ligne.texte_contexte == "/Invoice/InvoiceLine[2000]/LineExtensionAmount"


def test_ligne_de_texte_seul_ignoree():
    """Une ligne qui ne porte qu'une note (ZUGFeRD 1.0) ne crée pas de ligne vide dans le modèle."""
    note = (b"<ram:IncludedSupplyChainTradeLineItem><ram:AssociatedDocumentLineDocument><ram:IncludedNote>"
            b"<ram:Content>Texte fictif</ram:Content></ram:IncludedNote></ram:AssociatedDocumentLineDocument>"
            b"<ram:SpecifiedSupplyChainTradeSettlement/></ram:IncludedSupplyChainTradeLineItem>")
    xml = zf1().replace(b"<ram:IncludedSupplyChainTradeLineItem>", note + b"<ram:IncludedSupplyChainTradeLineItem>", 1)
    _doc, res = _extraire(xml, "rechnung.xml")
    assert len(res.champs.lignes) == 1 and res.champs.lignes[0].montant_ligne.valeur == "100.00"
