"""Extracteurs ``structure`` : Factur-X, CII, UBL, exports de déclaration par fiche de correspondance."""

from __future__ import annotations

from pathlib import Path

import fabriques as fab
import pytest
import yaml

from controldone.extract.base import Extracteur, ExtractionContext
from controldone.ids import IdGenerator
from controldone.ingest import (
    ExtracteurDeclarationExport,
    ExtracteurFactureXML,
    FicheCorrespondance,
    OptionsPages,
    analyser_contenu_structure,
    categorie_taxe,
    charger_fiches,
    decouper_fichier,
    extracteurs,
    nature_ligne,
    paiement_normalise,
    recevoir_octets,
)
from controldone.model.enums import (
    CategorieTaxe,
    Methode,
    NatureLigne,
    PaiementNormalise,
    TauxNature,
    TotalOrigine,
    TypeDocument,
    TypeIndiceAutoliquidation,
)

LOCAL = OptionsPages(isoler=False)


def _extraire(contenu: bytes, nom: str, fiches=None):
    rec = recevoir_octets([(nom, contenu)])
    fr = rec.fichiers[0]
    r = decouper_fichier(fr.fichier, fr.contenu, options=LOCAL, fiches=fiches)
    doc = r.documents[0]
    ctx = ExtractionContext(contenu_fichier=fr.contenu, type_mime=fr.fichier.type_mime,
                            ids=IdGenerator.deterministe(9))
    ex = ExtracteurDeclarationExport(fiches) if doc.type is TypeDocument.declaration else ExtracteurFactureXML()
    assert ex.supports(doc, r.pages)
    return doc, ex.extract(doc, r.pages, ctx)


def _provenance_complete(res, doc):
    for v in res.valeurs:
        assert v.document_id == doc.id and v.page == 1 and v.chemin.startswith(doc.type.value + ".")
        assert "[]" not in v.chemin
        if v.methode is not Methode.derive:
            assert v.valeur_brute and v.texte_contexte and v.methode in (Methode.xml_structure, Methode.csv_structure)


def test_extracteurs_respectent_le_protocole():
    for e in extracteurs():
        assert isinstance(e, Extracteur) and e.type == "structure"


def test_cii_facture_commerciale():
    doc, res = _extraire(fab.cii(), "facture.xml")
    assert doc.type is TypeDocument.facture_commerciale and doc.sous_type == "facture"
    c = res.champs
    assert c.numero.valeur == "INV-2026-0815" and c.date.valeur == "2026-08-14" and c.devise.valeur == "USD"
    assert c.total_facture.valeur == "12540.00" and c.total_facture.unite == "USD"
    assert c.total_facture.total_origine is TotalOrigine.imprime
    assert c.acheteur.tva.valeur == fab.TVA_CLIENT and c.incoterm.valeur == "FOB"
    ligne = c.lignes[0]
    assert ligne.code_marchandise_imprime.valeur == "847130" and ligne.pays_origine.valeur == "CN"
    assert ligne.quantite.valeur == "10" and ligne.quantite.unite == "C62"
    # valide au schéma : confiance 1,0 (sauf valeur non normalisable, ex. TVA hors UE du vendeur)
    assert all(v.confiance == 1.0 for v in res.valeurs if v.valeur is not None)
    _provenance_complete(res, doc)


