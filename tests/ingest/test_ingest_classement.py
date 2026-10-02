"""Classement page par page (§7.2, §5.3, P2) et découpage en documents logiques."""

from __future__ import annotations

import fabriques as fab
import pytest

from controldone.ids import IdGenerator
from controldone.ingest import (
    CONTINUATION,
    OptionsPages,
    classer_page,
    cle_classement,
    decouper_fichier,
    extraire_pages,
    extraire_refs,
    recevoir_octets,
)
from controldone.model.enums import MotifNonExploitable, TypeDocument

LOCAL = OptionsPages(isoler=False)


def _classer(lignes, titre=None, numero=1):
    p = extraire_pages(fab.pdf([lignes], titres=[titre]), type_mime="application/pdf", options=LOCAL)[0]
    return classer_page(p.texte, numero_dans_fichier=numero)


def _decouper(contenu: bytes, nom: str = "f.pdf"):
    rec = recevoir_octets([(nom, contenu)], ids=IdGenerator.deterministe(3))
    fr = rec.fichiers[0]
    return decouper_fichier(fr.fichier, fr.contenu, options=LOCAL, ids=IdGenerator.deterministe(4),
                            corps_courriel=fr.corps_courriel)


@pytest.mark.parametrize(
    ("lignes", "titre", "type_", "sous_type"),
    [
        (fab.FACTURE_COMMERCIALE, "COMMERCIAL INVOICE", TypeDocument.facture_commerciale, "facture"),
        (fab.FACTURE_COMMERCIALE, "PROFORMA INVOICE", TypeDocument.facture_commerciale, "pro_forma"),
        ([*fab.FACTURE_COMMERCIALE, "Value for customs purposes only"], "INVOICE",
         TypeDocument.facture_commerciale, "valeur_douane_seulement"),
        (fab.FACTURE_TRANSITAIRE, "FACTURE", TypeDocument.facture_transitaire, None),
        (fab.DECLARATION, "DÉCLARATION EN DOUANE (DAU)", TypeDocument.declaration, "h1"),
        (fab.DECLARATION, None, TypeDocument.declaration, "h1"),
        (fab.AVOIR, "CREDIT NOTE", TypeDocument.avoir, None),
        (fab.CONDITIONS_GENERALES, "CONDITIONS GÉNÉRALES DE VENTE", TypeDocument.document_support,
         "conditions_generales"),
        (fab.LETTRE, None, TypeDocument.document_support, "lettre_accompagnement"),
        (fab.LTA, "AIR WAYBILL", TypeDocument.document_support, "titre_transport"),
        (fab.PACKING_LIST, "PACKING LIST", TypeDocument.document_support, "liste_colisage"),
        (["Factura N° FAC-77", "Vendedor: FICTICIA SL", "Descripción Cantidad Precio unitario Importe",
          "Zapatos 10 25,00 250,00", "País de origen: ES", "Total factura 250,00 EUR"], "FACTURA COMERCIAL",
         TypeDocument.facture_commerciale, "facture"),
    ],
)
def test_types(lignes, titre, type_, sous_type):
    c = classer_page(extraire_pages(fab.pdf([lignes], titres=[titre]), type_mime="application/pdf",
                                    options=LOCAL)[0].texte)
    assert c.type == type_ and c.sous_type == sous_type
    assert c.confiance >= 0.7


def test_facture_avec_reference_de_transport_reste_une_facture():
    c = _classer([*fab.FACTURE_COMMERCIALE, "Air Waybill / LTA : 176-12345675", "Bill of lading BL-FICTIF-1"],
                 "COMMERCIAL INVOICE")
    assert c.type is TypeDocument.facture_commerciale


def test_nom_de_transporteur_ne_fait_pas_une_facture_transitaire():
    lignes = [*fab.FACTURE_COMMERCIALE, "Carrier: FICTIF EXPRESS WORLDWIDE - transport by air freight",
              "Forwarder: FICTIF LOGISTICS (shipping agent)"]
    assert _classer(lignes, "INVOICE").type is TypeDocument.facture_commerciale


def test_avoir_par_total_negatif():
    lignes = [*fab.FACTURE_TRANSITAIRE[:-1], "Total HT -65,00   TVA -13,00   Total TTC -78,00"]
    c = _classer(lignes, "FACTURE")
    assert c.type is TypeDocument.avoir and "avoir_total_negatif" in c.indices
    # une remise négative sur une ligne n'est pas un total négatif
    lignes = [*fab.FACTURE_COMMERCIALE[:-1], "Discount -50.00", "TOTAL AMOUNT DUE USD 12,490.00"]
    assert _classer(lignes, "COMMERCIAL INVOICE").type is TypeDocument.facture_commerciale


@pytest.mark.parametrize(
    ("lignes", "titre", "motif"),
    [
        (fab.DEVIS, "DEVIS", MotifNonExploitable.devis),
        (["Order No PO-1234", "Item qty price", "Total 1000.00"], "PURCHASE ORDER", MotifNonExploitable.bon_commande),
        (fab.FACTURE_COMMERCIALE[:3], "PRE-ALERT INVOICE", MotifNonExploitable.pre_alerte),
        (["Delivery note no 123", "Carton 3", "Laptop 10 pcs"], "DELIVERY NOTE",
         MotifNonExploitable.bon_livraison_sans_valeur),
        (["Shipping list 2026-14", "Carton 1 to 3"], "SHIPPING LIST", MotifNonExploitable.liste_expedition),
    ],
)
def test_non_exploitables(lignes, titre, motif):
    c = _classer(lignes, titre)
    assert c.type is TypeDocument.document_non_exploitable and c.motif_non_exploitable is motif


