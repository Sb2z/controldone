"""Déclarations sous des présentations nouvelles (D-2401 à D-2405) — documents **fictifs** propres à ces tests.

- feuillet d'en-tête et annexes : rubriques composées, taux de change sans libellé, blocs d'article dont le code
  n'a pas de libellé, deux tableaux de taxes côte à côte, récapitulatif « type / libellé / montant » ;
- état de liquidation en un seul tableau (colonnes d'article et de taxation, sous-lignes de taxe, suite de
  désignation) ;
- export XML d'un schéma inconnu, lu par ses noms d'éléments (fiche déduite).
"""

from __future__ import annotations

import io

from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas

from controldone.extract.base import ExtractionContext
from controldone.extract.deterministe.declaration import ExtracteurDeclaration
from controldone.ids import IdGenerator
from controldone.ingest import (
    ExtracteurDeclarationExport,
    OptionsPages,
    decouper_fichier,
    extraire_pages,
    recevoir_octets,
)
from controldone.ingest.structure import analyser_contenu_structure
from controldone.ingest.structure_deduite import (
    CONFIANCE_DEDUITE,
    CONFIANCE_DEDUITE_DOUTEUSE,
    correspondance_confirmee,
    deduire_fiche_declaration,
)
from controldone.model import Document, PageRef
from controldone.model.champs import ChampsDeclaration
from controldone.model.enums import CategorieTaxe, PaiementNormalise, TauxChangeSens, TypeDocument
from controldone.normalize import tva_fr_depuis_siren

TVA_IMP = tva_fr_depuis_siren("000424242")
TVA_DEC = tva_fr_depuis_siren("000515151")
MRN = "26FRQ7ZK3M5T8W2N4B"


def _pdf(pages: list[list[tuple]], taille_page=A4) -> bytes:
    """Éléments ``(x, y, texte[, taille])`` en fractions de page (origine en haut à gauche)."""
    larg, haut = taille_page
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=taille_page, invariant=1)
    for elements in pages:
        c.setFont("Helvetica", 6)
        c.drawCentredString(0.5 * larg, 0.985 * haut, "DONNÉES FICTIVES — DOCUMENT DE TEST")
        for el in elements:
            x, y, texte = el[:3]
            c.setFont("Helvetica", el[3] if len(el) > 3 else 8)
            c.drawString(x * larg, (1 - y) * haut, texte)
        c.showPage()
    c.save()
    return buf.getvalue()


def _extraire(contenu: bytes) -> ChampsDeclaration:
    extraites = extraire_pages(
        contenu, type_mime="application/pdf", options=OptionsPages(ocr=False, isoler=False)
    )
    pages = [pe.page for pe in extraites]
    doc = Document(
        type=TypeDocument.declaration,
        pages=[
            PageRef(fichier_id=p.fichier_id, numero=p.numero, qualite_texte=p.qualite_texte) for p in pages
        ],
    )
    ctx = ExtractionContext(
        ids=IdGenerator.deterministe(5),
        options={"textes_pages": {pe.page.numero: pe.texte for pe in extraites}},
    )
    res = ExtracteurDeclaration().extract(doc, pages, ctx)
    assert isinstance(res.champs, ChampsDeclaration)
    return res.champs


def _v(x):
    return None if x is None else x.valeur


def _ligne(y: float, *cellules: tuple[float, str]) -> list[tuple]:
    return [(x, y, t) for x, t in cellules]


# --- feuillet d'en-tête et annexes ----------------------------------------------------------------------------


