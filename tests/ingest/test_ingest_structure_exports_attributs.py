"""Exports de déclaration décrits par fiche de correspondance (§5.3.6) : XML à attributs et CSV dénormalisé
(fiches ``g2_m5_xml`` et ``g2_m6_csv``), et options génériques des fiches (ligne de commentaire, cellule à
éclater, élément requis, valeurs traduites) — D-1801, D-1802. Contenus **fictifs** écrits ici.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from controldone.extract.base import ExtractionContext
from controldone.ids import IdGenerator
from controldone.ingest import (
    ExtracteurDeclarationExport,
    OptionsPages,
    charger_fiches,
    decouper_fichier,
    recevoir_octets,
)
from controldone.model.enums import (
    CategorieTaxe,
    Methode,
    PaiementNormalise,
    TauxNature,
    TypeDocument,
    TypeIndiceAutoliquidation,
)

LOCAL = OptionsPages(isoler=False)
MRN = "26FRQ7ZK3M5T8W2N4B"


def _extraire(contenu: bytes, nom: str, fiches=None):
    rec = recevoir_octets([(nom, contenu)])
    fr = rec.fichiers[0]
    r = decouper_fichier(fr.fichier, fr.contenu, options=LOCAL, fiches=fiches)
    doc = r.documents[0]
    assert doc.type is TypeDocument.declaration
    ctx = ExtractionContext(
        contenu_fichier=fr.contenu, type_mime=fr.fichier.type_mime, ids=IdGenerator.deterministe(4)
    )
    ex = ExtracteurDeclarationExport(fiches)
    assert ex.supports(doc, r.pages)
    return doc, ex.extract(doc, r.pages, ctx)


XML_ATTRIBUTS = f"""<?xml version='1.0' encoding='UTF-8'?>
<dedouanement xmlns="urn:fictif:g2:dedouanement:2" version="2.0">
  <mention>DONNÉES FICTIVES — test</mention>
  <dossier mrn="{MRN}" lrn="LRN-T-1" rang="2" jeu="H1" acceptee-le="2026-05-04">
    <acteurs>
      <importateur tva="FR01000424242" eori="FR00042424200000">Atelier Fictif SARL</importateur>
      <declarant tva="FR61000515151" representation="directe">Transit Imaginaire SAS</declarant>
    </acteurs>
    <livraison incoterm="FOB" lieu="Ningbo" expedition="CN"/>
    <facturation monnaie="USD" total="1000.00">
      <conversion monnaie="USD" expression="unites_devise_pour_un_euro">1.16000</conversion>
    </facturation>
    <colisage masse-brute-kg="12.500" colis="3" positions="1"/>
    <pieces>
      <piece code="N380">INV-T-1</piece>
      <piece code="1008">FR01000424242</piece>
    </pieces>
    <positions>
      <position rang="1">
        <nomenclature>8467210000</nomenclature>
        <libelle>Perceuse fictive</libelle>
        <origine>CN</origine>
        <preference>100</preference>
        <regime complementaire="000">4000</regime>
        <montant-facture>1000.00</montant-facture>
        <valeur-statistique>862.07</valeur-statistique>
        <masse nette="10.000" brute="12.500"/>
        <quantite unite="p/st">4</quantite>
        <colis>3</colis>
        <impositions>
          <imposition code="A00" assiette="862.07" taux="2.7" mode-calcul="ad_valorem" montant="23.28"
                      exigible="23.28" paiement="E"/>
          <imposition code="B00" assiette="885.35" taux="20" mode-calcul="ad_valorem" montant="177.07"
                      exigible="0.00" paiement="G"/>
        </impositions>
      </position>
    </positions>
    <impositions-globales>
      <imposition code="FPE" assiette-quantite="1" unite-assiette="article" taux="3.00" mode-calcul="specifique"
                  montant="3.00" exigible="3.00" paiement="E" libelle="Droit forfaitaire petits envois"/>
    </impositions-globales>
    <recapitulatif>
      <total code="A00">23.28</total>
      <total-droits-taxes>203.35</total-droits-taxes>
      <total-a-acquitter>26.28</total-a-acquitter>
    </recapitulatif>
  </dossier>