def test_facturx_transitaire_debours_et_mrn():
    xml = fab.cii(numero="FT-2026-00042", devise="EUR", incoterm=None, refs_doc=["26FR000000000001A1", "176-12345675"],
                  lignes=[("Droits de douane", "1", "313.50", "313.50", None, None, "0"),
                          ("TVA import", "1", "2508.00", "2508.00", None, None, "0"),
                          ("Frais de dédouanement", "1", "65.00", "65.00", None, None, "20"),
                          ("Avance de fonds", "1", "70.53", "70.53", None, None, "20")],
                  vendeur="FICTIF TRANSIT SARL", tva_vendeur="FR40000987651")
    pdf = fab.facturx_pdf(xml, fab.FACTURE_TRANSITAIRE)
    info = analyser_contenu_structure(pdf, "application/pdf")
    assert info is not None and info.format == "facturx" and info.type is TypeDocument.facture_transitaire
    doc, res = _extraire(pdf, "ft.pdf")
    assert doc.type is TypeDocument.facture_transitaire
    c = res.champs
    assert [x.nature for x in c.lignes] == [NatureLigne.debours_droits, NatureLigne.debours_tva,
                                          NatureLigne.frais_dedouanement, NatureLigne.frais_avance_fonds]
    assert [v.valeur for v in c.refs_mrn] == ["26FR000000000001A1"]
    assert [v.valeur for v in c.refs_transport] == ["176-12345675"]
    assert c.total_debours.valeur == "2821.50" and c.total_debours.total_origine is TotalOrigine.reconstruit
    assert c.total_debours.methode is Methode.derive and c.total_debours.confiance <= 0.6
    assert c.emetteur.tva.valeur == "FR40000987651" and c.client_facture.tva.valeur == fab.TVA_CLIENT
    assert c.total_ttc.valeur == "2984.14"
    _provenance_complete(res, doc)


def test_cii_avoir():
    xml = fab.cii(numero="AV-1", type_code="381", devise="EUR", incoterm=None, ref_origine="FT-2026-00042",
                  lignes=[("Frais de dédouanement", "1", "65.00", "65.00", None, None, "20")],
                  note="Motif : geste commercial")
    doc, res = _extraire(xml, "av.xml")
    assert doc.type is TypeDocument.avoir
    c = res.champs
    assert [v.valeur for v in c.refs_facture_origine] == ["FT-2026-00042"]
    assert c.total_credite_ttc.valeur == "78.00" and c.motif.valeur == "geste commercial"


def test_ubl_facture_et_avoir():
    doc, res = _extraire(fab.ubl(), "ubl.xml")
    assert doc.type is TypeDocument.facture_commerciale
    assert res.champs.total_facture.valeur == "12540.00" and res.champs.acheteur.tva.valeur == fab.TVA_CLIENT
    assert res.champs.lignes[0].quantite.unite == "C62"
    assert all(v.confiance == 1.0 for v in res.valeurs if v.valeur is not None)
    doc, res = _extraire(fab.ubl(avoir=True, numero="CN-9", ref_origine="UBL-2026-001",
                                 lignes=[("Frais de dédouanement", "1", "65.00", None, None)]), "cn.xml")
    assert doc.type is TypeDocument.avoir
    assert [v.valeur for v in res.champs.refs_facture_origine] == ["UBL-2026-001"]
    _provenance_complete(res, doc)


def test_ubl_lieu_incoterm_tire_des_conditions_en_clair():
    """Lieu absent de ``DeliveryLocation`` : tiré de ``SpecialTerms`` (« DAP Le Havre Incoterms 2020 »), confiance
    0,90 ; un ``DeliveryLocation`` imprimé reste prioritaire ; des conditions qui ne commencent pas par le code ne
    donnent aucun lieu (D-2013)."""
    libre = ("<cac:DeliveryTerms><cbc:ID>DAP</cbc:ID><cbc:SpecialTerms>DAP Le Havre Incoterms 2020</cbc:SpecialTerms>"
             "</cac:DeliveryTerms>")
    _doc, res = _extraire(fab.ubl(livraison=libre), "ubl.xml")
    assert res.champs.incoterm.valeur == "DAP"
    assert res.champs.incoterm_lieu.valeur == "Le Havre" and res.champs.incoterm_lieu.confiance == 0.9
    lieu = ("<cac:DeliveryTerms><cbc:ID>CIF</cbc:ID><cbc:SpecialTerms>CIF Fos (Incoterms 2020)</cbc:SpecialTerms>"
            "<cac:DeliveryLocation><cbc:ID>Marseille</cbc:ID></cac:DeliveryLocation></cac:DeliveryTerms>")
    _doc, res = _extraire(fab.ubl(livraison=lieu), "ubl.xml")
    assert res.champs.incoterm_lieu.valeur == "Marseille" and res.champs.incoterm_lieu.confiance == 1.0
    autre = ("<cac:DeliveryTerms><cbc:ID>FOB</cbc:ID><cbc:SpecialTerms>Delivery within 30 days</cbc:SpecialTerms>"
             "</cac:DeliveryTerms>")
    _doc, res = _extraire(fab.ubl(livraison=autre), "ubl.xml")
    assert res.champs.incoterm_lieu is None