def _feuillet_et_annexe() -> bytes:
    p1 = [
        (0.06, 0.05, "LOGICIEL FICTIF — DÉCLARATION H7 — FEUILLET D'EN-TÊTE   1/2"),
        *_ligne(
            0.08,
            (0.06, f"MRN {MRN}"),
            (0.36, "LRN LRN000000777"),
            (0.56, "rang 2"),
            (0.68, "acceptée le 04/05/2026"),
        ),
        *_ligne(0.11, (0.06, "Importateur"), (0.25, "Atelier Fictif SARL")),
        (0.06, 0.13, f"TVA {TVA_IMP} — EORI FR00042424200000"),
        *_ligne(0.16, (0.06, "Déclarant"), (0.25, "Transit Imaginaire SAS")),
        (0.06, 0.18, f"TVA {TVA_DEC}"),
        *_ligne(0.21, (0.06, "Livraison / expédition"), (0.25, "DAP Lyon")),
        (0.06, 0.23, "Pays d'expédition CH"),
        *_ligne(0.26, (0.06, "Facturation"), (0.25, "1 200,00 CHF")),
        (0.06, 0.28, "1 EUR = 0,93500 CHF"),
        (0.06, 0.31, "Masse brute / colis / articles 12,500 kg — 3 colis — 2 article(s)"),
        (0.06, 0.34, "Documents"),
        *_ligne(0.36, (0.06, "N380"), (0.16, "Facture commerciale"), (0.40, "FAC-T-0001")),
        (0.06, 0.40, "Impositions globales"),
        *_ligne(
            0.42,
            (0.06, "Type"),
            (0.16, "Base"),
            (0.30, "Taux"),
            (0.44, "Montant"),
            (0.56, "À payer"),
            (0.68, "MP"),
        ),
        *_ligne(
            0.44,
            (0.06, "FPE"),
            (0.16, "2 art."),
            (0.30, "3,00 EUR/art."),
            (0.44, "6,00"),
            (0.56, "6,00"),
            (0.68, "E"),
        ),
        (0.06, 0.48, "Récapitulatif de la liquidation"),
        *_ligne(0.50, (0.06, "Type"), (0.16, "Libellé"), (0.50, "Montant EUR")),
        *_ligne(0.52, (0.06, "FPE"), (0.16, "Droit forfaitaire petits envois"), (0.50, "6,00")),
        *_ligne(0.54, (0.06, "B00"), (0.16, "TVA import"), (0.50, "39,20")),
        *_ligne(0.56, (0.06, "TOTAL DROITS ET TAXES"), (0.50, "45,20")),
        *_ligne(0.58, (0.06, "TOTAL À PAYER / À GARANTIR"), (0.50, "45,20")),
    ]
    p2 = [
        (0.06, 0.05, f"ANNEXE A1 — MRN {MRN}   2/2"),
        (0.06, 0.08, "Article 1 — 8471300000 — origine CN — préf. 100 — régime 4000/000"),
        (0.06, 0.10, "Ordinateur portable fictif"),
        (0.06, 0.12, "Montant facturé 1 000,00 CHF — valeur statistique 1 069,52 EUR"),
        (0.06, 0.14, "Masse nette 9,000 kg — masse brute 10,000 kg — colis 2 — quantité 2 p/st"),
        *_ligne(0.17, (0.06, "Droits et autres taxes"), (0.52, "TVA à l'importation")),
        *_ligne(
            0.19,
            (0.06, "Taxe"),
            (0.16, "Base"),
            (0.28, "Taux"),
            (0.38, "Montant"),
            (0.47, "MP"),
            (0.52, "Taxe"),
            (0.62, "Base"),
            (0.74, "Taux"),
            (0.84, "Montant"),
            (0.93, "MP"),
        ),
        *_ligne(
            0.21,
            (0.06, "A00"),
            (0.16, "0,00"),
            (0.28, "0,0%"),
            (0.38, "0,00"),
            (0.47, "E"),
            (0.52, "B00"),
            (0.62, "150,00"),
            (0.74, "20,0%"),
            (0.84, "30,00"),
            (0.93, "E"),
        ),
        (0.06, 0.25, "Article 2 — 4202329000 — origine VN — préf. 100 — régime 4000/000"),
        (0.06, 0.27, "Étui fictif"),
        (0.06, 0.29, "Montant facturé 200,00 CHF — valeur statistique 213,90 EUR"),
        (0.06, 0.31, "Masse nette 2,000 kg — masse brute 2,500 kg — colis 1 — quantité 4 p/st"),
        *_ligne(
            0.34,
            (0.06, "Taxe"),
            (0.16, "Base"),
            (0.28, "Taux"),
            (0.38, "Montant"),
            (0.47, "MP"),
            (0.52, "Taxe"),
            (0.62, "Base"),
            (0.74, "Taux"),
            (0.84, "Montant"),
            (0.93, "MP"),
        ),
        *_ligne(
            0.36,
            (0.06, "A00"),
            (0.16, "0,00"),
            (0.28, "0,0%"),
            (0.38, "0,00"),
            (0.47, "E"),
            (0.52, "B00"),
            (0.62, "46,00"),
            (0.74, "20,0%"),
            (0.84, "9,20"),
            (0.93, "E"),
        ),
    ]
    return _pdf([p1, p2])