</dedouanement>
""".encode()


def test_export_xml_a_attributs():
    doc, res = _extraire(XML_ATTRIBUTS, "export.xml")
    assert doc.sous_type == "export_xml" and "fiche:g2_m5_xml@1.1.0" in res.avertissements
    c = res.champs
    assert c.mrn.valeur == MRN and c.version.valeur == "2" and c.date_acceptation.valeur == "2026-05-04"
    assert c.importateur.nom.valeur == "Atelier Fictif SARL" and c.importateur.tva.valeur == "FR01000424242"
    assert (c.devise_facture.valeur, c.montant_total_facture.valeur, c.montant_total_facture.unite) == (
        "USD",
        "1000.00",
        "USD",
    )
    assert c.taux_change.valeur == "1.16000" and c.taux_change_sens.valeur == "devise_par_eur"
    assert c.taux_change_sens.valeur_brute == "unites_devise_pour_un_euro"  # valeur brute : celle du fichier
    a = c.articles[0]
    assert (a.masse_nette.valeur, a.masse_brute.valeur, a.quantite_unite_supplementaire.valeur) == (
        "10.000",
        "12.500",
        "4",
    )
    t_a00, t_b00, t_fpe = c.taxations
    assert t_a00.article.valeur == "1" and t_b00.paiement_normalise is PaiementNormalise.autoliquide
    # taxation de niveau déclaration : aucun article (le rang du dossier n'est pas un numéro d'article)
    assert t_fpe.article is None and t_fpe.categorie is CategorieTaxe.forfait_petits_envois
    assert t_fpe.taux_nature is TauxNature.specifique and t_fpe.base_quantite.valeur == "1"
    assert [(d.type_code.valeur, d.reference.valeur) for d in c.documents_references] == [
        ("N380", "INV-T-1"),
        ("1008", "FR01000424242"),
    ]
    assert {i.type for i in c.indices_autoliquidation} == {
        TypeIndiceAutoliquidation.code_1008,
        TypeIndiceAutoliquidation.mode_paiement_tva,
    }
    assert all(v.methode is Methode.xml_structure and v.confiance == 1.0 for v in res.valeurs)
    # D-3101 : total imprimé par code, porté à part (jamais une ligne de taxation)
    assert [(t.type_taxe.valeur, t.montant.valeur) for t in c.totaux_par_code] == [("A00", "23.28")]
    assert len(c.taxations) == 3


_COLONNES = (
    "mrn;lrn;rang;date_acceptation;importateur;tva_importateur;eori_importateur;declarant;tva_declarant;"
    "incoterm;lieu_livraison;pays_expedition;monnaie_facture;total_facture;taux_change;base_taux;"
    "masse_brute_totale;colis_total;nb_positions;pieces_jointes;position;code_nc;designation;origine;"
    "preference;regime;montant_facture_position;valeur_statistique;masse_nette;masse_brute;quantite;"
    "unite_quantite;colis_position;type_imposition;libelle_imposition;assiette;assiette_quantite;"
    "unite_assiette;taux;mode_calcul;montant;montant_exigible;mode_paiement;total_droits_taxes;"
    "total_a_acquitter"
)
_ENTETE = (
    f"{MRN};LRN-T-2;1;04/05/2026;Atelier Fictif SARL;FR01000424242;FR00042424200000;Transit Imaginaire SAS;"
    "FR61000515151;FOB;Ningbo;CN;EUR;1000,50;1,16000;1EUR;30,500;4;2;N380:INV-T-2|N705:BL-T-2|"
    "1008:FR01000424242"
)


def _csv() -> bytes:
    entete = _ENTETE
    lignes = [
        "# Export fictif — DONNÉES FICTIVES — séparateur ; décimales virgule",
        _COLONNES,
        f"{entete};1;8467210000;Perceuse fictive réf. A;CN;100;4000;900,50;776,29;10,000;12,000;4;p/st;3;"
        "A00;Droits de douane;776,29;;;2,7;ad_valorem;20,96;20,96;DIFFERE;201,37;23,96",
        f"{entete};1;8467210000;Perceuse fictive réf. A;CN;100;4000;900,50;776,29;10,000;12,000;4;p/st;3;"
        "B00;TVA import;797,25;;;20;ad_valorem;159,45;0;AUTOLIQUIDATION;201,37;23,96",
        f"{entete};2;8203200000;Pince fictive;CN;100;4000;100,00;86,21;5,000;6,000;10;p/st;1;"
        ";;;;;;;;;;201,37;23,96",
        f"{entete};;;;;;;;;;;;;;FPE;Forfait petits envois;;2;article;1,50;specifique;3,00;3,00;COMPTANT;201,37;"
        "23,96",
        "# commentaire final : ignorer cette ligne",
    ]
    return ("\r\n".join(lignes) + "\r\n").encode("cp1252")


def test_export_csv_denormalise_commentaire_virgule_decimale():
    doc, res = _extraire(_csv(), "export.csv")
    assert doc.sous_type == "export_csv" and "fiche:g2_m6_csv@1.0.0" in res.avertissements
    c = res.champs
    assert c.mrn.valeur == MRN and c.date_acceptation.valeur == "2026-05-04"
    assert c.montant_total_facture.valeur == "1000.50" and c.taux_change.valeur == "1.16000"
    assert c.taux_change_sens.valeur == "devise_par_eur"
    # colonnes d'article répétées sur chaque ligne de taxation : un article par position
    assert [a.numero_article.valeur for a in c.articles] == ["1", "2"]
    assert c.articles[0].masse_brute.valeur == "12.000"
    # article sans taxation propre (colonnes vides) : pas de ligne de taxation ; FPE sans article
    assert [(t.article.valeur if t.article else None, t.type_taxe.valeur) for t in c.taxations] == [
        ("1", "A00"),
        ("1", "B00"),
        (None, "FPE"),
    ]
    assert c.taxations[1].paiement_normalise is PaiementNormalise.autoliquide
    assert c.taxations[2].paiement_normalise is PaiementNormalise.comptant
    assert c.taxations[2].taux_nature is TauxNature.specifique
    # documents « code:référence » d'une seule cellule
    assert [(d.type_code.valeur, d.reference.valeur) for d in c.documents_references] == [
        ("N380", "INV-T-2"),
        ("N705", "BL-T-2"),
        ("1008", "FR01000424242"),
    ]
    assert c.indices_autoliquidation
    assert all(v.methode is Methode.csv_structure for v in res.valeurs)


def test_options_generiques_fiche_csv(tmp_path: Path):
    """Options ajoutées sans code propre à un format : ``csv.commentaire``, ``eclater``, ``requis``, ``valeurs``."""
    fiche = {
        "format_id": "fictif_options_csv",
        "type": "csv",
        "detection": {"colonnes_requises": ["REF", "DOCS"]},
        "csv": {"separateur": ";", "separateur_decimal": ".", "commentaire": "//"},
        "entete": {"mrn": "REF", "taux_change_sens": {"source": "SENS", "valeurs": {"A": "eur_par_devise"}}},
        "listes": {
            "documents_references": {
                "eclater": {"source": "DOCS", "separateur": "+", "motif": "(?P<c>[^=]+)=(?P<r>.+)"},
                "champs": {"type_code": "c", "reference": "r"},
            },
            "taxations": {"requis": "CODE", "champs": {"type_taxe": "CODE", "montant": "MT"}},
        },
    }
    (tmp_path / "fictif_options_csv.yaml").write_text(yaml.safe_dump(fiche), "utf-8")
    fiches = charger_fiches(tmp_path)
    contenu = (
        b"// mention fictive, ignoree\nREF;SENS;DOCS;CODE;MT\n"
        b"26FR333333333333C3;A;N380=F-1+N740=L-2;A00;5.00\n26FR333333333333C3;A;N380=F-1+N740=L-2;;\n"
        b"26FR333333333333C3;A;N380=F-1+N740=L-2;B00;20.00\n"
    )
    _doc, res = _extraire(contenu, "options.csv", fiches=fiches)
    c = res.champs
    assert c.mrn.valeur == "26FR333333333333C3" and c.taux_change_sens.valeur == "eur_par_devise"
    assert [(d.type_code.valeur, d.reference.valeur) for d in c.documents_references] == [
        ("N380", "F-1"),
        ("N740", "L-2"),
    ]
    assert [t.type_taxe.valeur for t in c.taxations] == ["A00", "B00"]


def test_fiches_livrees_valides():
    noms = {f.format_id for f in charger_fiches()}
    assert {"bench_x1_xml", "bench_x2_csv", "g2_m5_xml", "g2_m6_csv"} <= noms


XML_DEDUIT = f"""<?xml version='1.0' encoding='UTF-8'?>
<CustomsEntry xmlns="urn:fictif:test:customs-entry:9">
  <Notice>DONNÉES FICTIVES — test</Notice>
  <Header>
    <MRN>{MRN}</MRN>
    <AcceptanceDate>2026-05-04</AcceptanceDate>
    <InvoiceCurrency>EUR</InvoiceCurrency>
    <InvoiceTotal>300.00</InvoiceTotal>
    <ItemCount>2</ItemCount>
  </Header>
  <Items>
    <Item seq="1"><CommodityCode>8467210000</CommodityCode><InvoicedAmount currency="EUR">200.00</InvoicedAmount></Item>
    <Item seq="2"><CommodityCode>8205200000</CommodityCode><InvoicedAmount currency="EUR">100.00</InvoicedAmount></Item>
  </Items>
  <Duties>
    <Duty item="1" type="A00" label="Customs duty"><Base>200.00</Base><Rate>2.7</Rate><Amount>5.40</Amount></Duty>
    <Duty item="1" type="B00" label="Import VAT"><Base>205.40</Base><Rate>20</Rate><Amount>41.08</Amount></Duty>
    <Duty item="2" type="A00" label="Customs duty"><Base>100.00</Base><Rate>3.7</Rate><Amount>3.70</Amount></Duty>
    <Duty item="2" type="B00" label="Import VAT"><Base>103.70</Base><Rate>20</Rate><Amount>20.74</Amount></Duty>
  </Duties>
  <Summary>
    <TypeTotal type="A00">9.10</TypeTotal>
    <TypeTotal type="B00">61.82</TypeTotal>
    <TotalDutiesAndTaxes>70.92</TotalDutiesAndTaxes>
  </Summary>
