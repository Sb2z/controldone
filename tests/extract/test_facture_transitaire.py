"""Extracteur déterministe des factures de transitaire et avoirs de transitaire (SPEC §5.3.3, §5.3.4).

Documents **fictifs** rendus par reportlab dans les tests (sociétés, numéros et adresses inventés).
"""

from __future__ import annotations

import io
from decimal import Decimal

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from controldone.extract.base import Extracteur, ExtractionContext
from controldone.extract.deterministe.facture_transitaire import ExtracteurFactureTransitaire, classer_nature
from controldone.ids import IdGenerator
from controldone.ingest.pages import OptionsPages, extraire_pages
from controldone.model.documents import Document, PageRef
from controldone.model.enums import Methode, NatureLigne, SigneImprime, TotalOrigine, TypeDocument
from controldone.model.referentiel import Entite
from controldone.normalize.fiscal import tva_fr_depuis_siren

TVA_TRANSITAIRE = tva_fr_depuis_siren("000616383")
TVA_CLIENT = tva_fr_depuis_siren("000714980")
MRN_1 = "26FRF18L6C7QDZYU4X"
MRN_2 = "26FRK7G7KR9KVHGNG3"
MRN_3 = "26FR6V95LB0NUEERWD"

L, H = A4


def _pdf(elements: list[tuple[float, float, str, str]]) -> bytes:
    """Éléments ``(x, y, texte, alignement)`` en fractions de page (origine en haut à gauche) ;
    alignement ``g`` (gauche) ou ``d`` (droite)."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1)
    c.setFont("Helvetica", 8)
    for x, y, texte, al in elements:
        if al == "d":
            c.drawRightString(x * L, (1 - y) * H, texte)
        else:
            c.drawString(x * L, (1 - y) * H, texte)
    c.showPage()
    c.save()
    return buf.getvalue()


def _extraire(contenu: bytes, type_doc: TypeDocument = TypeDocument.facture_transitaire, entites=()):
    extraites = extraire_pages(contenu, options=OptionsPages(ocr=False, isoler=False))
    pages = [pe.page for pe in extraites]
    doc = Document(type=type_doc, pages=[PageRef(fichier_id=p.fichier_id, numero=p.numero,
                                                  qualite_texte=p.qualite_texte) for p in pages])
    ctx = ExtractionContext(ids=IdGenerator.deterministe(7), entites=tuple(entites),
                            options={"textes_pages": {pe.page.numero: pe.texte for pe in extraites}})
    ex = ExtracteurFactureTransitaire()
    assert ex.supports(doc, pages)
    res = ex.extract(doc, pages, ctx)
    assert res.champs is not None
    return res.champs


def _entete(titre: str, numero: str, *, client_label: str = "Client facturé") -> list:
    return [
        (0.07, 0.04, "Transitaire Démo Alpha SAS (FICTIF)", "g"),
        (0.93, 0.04, titre, "d"),
        (0.07, 0.055, "13 avenue du Fret Imaginaire, 52999 Villefictive-Port", "g"),
        (0.07, 0.07, f"TVA {TVA_TRANSITAIRE}", "g"),
        (0.93, 0.07, numero, "d"),
        (0.07, 0.10, "Date", "g"), (0.20, 0.10, "08/08/2026", "g"), (0.55, 0.10, client_label, "g"),
        (0.07, 0.115, "Échéance", "g"), (0.20, 0.115, "07/09/2026", "g"),
        (0.55, 0.115, "Cap Horizon Outillage SARL (FICTIF)", "g"),
        (0.07, 0.13, "LTA / BL", "g"), (0.20, 0.13, "999-20278075", "g"),
        (0.55, 0.13, "33 route du Prototype", "g"),
        (0.07, 0.145, "MRN", "g"), (0.20, 0.145, MRN_1, "g"), (0.55, 0.145, "44999 Nantes-Démo", "g"),
        (0.55, 0.16, f"N° TVA {TVA_CLIENT}", "g"),
        (0.07, 0.175, "Fact. fournisseur", "g"), (0.20, 0.175, "EXP-26-00230 ; EXP-26-00231", "g"),
        (0.18, 0.95, "Transitaire Démo Alpha SAS (FICTIF) - RCS Démo 000616383 - IBAN FR00 0000 0000 (FICTIF)", "g"),
    ]


def _facture_ventilee() -> bytes:
    """Débours ventilés (droits, autres taxes, forfait) + prestations, lettres de statut TVA, légende."""
    el = _entete("FACTURE", "FA-2610161")
    el += [
        (0.07, 0.21, "DÉBOURS (sommes payées pour votre compte)", "g"),
        (0.08, 0.23, "Désignation", "g"), (0.40, 0.23, "MRN", "g"), (0.70, 0.23, "TVA", "g"),
        (0.93, 0.23, "Montant", "d"),
        (0.08, 0.25, "Droits de douane", "g"), (0.40, 0.25, MRN_1, "g"), (0.71, 0.25, "E", "g"),
        (0.93, 0.25, "1 202,05", "d"),
        (0.08, 0.27, "Autres taxes", "g"), (0.40, 0.27, MRN_1, "g"), (0.71, 0.27, "E", "g"),
        (0.93, 0.27, "510,30", "d"),
        (0.08, 0.29, "Droit forfaitaire petits envois", "g"), (0.40, 0.29, MRN_1, "g"), (0.71, 0.29, "E", "g"),
        (0.93, 0.29, "12,00", "d"),
        (0.60, 0.31, "Total débours", "g"), (0.93, 0.31, "1 724,35", "d"),
        (0.07, 0.34, "PRESTATIONS", "g"),
        (0.08, 0.36, "Désignation", "g"), (0.36, 0.36, "Détail", "g"), (0.60, 0.36, "Qté", "d"),
        (0.70, 0.36, "PU HT", "d"), (0.80, 0.36, "Montant HT", "d"), (0.86, 0.36, "TVA", "g"),
        (0.08, 0.38, "Frais de dédouanement", "g"), (0.60, 0.38, "1", "d"), (0.70, 0.38, "62,50", "d"),
        (0.80, 0.38, "62,50", "d"), (0.86, 0.38, "20 %", "g"), (0.92, 0.38, "N", "g"),
        (0.08, 0.40, "Frais d'avance de fonds", "g"), (0.36, 0.40, "3 % x 1 724,35 (min. 25,00)", "g"),
        (0.60, 0.40, "1", "d"), (0.70, 0.40, "51,73", "d"), (0.80, 0.40, "51,73", "d"),
        (0.86, 0.40, "20 %", "g"), (0.92, 0.40, "N", "g"),
        (0.08, 0.42, "Magasinage", "g"), (0.36, 0.42, "23/07/2026 - 02/08/2026", "g"), (0.60, 0.42, "6", "d"),
        (0.70, 0.42, "15,00", "d"), (0.80, 0.42, "90,00", "d"), (0.86, 0.42, "20 %", "g"),
        (0.92, 0.42, "N", "g"),
        (0.60, 0.45, "Total prestations HT", "g"), (0.93, 0.45, "204,23", "d"),
        (0.60, 0.47, "Total HT", "g"), (0.93, 0.47, "1 928,58", "d"),
        (0.60, 0.49, "TVA 20 %", "g"), (0.93, 0.49, "40,85", "d"),
        (0.60, 0.51, "Total TTC", "g"), (0.93, 0.51, "1 969,43", "d"),
        (0.60, 0.53, "Net à payer", "g"), (0.93, 0.53, "1 969,43", "d"),
        (0.07, 0.56, "Codes TVA : E = exonéré / hors champ (débours) ; N = normal 20 %.", "g"),
    ]
    return _pdf(el)


@pytest.fixture(scope="module")
def ventilee():
    return _extraire(_facture_ventilee())


def test_protocole():
    assert isinstance(ExtracteurFactureTransitaire(), Extracteur)


def test_entete_parties_et_references(ventilee):
    c = ventilee
    assert c.numero.valeur == "FA-2610161" and c.numero.ancree and c.numero.page == 1
    assert c.date.valeur == "2026-08-08"
    # la TVA du transitaire et celle du client ne sont jamais interverties
    assert c.emetteur.tva.valeur == TVA_TRANSITAIRE
    assert c.client_facture.tva.valeur == TVA_CLIENT
    assert c.emetteur.tva.confiance >= 0.9 and c.client_facture.tva.confiance >= 0.9
    assert c.client_facture.nom.valeur == "Cap Horizon Outillage SARL (FICTIF)"
    assert [v.valeur for v in c.refs_mrn] == [MRN_1]
    assert [v.valeur for v in c.refs_transport] == ["999-20278075"]
    assert [v.valeur for v in c.refs_facture_commerciale] == ["EXP-26-00230", "EXP-26-00231"]
    assert c.est_releve is False
    for v in (c.numero, c.date, c.emetteur.tva, c.client_facture.tva, *c.refs_mrn):
        assert v.methode is Methode.texte_natif and v.zone is not None and v.valeur_brute


def test_lignes_nature_et_marqueurs(ventilee):
    lignes = ventilee.lignes
    natures = [lg.nature for lg in lignes]
    assert natures == [NatureLigne.debours_droits, NatureLigne.debours_autres_taxes,
                       NatureLigne.debours_forfait_petits_envois, NatureLigne.frais_dedouanement,
                       NatureLigne.frais_avance_fonds, NatureLigne.magasinage]
    assert [lg.montant_ht.valeur for lg in lignes] == ["1202.05", "510.30", "12.00", "62.50", "51.73", "90.00"]
    droits = lignes[0]
    # la lettre de statut est un marqueur, jamais un montant ; le taux vient de la légende (valeur dérivée)
    assert droits.marqueur_tva.valeur == "E"
    assert droits.taux_tva.valeur == "0" and droits.taux_tva.methode is Methode.derive
    assert droits.taux_tva.confiance <= 0.6
    assert droits.mrn.valeur == MRN_1
    assert droits.quantite.valeur == "1" and droits.quantite.methode is Methode.derive
    fonds = lignes[4]
    assert fonds.pourcentage.valeur == "3" and fonds.taux_tva.valeur == "20"
    assert fonds.montant_tva.valeur == "10.35" and fonds.montant_tva.methode is Methode.derive
    mag = lignes[5]
    assert (mag.quantite.valeur, mag.prix_unitaire.valeur) == ("6", "15.00")
    assert (mag.date_debut.valeur, mag.date_fin.valeur) == ("2026-07-23", "2026-08-02")
    # une ligne de libellé MRN unique : le MRN de l'en-tête est rattaché (confiance de rattachement)
    assert lignes[3].mrn.valeur == MRN_1 and lignes[3].mrn.confiance < 0.9


def test_totaux_imprimes(ventilee):
    c = ventilee
    assert c.total_debours.valeur == "1724.35" and c.total_debours.total_origine is TotalOrigine.imprime
    assert c.total_ht.valeur == "1928.58" and c.total_tva.valeur == "40.85"
    assert c.total_ttc.valeur == "1969.43" and c.net_a_payer.valeur == "1969.43"
    # « Total prestations HT » n'est pas le total HT
    assert c.total_ht.valeur_brute == "1 928,58"


def test_droits_et_taxes_combines_et_total_reconstruit():
    el = _entete("FACTURE", "N° F-2610140")
    el += [
        (0.08, 0.23, "Désignation", "g"), (0.36, 0.23, "Référence", "g"), (0.62, 0.23, "Qté", "d"),
        (0.76, 0.23, "Montant HT", "d"), (0.82, 0.23, "TVA", "g"),
        (0.08, 0.25, "Droits et taxes (débours)", "g"), (0.36, 0.25, MRN_1, "g"), (0.62, 0.25, "1", "d"),
        (0.76, 0.25, "1 047,60", "d"), (0.82, 0.25, "0 - 0 %", "g"),
        (0.08, 0.27, "Droits et taxes (débours)", "g"), (0.36, 0.27, MRN_2, "g"), (0.62, 0.27, "1", "d"),
        (0.76, 0.27, "3 332,96", "d"), (0.82, 0.27, "0 - 0 %", "g"),
        (0.08, 0.29, "Frais de dédouanement", "g"), (0.36, 0.29, MRN_1, "g"), (0.62, 0.29, "1", "d"),
        (0.76, 0.29, "62,50", "d"), (0.82, 0.29, "1 - 20 %", "g"),
        (0.08, 0.31, "Livraison", "g"), (0.62, 0.31, "1", "d"),
        (0.76, 0.31, "140,00", "d"), (0.82, 0.31, "1 - 20 %", "g"),
        (0.60, 0.34, "Total HT", "g"), (0.93, 0.34, "4 583,06", "d"),
        (0.60, 0.36, "Total TVA", "g"), (0.93, 0.36, "40,50", "d"),
        (0.60, 0.38, "Total TTC", "g"), (0.93, 0.38, "4 623,56", "d"),
        (0.07, 0.41, "TVA : 0 = débours non soumis ; 1 = taux normal 20 %.", "g"),
    ]
    c = _extraire(_pdf(el))
    assert c.numero.valeur == "F-2610140"
    assert [lg.nature for lg in c.lignes[:2]] == [NatureLigne.debours_combines] * 2
    assert [lg.mrn.valeur for lg in c.lignes[:2]] == [MRN_1, MRN_2]
    # deux MRN : une ligne sans MRN imprimé n'en reçoit pas
    assert c.lignes[3].nature is NatureLigne.transport and c.lignes[3].mrn is None
    assert (c.lignes[2].marqueur_tva.valeur, c.lignes[2].taux_tva.valeur) == ("1", "20")
    # total des débours absent : reconstruit (somme des lignes de débours), confiance plafonnée
    td = c.total_debours
    assert td.valeur == "4380.56" and td.total_origine is TotalOrigine.reconstruit
    assert td.methode is Methode.derive and td.confiance <= 0.6 and len(td.derivee_de) == 2
    assert {v.valeur for v in c.refs_mrn} == {MRN_1, MRN_2}


def test_releve_mensuel_tableau_mrn():
    el = [
        (0.07, 0.03, "Transitaire Démo Delta Fret (FICTIF)", "g"), (0.93, 0.03, "RELEVÉ MENSUEL DE FACTURATION", "d"),
        (0.07, 0.05, f"TVA {TVA_TRANSITAIRE}", "g"), (0.93, 0.05, "N° REL-2026-00240", "d"),
        (0.07, 0.09, "Client facturé", "g"), (0.60, 0.09, "Date du relevé : 28/08/2026", "g"),
        (0.07, 0.105, "Lumen Industrie SAS (FICTIF)", "g"),
        (0.07, 0.12, f"N° TVA {TVA_CLIENT}", "g"),
        (0.05, 0.18, "Transport", "g"), (0.20, 0.18, "MRN", "g"), (0.38, 0.18, "Date", "g"),
        (0.56, 0.18, "Droits", "d"), (0.66, 0.18, "Autres tx", "d"), (0.77, 0.18, "Dédouan.", "d"),
        (0.92, 0.18, "Av. fonds", "d"),
        (0.05, 0.20, "DEMO168883687", "g"), (0.20, 0.20, MRN_1, "g"), (0.38, 0.20, "02/08/2026", "g"),
        (0.56, 0.20, "1 202,05", "d"), (0.66, 0.20, "510,30", "d"), (0.77, 0.20, "69,00", "d"),
        (0.92, 0.20, "34,25", "d"),
        (0.05, 0.22, "DEMO709602958", "g"), (0.20, 0.22, MRN_2, "g"), (0.38, 0.22, "11/08/2026", "g"),
        (0.56, 0.22, "802,66", "d"), (0.66, 0.22, "-", "d"), (0.77, 0.22, "69,00", "d"),
        (0.92, 0.22, "16,05", "d"),
        (0.05, 0.24, "999-70166073", "g"), (0.20, 0.24, MRN_3, "g"), (0.38, 0.24, "21/08/2026", "g"),
        (0.56, 0.24, "49,54", "d"), (0.66, 0.24, "-", "d"), (0.77, 0.24, "69,00", "d"),
        (0.92, 0.24, "15,00", "d"),
        (0.57, 0.28, "Total débours (D)", "g"), (0.93, 0.28, "2 564,55", "d"),
        (0.57, 0.30, "Total HT", "g"), (0.93, 0.30, "2 837,80", "d"),
        (0.57, 0.32, "TVA 20 % sur prestations", "g"), (0.93, 0.32, "54,65", "d"),
        (0.57, 0.34, "TOTAL TTC DU RELEVÉ", "g"), (0.93, 0.34, "2 892,45", "d"),
    ]
    c = _extraire(_pdf(el))
    assert c.est_releve is True and c.numero.valeur == "REL-2026-00240" and c.date.valeur == "2026-08-28"
    assert len(c.tableau_mrn) == 3
    assert [(t.ref_transport.valeur, t.mrn.valeur, t.date.valeur) for t in c.tableau_mrn][2] == \
        ("999-70166073", MRN_3, "2026-08-21")
    assert {v.valeur for v in c.refs_transport} == {"DEMO168883687", "DEMO709602958", "999-70166073"}
    # une ligne par montant des colonnes « par nature », rattachée au MRN de sa rangée
    assert len(c.lignes) == 10
    par = {(lg.mrn.valeur, lg.nature): lg.montant_ht.valeur for lg in c.lignes}
    assert par[(MRN_1, NatureLigne.debours_autres_taxes)] == "510.30"
    assert par[(MRN_2, NatureLigne.frais_avance_fonds)] == "16.05"
    assert (MRN_2, NatureLigne.debours_autres_taxes) not in par  # « - » : pas de ligne
    lg = next(x for x in c.lignes if x.nature is NatureLigne.frais_dedouanement)
    assert lg.taux_tva.valeur == "20" and lg.montant_tva.valeur == "13.80" and lg.montant_tva.confiance <= 0.6
    assert c.total_debours.valeur == "2564.55"


def test_avoir_montants_entre_parentheses():
    el = [
        (0.07, 0.04, "Transitaire Démo Hotel International (FICTIF)", "g"), (0.93, 0.04, "AVOIR / CREDIT NOTE", "d"),
        (0.07, 0.06, f"TVA {TVA_TRANSITAIRE}", "g"), (0.93, 0.06, "AV-2610322", "d"),
        (0.07, 0.10, "Date", "g"), (0.20, 0.10, "13/05/2026", "g"),
        (0.55, 0.10, "Brindille Cosmétiques SAS (FICTIF)", "g"),
        (0.07, 0.115, "Facture d'origine", "g"), (0.20, 0.115, "FB-2610300", "g"),
        (0.55, 0.115, "7 chemin des Échantillons", "g"),
        (0.07, 0.13, "Motif", "g"), (0.20, 0.13, "Geste commercial", "g"),
        (0.55, 0.13, f"TVA {TVA_CLIENT}", "g"),
        (0.08, 0.17, "Désignation", "g"), (0.45, 0.17, "MRN", "g"), (0.78, 0.17, "HT", "d"),
        (0.92, 0.17, "TVA", "d"),
        (0.08, 0.19, "Frais de dédouanement / Customs clearance", "g"), (0.45, 0.19, MRN_1, "g"),
        (0.78, 0.19, "(15,00)", "d"), (0.92, 0.19, "(3,00)", "d"),
        (0.57, 0.22, "Total HT / Net credited", "g"), (0.93, 0.22, "(15,00)", "d"),
        (0.57, 0.24, "TVA / VAT", "g"), (0.93, 0.24, "(3,00)", "d"),
        (0.57, 0.26, "Total TTC / Gross credited", "g"), (0.93, 0.26, "(18,00)", "d"),
        (0.18, 0.95, "Transitaire Démo Hotel International (FICTIF) - RCS Démo 000616383", "g"),
    ]
    c = _extraire(_pdf(el), TypeDocument.avoir)
    assert c.numero.valeur == "AV-2610322" and c.date.valeur == "2026-05-13"
    assert [v.valeur for v in c.refs_facture_origine] == ["FB-2610300"]
    assert c.motif.valeur == "Geste commercial"
    assert c.emetteur.tva.valeur == TVA_TRANSITAIRE
    (lg,) = c.lignes
    assert lg.nature is NatureLigne.frais_dedouanement
    # montants positifs, signe imprimé porté à part (§5.2)
    assert lg.montant_ht.valeur == "15.00" and lg.montant_ht.signe_imprime is SigneImprime.negatif
    assert c.total_credite_ttc.valeur == "18.00" and c.total_credite_ttc.signe_imprime is SigneImprime.negatif
    assert c.total_credite_ht.valeur == "15.00" and c.total_tva.valeur == "3.00"


def test_client_sans_libelle_identifie_par_entite():
    """Pas de pavé « client facturé » : l'entité du client désigne sa TVA, l'autre est celle de l'émetteur."""
    el = _entete("FACTURE", "FA-2610999", client_label="")
    el = [e for e in el if e[2] != ""]
    el += [
        (0.08, 0.23, "Désignation", "g"), (0.62, 0.23, "Qté", "d"), (0.76, 0.23, "Montant HT", "d"),
        (0.85, 0.23, "TVA", "d"),
        (0.08, 0.25, "Frais de dédouanement", "g"), (0.62, 0.25, "1", "d"), (0.76, 0.25, "62,50", "d"),
        (0.85, 0.25, "12,50", "d"),
        (0.60, 0.28, "Total HT", "g"), (0.93, 0.28, "62,50", "d"),
    ]
    entite = Entite(raison_sociale="Cap Horizon Outillage SARL (FICTIF)", tva=TVA_CLIENT)
    c = _extraire(_pdf(el), entites=[entite])
    assert c.client_facture.tva.valeur == TVA_CLIENT
    assert c.emetteur.tva.valeur == TVA_TRANSITAIRE
    lg = c.lignes[0]
    assert lg.taux_tva.valeur == "20" and lg.montant_tva.valeur == "12.50"
    # total des débours : aucune ligne de débours -> 0, reconstruit, confiance basse
    assert Decimal(c.total_debours.valeur) == 0 and c.total_debours.confiance <= 0.6