def test_feuillet_d_en_tete_rubriques_composees_et_taux_sans_libelle():
    c = _extraire(_feuillet_et_annexe())
    assert _v(c.mrn) == MRN and _v(c.lrn) == "LRN000000777" and _v(c.version) == "2"
    assert _v(c.date_acceptation) == "2026-05-04"
    assert (
        _v(c.masse_brute_totale) == "12.500"
        and _v(c.nombre_colis_total) == "3"
        and _v(c.nombre_articles) == "2"
    )
    assert _v(c.montant_total_facture) == "1200.00" and _v(c.devise_facture) == "CHF"
    assert _v(c.incoterm) == "DAP"
    assert _v(c.taux_change) == "0.93500" and _v(c.taux_change_sens) == TauxChangeSens.devise_par_eur.value
    assert c.taux_change.confiance >= 0.90
    assert _v(c.total_droits_taxes) == "45.20"


def test_annexes_blocs_sans_libelle_de_code_et_taxes_cote_a_cote():
    c = _extraire(_feuillet_et_annexe())
    arts = [
        (
            _v(a.numero_article),
            _v(a.code_marchandise),
            _v(a.pays_origine),
            _v(a.masse_nette),
            _v(a.masse_brute),
            _v(a.nombre_colis),
        )
        for a in c.articles
    ]
    assert arts == [
        ("1", "8471300000", "CN", "9.000", "10.000", "2"),
        ("2", "4202329000", "VN", "2.000", "2.500", "1"),
    ]
    assert _v(c.articles[0].quantite_unite_supplementaire) == "2"
    taxes = [(_v(t.article), _v(t.type_taxe), _v(t.base_montant), _v(t.montant)) for t in c.taxations]
    assert ("1", "A00", "0.00", "0.00") in taxes and ("1", "B00", "150.00", "30.00") in taxes
    assert ("2", "B00", "46.00", "9.20") in taxes
    # forfait de niveau déclaration : catégorie d'après le récapitulatif « type / libellé / montant »
    fpe = next(t for t in c.taxations if _v(t.type_taxe) == "FPE")
    assert fpe.categorie is CategorieTaxe.forfait_petits_envois and fpe.article is None
    assert all(t.paiement_normalise is PaiementNormalise.differe for t in c.taxations)


# --- état de liquidation en un seul tableau -----------------------------------------------------------------------

_COLS = [
    (0.03, "Art."),
    (0.07, "Code NC"),
    (0.17, "Or."),
    (0.21, "Désignation"),
    (0.42, "Mt facturé"),
    (0.50, "Net kg"),
    (0.57, "Brut kg"),
    (0.64, "Colis"),
    (0.69, "Taxe"),
    (0.74, "Base"),
    (0.81, "Taux"),
    (0.87, "Montant"),
    (0.93, "À payer"),
    (0.98, "MP"),
]


def _etat_liquidation() -> bytes:
    els = [
        (0.03, 0.05, "ÉTAT DE LIQUIDATION DES DROITS ET TAXES — LOGICIEL FICTIF", 10),
        *_ligne(
            0.09,
            (0.03, "N° MRN ......................"),
            (0.25, MRN),
            (0.52, "Déclarant ..............."),
            (0.70, "Transit Imaginaire SAS"),
        ),
        *_ligne(0.12, (0.03, "LRN / rang ......................"), (0.25, "LRN000000888 / 3")),
        *_ligne(0.15, (0.03, "Importateur ....................."), (0.25, "Atelier Fictif SARL")),
        *_ligne(
            0.18,
            (0.03, "TVA importateur ................"),
            (0.25, TVA_IMP),
            (0.52, "Montant facturé ........"),
            (0.70, "300,00 EUR"),
        ),
        *_ligne(0.21, (0.03, "Colis / articles ................."), (0.25, "4 / 2")),
        *_ligne(0.26, *_COLS),
        *_ligne(
            0.29,
            (0.03, "1"),
            (0.07, "8471300000"),
            (0.17, "CN"),
            (0.21, "Clavier fictif — réf. A-1,"),
            (0.42, "200,00"),
            (0.50, "5,000"),
            (0.57, "5,500"),
            (0.64, "3"),
            (0.69, "A00"),
            (0.74, "200,00"),
            (0.81, "2,0 %"),
            (0.87, "4,00"),
            (0.93, "4,00"),
            (0.98, "A"),
        ),
        (0.21, 0.31, "A-2, A-3"),
        (0.21, 0.33, "A-4"),
        *_ligne(
            0.35,
            (0.69, "B00"),
            (0.74, "204,00"),
            (0.81, "20,0 %"),
            (0.87, "40,80"),
            (0.93, "40,80"),
            (0.98, "A"),
        ),
        *_ligne(
            0.38,
            (0.03, "2"),
            (0.07, "4202329000"),
            (0.17, "VN"),
            (0.21, "Étui fictif"),
            (0.42, "100,00"),
            (0.50, "1,000"),
            (0.57, "1,200"),
            (0.64, "1"),
            (0.69, "A00"),
            (0.74, "100,00"),
            (0.81, "3,7 %"),
            (0.87, "3,70"),
            (0.93, "3,70"),
            (0.98, "A"),
        ),
        *_ligne(
            0.40,
            (0.69, "B00"),
            (0.74, "103,70"),
            (0.81, "20,0 %"),
            (0.87, "20,74"),
            (0.93, "20,74"),
            (0.98, "A"),
        ),
        (
            0.03,
            0.44,
            "Total A00 : 7,70 Total B00 : 61,54   TOTAL DROITS ET TAXES 69,24 EUR — TOTAL À PAYER 69,24 EUR",
        ),
        (0.03, 0.47, "MP : A comptant — E crédit d'enlèvement — G TVA autoliquidée"),
    ]
    return _pdf([[(e[0], e[1], e[2], e[3] if len(e) > 3 else 7) for e in els]], taille_page=landscape(A4))