def test_xml_non_valide_au_schema_confiance_095():
    xml = fab.cii().replace(b"<ram:TypeCode>380</ram:TypeCode>", b"<ram:TypeCode>380</ram:TypeCode><ram:Inconnu/>")
    _doc, res = _extraire(xml, "f.xml")
    assert "schema_non_valide" in res.avertissements
    assert all(v.confiance == 0.95 for v in res.valeurs if v.valeur is not None)


def test_xml_sans_entites_externes():
    xxe = (b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
           b'<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100">'
           b'&x;</rsm:CrossIndustryInvoice>')
    info = analyser_contenu_structure(xxe, "application/xml")
    assert info is None or b"root:" not in (info.xml or b"")


@pytest.mark.parametrize(
    ("libelle", "nature"),
    [("Droits de douane", NatureLigne.debours_droits), ("Droits et taxes", NatureLigne.debours_combines),
     ("TVA à l'importation", NatureLigne.debours_tva), ("Autres taxes", NatureLigne.debours_autres_taxes),
     ("Droit forfaitaire petits envois", NatureLigne.debours_forfait_petits_envois),
     ("Frais d'avance de fonds", NatureLigne.frais_avance_fonds),
     ("Lignes supplémentaires", NatureLigne.frais_ligne_supplementaire),
     ("Customs clearance", NatureLigne.frais_dedouanement), ("Magasinage", NatureLigne.magasinage),
     ("Livraison", NatureLigne.transport), ("Handling", NatureLigne.manutention),
     ("Surcharge carburant", NatureLigne.surcharge), ("Frais de dossier informatique", NatureLigne.autre_prestation)],
)
def test_nature_ligne(libelle, nature):
    assert nature_ligne(libelle) is nature


def test_categorie_et_paiement():
    assert categorie_taxe("A00") is CategorieTaxe.droit and categorie_taxe("B00") is CategorieTaxe.tva
    assert categorie_taxe("A30") is CategorieTaxe.autre_taxe
    assert categorie_taxe("FPE", {"FPE": "forfait_petits_envois"}) is CategorieTaxe.forfait_petits_envois
    assert paiement_normalise("G", {"G": "autoliquide"}) is PaiementNormalise.autoliquide
    assert paiement_normalise("TVA autoliquidée") is PaiementNormalise.autoliquide
    assert paiement_normalise("Z") is PaiementNormalise.inconnu


# --- exports de déclaration -----------------------------------------------------------------------------