@pytest.mark.parametrize(("libelle", "nature"), [
    ("Droits de douane", NatureLigne.debours_droits),
    ("Customs duty", NatureLigne.debours_droits),
    ("Other duties and taxes", NatureLigne.debours_autres_taxes),
    ("Accises", NatureLigne.debours_autres_taxes),
    ("TVA à l'importation", NatureLigne.debours_tva),
    ("Import VAT", NatureLigne.debours_tva),
    ("Droits et taxes", NatureLigne.debours_combines),
    ("Flat duty low-value parcels", NatureLigne.debours_forfait_petits_envois),
    ("Droit forfaitaire petits envois", NatureLigne.debours_forfait_petits_envois),
    ("Frais de dédouanement", NatureLigne.frais_dedouanement),
    ("Customs clearance", NatureLigne.frais_dedouanement),
    ("Disbursement fee", NatureLigne.frais_avance_fonds),
    ("Avance de fonds / Disbursement fee", NatureLigne.frais_avance_fonds),
    ("Lignes supplémentaires", NatureLigne.frais_ligne_supplementaire),
    ("Storage", NatureLigne.magasinage),
    ("Livraison / Delivery", NatureLigne.transport),
    ("Handling", NatureLigne.manutention),
    ("Surcharge carburant", NatureLigne.surcharge),
    ("Security surcharge", NatureLigne.surcharge),
])
def test_classer_nature(libelle, nature):
    assert classer_nature(libelle) is nature


def test_classer_nature_inconnue():
    assert classer_nature("Ouverture de dossier") is None