def test_etat_de_liquidation_tableau_mixte():
    c = _extraire(_etat_liquidation())
    assert _v(c.mrn) == MRN and _v(c.lrn) == "LRN000000888" and _v(c.version) == "3"
    assert _v(c.nombre_colis_total) == "4" and _v(c.nombre_articles) == "2"
    arts = [
        (
            _v(a.numero_article),
            _v(a.code_marchandise),
            _v(a.pays_origine),
            _v(a.montant_facture_article),
            _v(a.masse_nette),
            _v(a.masse_brute),
            _v(a.nombre_colis),
        )
        for a in c.articles
    ]
    assert arts == [
        ("1", "8471300000", "CN", "200.00", "5.000", "5.500", "3"),
        ("2", "4202329000", "VN", "100.00", "1.000", "1.200", "1"),
    ]
    taxes = [
        (
            _v(t.article),
            _v(t.type_taxe),
            t.categorie,
            _v(t.base_montant),
            _v(t.taux),
            _v(t.montant),
            t.paiement_normalise,
        )
        for t in c.taxations
    ]
    assert taxes == [
        ("1", "A00", CategorieTaxe.droit, "200.00", "2.0", "4.00", PaiementNormalise.comptant),
        ("1", "B00", CategorieTaxe.tva, "204.00", "20.0", "40.80", PaiementNormalise.comptant),
        ("2", "A00", CategorieTaxe.droit, "100.00", "3.7", "3.70", PaiementNormalise.comptant),
        ("2", "B00", CategorieTaxe.tva, "103.70", "20.0", "20.74", PaiementNormalise.comptant),
    ]
    assert _v(c.total_droits_taxes) == "69.24"


# --- export XML d'un schéma inconnu -------------------------------------------------------------------------------

XML_INCONNU = f"""<?xml version='1.0' encoding='UTF-8'?>
<ImportClearance xmlns="urn:fictif:test:import-clearance:1">
  <Remark>DONNÉES FICTIVES — test</Remark>
  <General>
    <MRN>{MRN}</MRN>
    <LocalReference>LRN-X-1</LocalReference>
    <VersionNumber>1</VersionNumber>
    <DateOfAcceptance>2026-06-02</DateOfAcceptance>
    <Consignee><CompanyName>Atelier Fictif SARL</CompanyName><VAT>{TVA_IMP}</VAT></Consignee>
    <Declarant><Name>Transit Imaginaire SAS</Name><VAT>{TVA_DEC}</VAT></Declarant>
    <TermsOfDelivery incoterm="FCA" place="Basel"/>
    <CountryOfDispatch>CH</CountryOfDispatch>
    <InvoiceCurrency>CHF</InvoiceCurrency>
    <InvoiceTotal>1000.00</InvoiceTotal>
    <ExchangeRate direction="EUR_PER_CURRENCY">1.06952</ExchangeRate>
    <TotalGrossMass>12.500</TotalGrossMass>
    <NumberOfPackages>3</NumberOfPackages>
    <NumberOfItems>1</NumberOfItems>
  </General>
  <Attached><Doc code="N380"><Reference>FAC-X-1</Reference></Doc></Attached>
  <Goods>
    <GoodsItem number="1">
      <HSCode>8471300000</HSCode><Description>Ordinateur fictif</Description><CountryOfOrigin>CN</CountryOfOrigin>
      <InvoiceAmount currency="CHF">1000.00</InvoiceAmount><StatisticalValue>1069.52</StatisticalValue>
      <NetWeight>9.000</NetWeight><GrossWeight>10.000</GrossWeight><Packages>3</Packages>
      <Levies>
        <Levy code="A00" label="Customs duty"><TaxBase>1069.52</TaxBase><Rate>0</Rate><Amount>0.00</Amount>
          <PaymentMethod>E</PaymentMethod></Levy>
        <Levy code="B00" label="Import VAT"><TaxBase>1069.52</TaxBase><Rate>20</Rate><Amount>213.90</Amount>
          <PaymentMethod>G</PaymentMethod></Levy>
      </Levies>
    </GoodsItem>
  </Goods>
  <Totals><TotalDutiesAndTaxes>213.90</TotalDutiesAndTaxes><TotalPayable>0.00</TotalPayable></Totals>
</ImportClearance>
""".encode()


