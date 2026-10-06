"""Factur-X EN 16931 : XML CII valide au XSD, mentions obligatoires (françaises et 2026), PDF/A-3 embarqué."""

from __future__ import annotations

import io
from dataclasses import replace
from datetime import date
from decimal import Decimal

import facturx
import pdfplumber
import pytest
from lxml import etree

from controldone.facturation.facturx_cii import NS, controles_reforme, generer_xml, valider_xsd
from controldone.facturation.modele import TYPE_AVOIR, Acheteur, Facture, Ligne, Remise
from controldone.facturation.pdf import assembler_facturx, rendre_pdf

ACHETEUR = Acheteur(
    "cli_a",
    "CLIENT A FICTIF SAS",
    siren="000000001",
    tva_intracom="FR00000000001",
    adresse_ligne="10 avenue Fictive",
    code_postal="69001",
    ville="Lyon",
)


def _facture(catalogue, **kw) -> Facture:
    base = dict(
        numero="F-2026-0001",
        type_code="380",
        date_emission=date(2026, 10, 2),
        date_echeance=date(2026, 11, 1),
        vendeur=catalogue.vendeur,
        acheteur=ACHETEUR,
        lignes=(Ligne("Diagnostic FICTIF", Decimal("390.00")),),
        tva=catalogue.tva,
        paiement=catalogue.paiement,
    )
    base.update(kw)
    return Facture(**base)


def _x(xml: bytes, chemin: str) -> list[str]:
    return [
        e.text if isinstance(e, etree._Element) else str(e)
        for e in etree.fromstring(xml).xpath(chemin, namespaces=NS)
    ]


def test_totaux_et_tva(catalogue):
    f = _facture(
        catalogue, lignes=(Ligne("A", Decimal("199.00")), Ligne("B", Decimal("10.005"), Decimal("3")))
    )
    assert f.total_lignes_ht == Decimal("229.02")  # 199,00 + 30,015 -> 30,02
    assert f.montant_tva == Decimal("45.80")  # 229,02 × 20 % = 45,804
    assert f.total_ttc == Decimal("274.82") == f.net_a_payer


def test_xml_valide_xsd_et_mentions(catalogue):
    xml = generer_xml(_facture(catalogue))
    valider_xsd(xml)
    assert _x(
        xml, "//rsm:ExchangedDocumentContext/ram:BusinessProcessSpecifiedDocumentContextParameter/ram:ID"
    ) == ["S1"]
    assert _x(
        xml, "//rsm:ExchangedDocumentContext/ram:GuidelineSpecifiedDocumentContextParameter/ram:ID"
    ) == ["urn:cen.eu:en16931:2017"]
    notes = dict(
        zip(
            _x(xml, "//ram:IncludedNote/ram:SubjectCode"),
            _x(xml, "//ram:IncludedNote[ram:SubjectCode]/ram:Content"),
            strict=True,
        )
    )
    assert notes["BAR"] == "B2B"
    assert "BCE" in notes["PMD"] and "10 points" in notes["PMD"]
    assert "40 EUR" in notes["PMT"] and "L441-10" in notes["PMT"]
    assert notes["AAB"] == "Pas d'escompte pour paiement anticipé."
    assert "SIREN 999999999" in notes["REG"]
    assert any("prestation de services" in n for n in _x(xml, "//ram:IncludedNote/ram:Content"))
    # SIREN des deux parties (schéma 0002) et adresses électroniques de l'annuaire (0225)
    assert _x(xml, "//ram:SellerTradeParty/ram:SpecifiedLegalOrganization/ram:ID[@schemeID='0002']") == [
        "999999999"
    ]
    assert _x(xml, "//ram:BuyerTradeParty/ram:SpecifiedLegalOrganization/ram:ID[@schemeID='0002']") == [
        "000000001"
    ]
    assert _x(xml, "//ram:BuyerTradeParty/ram:URIUniversalCommunication/ram:URIID[@schemeID='0225']") == [
        "000000001"
    ]
    assert _x(xml, "//ram:SellerTradeParty/ram:SpecifiedTaxRegistration/ram:ID[@schemeID='VA']") == [
        "FR99999999999"
    ]
    assert _x(xml, "//ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:GrandTotalAmount") == ["468.00"]
    assert _x(xml, "//ram:ApplicableHeaderTradeSettlement/ram:ApplicableTradeTax/ram:CalculatedAmount") == [
        "78.00"
    ]
    assert _x(xml, "//ram:SpecifiedTradePaymentTerms/ram:DueDateDateTime/udt:DateTimeString") == ["20261101"]
    assert _x(xml, "//ram:PayeePartyCreditorFinancialAccount/ram:IBANID") == ["FR7630006000011234567890189"]
    assert _x(xml, "//ram:ApplicableHeaderTradeSettlement/ram:ApplicableTradeTax/ram:DueDateTypeCode") == []
    assert controles_reforme(_facture(catalogue)) == []