X1 = """<?xml version="1.0" encoding="UTF-8"?>
<DeclarationExport xmlns="urn:fictif:bench:declaration-export:1" version="1.0">
  <Avertissement>DONNÉES FICTIVES — DOCUMENT DE TEST</Avertissement>
  <Entete>
    <MRN>26FR111111111111A1</MRN><LRN>LRN-1</LRN><Version>1</Version><JeuDonnees>H1</JeuDonnees>
    <DateAcceptation>2026-08-18</DateAcceptation>
    <Importateur><Nom>SOCIETE FICTIVE SAS</Nom><TVA>{tva}</TVA><EORI>FR00012345900000</EORI></Importateur>
    <ConditionsLivraison incoterm="FOB" lieu="Shanghai"/>
    <MonnaieFacturation>USD</MonnaieFacturation><MontantTotalFacture>12540.00</MontantTotalFacture>
    <TauxChange sens="devise_par_eur" devise="USD">1.12500</TauxChange>
    <MasseBruteTotale unite="KGM">45.000</MasseBruteTotale><NombreColisTotal>3</NombreColisTotal>
    <NombreArticles>1</NombreArticles><ChampFutur>x</ChampFutur>
  </Entete>
  <DocumentsReferences><Document code="N380" reference="INV-2026-0815"/>
    <Document code="1008" reference="{tva}"/></DocumentsReferences>
  <Articles><Article numero="1"><CodeMarchandise>8471300000</CodeMarchandise><PaysOrigine>CN</PaysOrigine>
    <MontantFacture>12540.00</MontantFacture><MasseNette>40.000</MasseNette>
    <QuantiteSupplementaire unite="p/st">10</QuantiteSupplementaire>
    <Taxations>
      <Taxation type="A00" nature="ad_valorem"><BaseMontant>11146.67</BaseMontant><Taux>0</Taux>
        <Montant>0.00</Montant><MontantAPayer>0.00</MontantAPayer><ModePaiement>E</ModePaiement></Taxation>
      <Taxation type="B00" nature="ad_valorem"><BaseMontant>11146.67</BaseMontant><Taux>20</Taux>
        <Montant>2229.33</Montant><MontantAPayer>0.00</MontantAPayer><ModePaiement>G</ModePaiement></Taxation>
    </Taxations></Article></Articles>
  <Totaux><TotalDroitsTaxes>2229.33</TotalDroitsTaxes><TotalAPayer>0.00</TotalAPayer></Totaux>
</DeclarationExport>""".replace("{tva}", fab.TVA_CLIENT).encode()

X2 = (
    "#ENTETE;mrn;lrn;version;date_acceptation;importateur_nom;importateur_tva;devise_facture;"
    "montant_total_facture;taux_change;sens_taux;devise_taux;nombre_articles;total_a_payer;colonne_future\r\n"
    f"ENTETE;26FR111111111111A1;LRN-1;1;18/08/2026;SOCIETE FICTIVE SAS;{fab.TVA_CLIENT};JPY;1250000;"
    "162,50000;devise_par_eur;JPY;1;100,00;x\r\n"
    "#DOCUMENT;code;reference\r\nDOCUMENT;N380;INV-2026-0815\r\n"
    "#ARTICLE;numero;code_marchandise;designation;pays_origine;montant_facture;masse_nette;"
    "quantite_supplementaire;unite_supplementaire\r\n"
    'ARTICLE;1;6403990000;"CHAUSSURES; CUIR";CN;1250000;12,500;20;pa\r\n'
    "#TAXE;article;type;base_montant;base_quantite;base_unite;taux;nature_taux;montant;montant_a_payer;mode_paiement\r\n"
    "TAXE;1;A00;7692,31;;;8;ad_valorem;615,38;615,38;A\r\n"
    "TAXE;1;X01;;20;pa;5,00;specifique;100,00;100,00;A\r\n"
    "#TOTAL;type;montant\r\nTOTAL;A00;615,38\r\n#COMMENTAIRE;texte\r\nCOMMENTAIRE;DONNÉES FICTIVES\r\n"
).encode()


def test_fiches_du_depot_chargees():
    ids = {f.format_id for f in charger_fiches()}
    assert {"bench_x1_xml", "bench_x2_csv"} <= ids