def test_pre_alerte_sans_intitule_facture_est_un_support():
    c = _classer(["Shipment notification", "AWB 176-12345675  ETA 20/08/2026"], "PRE-ALERT")
    assert c.type is TypeDocument.document_support and c.sous_type == "pre_alerte"


def test_page_sans_entete_continuation():
    c = _classer(["Page 2/2", "2  Mouse  10  12.00  120.00", "TOTAL USD 12,660.00"], None, numero=2)
    assert c.type == CONTINUATION
    c1 = _classer(["2  Mouse  10  12.00  120.00"], None, numero=1)
    assert c1.type is TypeDocument.inconnu or c1.confiance < 0.7


def test_extraire_refs():
    r = extraire_refs("INVOICE No: INV-2026-0815\nMRN 26FR000000000001A1 Page 1/3")
    assert r.numero_facture == "INV20260815" and r.mrns == ("26FR000000000001A1",)
    assert (r.page_n, r.page_total) == (1, 3)
    assert extraire_refs("Montant total facturé : 12540,00 USD").numero_facture is None
    assert extraire_refs("Facture N° FT-2026-00042").numero_facture == "FT202600042"


def test_pdf_fusionne_decoupe():
    pages = [fab.FACTURE_COMMERCIALE, ["Page 2/2", "2  Mouse  10  12.00  120.00"], fab.CONDITIONS_GENERALES,
             fab.DECLARATION, [*fab.DECLARATION[:1], "suite des articles", "Article 2 Code marchandise 8471600000"],
             [x.replace("26FR000000000001A1", "26FR222222222222B7") for x in fab.DECLARATION],
             fab.FACTURE_TRANSITAIRE]
    titres = ["COMMERCIAL INVOICE", None, "CONDITIONS GÉNÉRALES", "DAU", None, "DAU", "FACTURE"]
    r = _decouper(fab.pdf(pages, titres=titres), "fusion.pdf")
    resume = [(d.type.value, [p.numero for p in d.pages]) for d in r.documents]
    assert resume == [
        ("facture_commerciale", [1, 2]),
        ("document_support", [3]),
        ("declaration", [4, 5]),
        ("declaration", [6]),
        ("facture_transitaire", [7]),
    ]
    assert all(p.qualite_texte is not None for d in r.documents for p in d.pages)
    assert len({d.identite for d in r.documents}) == 5


def test_continuation_avec_nouveau_mrn_commence_un_document():
    p1 = fab.DECLARATION
    p2 = ["MRN : 26FR999999999999Z9", "Article 1 Code marchandise 6403990000"]
    r = _decouper(fab.pdf([p1, p2], titres=["DAU", None]))
    assert [(d.type.value, [p.numero for p in d.pages]) for d in r.documents] == [
        ("declaration", [1]), ("declaration", [2])]


def test_nouveau_numero_de_facture_commence_un_document():
    a = fab.FACTURE_COMMERCIALE
    b = [x.replace("INV-2026-0815", "INV-2026-0999") for x in fab.FACTURE_COMMERCIALE]
    r = _decouper(fab.pdf([a, b], titres=["COMMERCIAL INVOICE", "COMMERCIAL INVOICE"]))
    assert [[p.numero for p in d.pages] for d in r.documents] == [[1], [2]]
    c = [*fab.FACTURE_COMMERCIALE[:1], "Page 2/2", "Total gross weight 45 kg"]
    r = _decouper(fab.pdf([a, c], titres=["COMMERCIAL INVOICE", "COMMERCIAL INVOICE"]))
    assert [[p.numero for p in d.pages] for d in r.documents] == [[1, 2]]


def test_document_entier_identite_sha_fichier_et_confiance_basse_inconnu():
    r = _decouper(fab.pdf([fab.FACTURE_COMMERCIALE], titres=["COMMERCIAL INVOICE"]))
    assert len(r.documents) == 1 and len(r.documents[0].identite) == 64
    r = _decouper(fab.pdf([["Lorem 12 ipsum 45.00", "dolor 7"]]))
    assert r.documents[0].type is TypeDocument.inconnu
    assert r.documents[0].champs is None


def test_corps_de_courriel_et_structure():
    client = __import__("controldone.model.referentiel", fromlist=["Client"]).Client(
        id="cli_" + "3" * 32, raison_sociale="CLIENT FICTIF", expediteurs_autorises=["@fictif.invalid"])
    from controldone.ingest import recevoir_courriel

    rec = recevoir_courriel(fab.eml(expediteur="a@fictif.invalid", sujet="Facture", corps="Facture n° 12 ci-jointe",
                                    pieces={"f.xml": fab.cii()}), client=client)
    types = {}
    for fr in rec.a_traiter():
        r = decouper_fichier(fr.fichier, fr.contenu, options=LOCAL, corps_courriel=fr.corps_courriel)
        types[fr.fichier.nom_original.rsplit(".", 1)[-1]] = (r.documents[0].type.value, r.documents[0].sous_type)
    assert types == {"eml": ("document_support", "courriel"), "xml": ("facture_commerciale", "facture")}


def test_xml_inconnu_jamais_classe_avec_certitude():
    r = _decouper(b"<?xml version='1.0'?><Facture><Invoice>12</Invoice><Total>10</Total></Facture>", "x.xml")
    assert r.documents[0].type is TypeDocument.inconnu


def test_cle_classement_stable():
    assert cle_classement(["a", "b"]) == cle_classement(["a", "b"]) != cle_classement(["b", "a"])