def test_option_debits_adresse_livraison_et_franchise(catalogue):
    deb = generer_xml(_facture(catalogue, tva=replace(catalogue.tva, option_debits=True)))
    valider_xsd(deb)
    assert _x(deb, "//ram:ApplicableHeaderTradeSettlement/ram:ApplicableTradeTax/ram:DueDateTypeCode") == [
        "5"
    ]
    assert "débits" in " ".join(_x(deb, "//ram:IncludedNote[ram:SubjectCode='TXD']/ram:Content"))

    livr = generer_xml(
        _facture(
            catalogue,
            acheteur=replace(
                ACHETEUR,
                livraison_ligne="Entrepôt FICTIF",
                livraison_code_postal="13015",
                livraison_ville="Marseille",
            ),
        )
    )
    valider_xsd(livr)
    assert _x(livr, "//ram:ShipToTradeParty/ram:PostalTradeAddress/ram:LineOne") == ["Entrepôt FICTIF"]
    assert _x(generer_xml(_facture(catalogue)), "//ram:ShipToTradeParty") == []

    f = _facture(catalogue, tva=replace(catalogue.tva, tva_applicable=False))
    fr = generer_xml(f)
    valider_xsd(fr)
    assert f.total_ttc == Decimal("390.00")
    assert _x(fr, "//ram:ApplicableHeaderTradeSettlement/ram:ApplicableTradeTax/ram:CategoryCode") == ["E"]
    assert _x(fr, "//ram:ApplicableHeaderTradeSettlement/ram:ApplicableTradeTax/ram:ExemptionReason") == [
        "TVA non applicable, art. 293 B du CGI"
    ]
    assert _x(fr, "//ram:SellerTradeParty/ram:SpecifiedTaxRegistration") == []


def test_avoir_et_remise_cent_pour_cent(catalogue):
    av = _facture(
        catalogue,
        numero="AV-2026-0001",
        type_code=TYPE_AVOIR,
        facture_origine="F-2026-0001",
        date_facture_origine=date(2026, 10, 2),
        date_echeance=date(2026, 10, 2),
    )
    xml = generer_xml(av)
    valider_xsd(xml)
    assert _x(xml, "//rsm:ExchangedDocument/ram:TypeCode") == ["381"]
    assert _x(xml, "//ram:InvoiceReferencedDocument/ram:IssuerAssignedID") == ["F-2026-0001"]
    gratuit = _facture(catalogue, remises=(Remise("Offre de lancement (coupon)", Decimal("390.00")),))
    xg = generer_xml(gratuit)
    valider_xsd(xg)
    assert gratuit.total_ttc == Decimal("0.00")
    assert _x(xg, "//ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:AllowanceTotalAmount") == [
        "390.00"
    ]
    with pytest.raises(ValueError):
        _facture(catalogue, type_code=TYPE_AVOIR)  # avoir sans facture d'origine
    with pytest.raises(ValueError):
        _facture(catalogue, remises=(Remise("trop", Decimal("400")),))


def test_xml_invalide_refuse(catalogue):
    xml = generer_xml(_facture(catalogue)).replace(b"<ram:TypeCode>380</ram:TypeCode>", b"")
    with pytest.raises(Exception):  # noqa: B017 - l'exception exacte dépend de la bibliothèque
        valider_xsd(xml)


def test_controles_reforme_signalent_les_manques(catalogue):
    from controldone.facturation.offres import Vendeur

    f = _facture(catalogue, vendeur=Vendeur(), acheteur=replace(ACHETEUR, siren=""))
    anomalies = " ".join(controles_reforme(f))
    assert "SIREN du vendeur" in anomalies and "SIREN de l'acheteur" in anomalies


def test_pdf_facturx_mentions_lisibles_et_xml_embarque(catalogue):
    f = _facture(catalogue)
    xml = generer_xml(f)
    pdf = assembler_facturx(rendre_pdf(f), xml, numero=f.numero, vendeur="CONTROLDONE FICTIF")
    assert pdf[:5] == b"%PDF-"
    nom, embarque = facturx.get_xml_from_pdf(pdf, check_xsd=True)
    assert nom == "factur-x.xml" and embarque == xml
    assert facturx.get_level(etree.fromstring(embarque)) == "en16931"
    with pdfplumber.open(io.BytesIO(pdf)) as p:
        texte = " ".join((pg.extract_text() or "") for pg in p.pages).replace("\n", " ")
    for attendu in (
        "FACTURE n° F-2026-0001",
        "SIREN 999999999",
        "SIREN 000000001",
        "40 EUR",
        "BCE",
        "Pas d'escompte",
        "prestation de services",
        "Total TTC",
        "468,00",
        "TVA 20 %",
        "N° TVA intracommunautaire : FR99999999999",
    ):
        assert attendu in texte, attendu
    from pypdf import PdfReader

    racine = PdfReader(io.BytesIO(pdf)).trailer["/Root"]
    xmp = racine["/Metadata"].get_object().get_data()
    assert b"pdfaid" in xmp and b"3" in xmp and b"factur-x" in xmp.lower()  # PDF/A-3 + extension Factur-X
    assert "/AF" in racine  # fichier associé (XML) déclaré


def test_pdf_non_valable_si_vendeur_incomplet(catalogue):
    from controldone.facturation.offres import Vendeur

    f = _facture(catalogue, vendeur=Vendeur())
    with pdfplumber.open(io.BytesIO(rendre_pdf(f, non_valable=True))) as p:
        assert "NON VALABLE" in (p.pages[0].extract_text() or "")