</CustomsEntry>
""".encode()


def test_export_xml_deduit_totaux_par_code():
    # D-3101 : fiche déduite des noms d'éléments ; « TypeTotal type=… » est le total imprimé du code
    _, res = _extraire(XML_DEDUIT, "customs_entry.xml", fiches=())
    c = res.champs
    assert any(a.startswith("fiche_deduite") for a in res.avertissements)
    assert [(t.type_taxe.valeur, t.montant.valeur) for t in c.totaux_par_code] == [
        ("A00", "9.10"),
        ("B00", "61.82"),
    ]
    assert len(c.taxations) == 4 and all(t.article is not None for t in c.taxations)


def test_export_csv_x2_totaux_par_code():
    contenu = (
        "#ENTETE;mrn;lrn;version;date_acceptation;importateur_nom;importateur_tva;importateur_eori;declarant_nom;"
        "declarant_tva;incoterm;incoterm_lieu;pays_expedition;devise_facture;montant_total_facture;taux_change;"
        "sens_taux;devise_taux;masse_brute_totale;nombre_colis_total;nombre_articles;total_droits_taxes;total_a_payer\n"
        f"ENTETE;{MRN};LRN-T-3;1;04/05/2026;Atelier Fictif SARL (FICTIF);FR01000424242;FR00042424200000;"
        "Transit Imaginaire SAS (FICTIF);FR61000515151;FOB;Ningbo;CN;EUR;200,00;;;;10,000;2;1;45,40;45,40\n"
        "#TAXE;article;type;base_montant;base_quantite;base_unite;taux;nature_taux;montant;montant_a_payer;mode_paiement\n"
        "TAXE;1;A00;200,00;;;2,7;ad_valorem;5,40;5,40;E\n"
        "TAXE;1;B00;200,00;;;20;ad_valorem;40,00;40,00;E\n"
        "#TOTAL;type;montant\n"
        "TOTAL;A00;5,40\n"
        "TOTAL;B00;40,00\n"
    ).encode()
    _, res = _extraire(contenu, "export_declaration.csv")
    c = res.champs
    assert "fiche:bench_x2_csv@1.1.0" in res.avertissements
    assert [(t.type_taxe.valeur, t.montant.valeur) for t in c.totaux_par_code] == [
        ("A00", "5.40"),
        ("B00", "40.00"),
    ]
    assert len(c.taxations) == 2