def test_export_xml_x1():
    doc, res = _extraire(X1, "export.xml")
    assert doc.type is TypeDocument.declaration and doc.sous_type == "export_xml"
    c = res.champs
    assert c.mrn.valeur == "26FR111111111111A1" and c.date_acceptation.valeur == "2026-08-18"
    assert c.importateur.tva.valeur == fab.TVA_CLIENT and c.devise_facture.valeur == "USD"
    assert c.montant_total_facture.valeur == "12540.00" and c.montant_total_facture.unite == "USD"
    assert c.taux_change.valeur == "1.12500" and c.taux_change_sens.valeur == "devise_par_eur"
    assert c.incoterm.valeur == "FOB" and c.incoterm_lieu.valeur == "Shanghai"
    assert c.masse_brute_totale.valeur == "45.000" and c.nombre_colis_total.valeur == "3"
    a = c.articles[0]
    assert a.numero_article.valeur == "1" and a.code_marchandise.valeur == "8471300000"
    assert a.quantite_unite_supplementaire.unite_brute == "p/st"
    t0, t1 = c.taxations
    assert (t0.article.valeur, t0.type_taxe.valeur, t0.categorie, t0.paiement_normalise) == (
        "1", "A00", CategorieTaxe.droit, PaiementNormalise.differe)
    assert t1.categorie is CategorieTaxe.tva and t1.paiement_normalise is PaiementNormalise.autoliquide
    assert t1.taux_nature is TauxNature.ad_valorem and t1.montant.valeur == "2229.33" and t1.montant.unite == "EUR"
    types = [i.type for i in c.indices_autoliquidation]
    assert TypeIndiceAutoliquidation.code_1008 in types and TypeIndiceAutoliquidation.mode_paiement_tva in types
    assert c.indices_autoliquidation[0].tva.valeur == fab.TVA_CLIENT
    assert c.total_a_payer.valeur == "0.00"
    assert "element_ignore:ChampFutur" in res.avertissements  # élément inconnu ignoré et journalisé
    assert t1.montant.texte_contexte == "/DeclarationExport/Articles/Article/Taxations/Taxation[2]/Montant"
    _provenance_complete(res, doc)


def test_export_csv_x2_multi_enregistrements():
    doc, res = _extraire(X2, "export.csv")
    assert doc.type is TypeDocument.declaration and doc.sous_type == "export_csv"
    c = res.champs
    assert c.date_acceptation.valeur == "2026-08-18" and c.devise_facture.valeur == "JPY"
    assert c.montant_total_facture.valeur == "1250000" and c.taux_change.valeur == "162.50000"
    assert c.articles[0].description.valeur == "CHAUSSURES; CUIR"
    assert c.articles[0].masse_nette.valeur == "12.500"
    t0, t1 = c.taxations
    assert t0.montant.valeur == "615.38" and t0.taux.valeur == "8"
    assert t1.categorie is CategorieTaxe.autre_taxe and t1.taux_nature is TauxNature.specifique
    assert t1.base_quantite.valeur == "20" and t1.base_unite.unite_brute == "pa"
    assert [r.reference.valeur for r in c.documents_references] == ["INV-2026-0815"]
    assert "colonne_ignoree:ENTETE.colonne_future" in res.avertissements
    assert all(v.methode is Methode.csv_structure for v in res.valeurs)
    assert t0.montant.texte_contexte.startswith("bench_x2_csv:ligne ")
    _provenance_complete(res, doc)


def test_fiche_fictive_ajoutee_sans_code(tmp_path: Path):
    fiche = {
        "format_id": "fictif_simple_csv", "type": "csv",
        "detection": {"colonnes_requises": ["NUM_MRN", "VALEUR"]},
        "csv": {"separateur": ",", "separateur_decimal": "."},
        "entete": {"mrn": "NUM_MRN", "montant_total_facture": {"source": "VALEUR", "unite": "EUR"}},
        "listes": {"taxations": {"type_enregistrement": None, "cle": "CODE",
                                 "champs": {"type_taxe": "CODE", "montant": "MONTANT"}}},
    }
    (tmp_path / "fictif_simple_csv.yaml").write_text(yaml.safe_dump(fiche), "utf-8")
    fiches = charger_fiches(tmp_path)
    assert [f.format_id for f in fiches] == ["fictif_simple_csv"]
    contenu = b"NUM_MRN,VALEUR,CODE,MONTANT\n26FR333333333333C3,100.00,A00,5.00\n26FR333333333333C3,100.00,B00,21.00\n"
    doc, res = _extraire(contenu, "simple.csv", fiches=fiches)
    assert doc.type is TypeDocument.declaration
    assert res.champs.mrn.valeur == "26FR333333333333C3"
    assert [t.type_taxe.valeur for t in res.champs.taxations] == ["A00", "B00"]


def test_fiche_invalide_refusee():
    with pytest.raises(ValueError):
        FicheCorrespondance.depuis_dict({"format_id": "x", "type": "xml", "detection": {},
                                         "entete": {"champ_inexistant": "a"}})