def _extraire_xml(contenu: bytes):
    rec = recevoir_octets([("export_inconnu.xml", contenu)])
    fr = rec.fichiers[0]
    r = decouper_fichier(fr.fichier, fr.contenu, options=OptionsPages(isoler=False))
    doc = r.documents[0]
    ctx = ExtractionContext(
        contenu_fichier=fr.contenu, type_mime=fr.fichier.type_mime, ids=IdGenerator.deterministe(4)
    )
    return doc, ExtracteurDeclarationExport().extract(doc, r.pages, ctx)


def test_export_xml_inconnu_classe_declaration_et_lu_par_ses_noms():
    doc, res = _extraire_xml(XML_INCONNU)
    assert doc.type is TypeDocument.declaration and doc.sous_type == "export_xml"
    c = res.champs
    assert isinstance(c, ChampsDeclaration)
    assert _v(c.mrn) == MRN and _v(c.lrn) == "LRN-X-1" and _v(c.date_acceptation) == "2026-06-02"
    assert _v(c.importateur.nom) == "Atelier Fictif SARL" and _v(c.importateur.tva) == TVA_IMP
    assert _v(c.declarant.tva) == TVA_DEC
    assert _v(c.incoterm) == "FCA" and _v(c.incoterm_lieu) == "Basel"
    assert _v(c.taux_change_sens) == TauxChangeSens.eur_par_devise.value
    assert _v(c.nombre_articles) == "1" and _v(c.nombre_colis_total) == "3"
    assert [(_v(d.type_code), _v(d.reference)) for d in c.documents_references] == [("N380", "FAC-X-1")]
    a = c.articles[0]
    assert (_v(a.numero_article), _v(a.code_marchandise), _v(a.pays_origine), _v(a.masse_brute)) == (
        "1",
        "8471300000",
        "CN",
        "10.000",
    )
    taxes = [
        (_v(t.article), _v(t.type_taxe), t.categorie, _v(t.montant), t.paiement_normalise)
        for t in c.taxations
    ]
    assert taxes == [
        ("1", "A00", CategorieTaxe.droit, "0.00", PaiementNormalise.differe),
        ("1", "B00", CategorieTaxe.tva, "213.90", PaiementNormalise.autoliquide),
    ]
    # correspondance déduite et confirmée par les recoupements : jamais la certitude d'une fiche écrite
    assert c.mrn.confiance == CONFIANCE_DEDUITE < 1.0
    assert any(a.startswith("fiche_deduite") for a in res.avertissements)


def test_export_xml_inconnu_incoherent_reste_douteux():
    faux = XML_INCONNU.replace(b"<Amount>213.90</Amount>", b"<Amount>999.99</Amount>").replace(
        b"<TotalDutiesAndTaxes>213.90", b"<TotalDutiesAndTaxes>5.00"
    )
    _doc, res = _extraire_xml(faux)
    assert res.champs.mrn.confiance == CONFIANCE_DEDUITE_DOUTEUSE < 0.90


def test_correspondance_confirmee_tolere_une_anomalie_isolee():
    assert correspondance_confirmee(8, 1) and correspondance_confirmee(2, 1)
    assert not correspondance_confirmee(0, 0) and not correspondance_confirmee(3, 3)


def test_xml_quelconque_n_est_pas_une_declaration():
    from lxml import etree

    autre = (
        b"<?xml version='1.0'?><Catalogue><Item><Name>Chaise</Name><Price>10.00</Price></Item></Catalogue>"
    )
    assert deduire_fiche_declaration(etree.fromstring(autre)) is None
    assert analyser_contenu_structure(autre, "application/xml") is None
    # un MRN seul (sans article ni taxation) ne suffit pas
    seul = f"<?xml version='1.0'?><Notice><MRN>{MRN}</MRN></Notice>".encode()
    assert deduire_fiche_declaration(etree.fromstring(seul)) is None
