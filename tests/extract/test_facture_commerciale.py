"""Extracteur déterministe des factures commerciales (SPEC §5.3.1, §6.3) sur des PDF fictifs (reportlab)."""

from __future__ import annotations

import io
from decimal import Decimal

import fixtures_fc as fx
import pytest

from controldone.extract.base import anchor
from controldone.extract.deterministe import EXTRACTEURS_DETERMINISTES
from controldone.extract.deterministe._mise_en_page import (
    VueDocument,
    accepte_reference,
    inferer_separateur,
    lire_tva_mots,
    lire_tva_ocr,
    nombres_dans,
    texte_nombre,
    vue_document,
)
from controldone.extract.deterministe.facture_commerciale import (
    ExtracteurFactureCommerciale,
    extraire_facture_commerciale,
)
from controldone.ingest.texte import Ligne, Mot, PageText
from controldone.model import Document
from controldone.model.enums import Methode, QualiteTexte, TotalOrigine, TypeDocument, TypeSousTotal


def _fc(contenu: bytes, **kw):
    r = fx.extraire(contenu, TypeDocument.facture_commerciale, **kw)
    assert r.champs is not None
    return r.champs, r


# --- facture anglaise : en-tête, pavés, totaux, lignes -------------------------------------------------------


@pytest.fixture(scope="module")
def en():
    return _fc(fx.facture_en())


def test_registre_et_contrat():
    ext = EXTRACTEURS_DETERMINISTES["facture_commerciale"]
    assert isinstance(ext, ExtracteurFactureCommerciale)
    assert ext.type == "deterministe" and ext.id and ext.version
    assert not ext.supports(Document(type=TypeDocument.declaration), [])


def test_entete_en(en):
    ch, _ = en
    assert ch.numero.valeur == "INV-2026-0815"
    assert ch.date.valeur == "2026-08-14"
    assert ch.devise.valeur == "USD"
    assert ch.incoterm.valeur == "FOB" and ch.incoterm_lieu.valeur == "Felixstowe"
    assert ch.ref_transport.valeur == "DEMO123456789"
    for v in (ch.numero, ch.date, ch.devise, ch.incoterm):
        assert v.methode is Methode.texte_natif and v.ancree and v.page == 1 and v.zone is not None
        assert v.confiance >= 0.9


def test_tva_acheteur_lue_dans_le_pave_acheteur_seulement(en):
    ch, _ = en
    # la TVA du transporteur (pavé « Notify / Carrier ») et celle du vendeur ne sont jamais prises
    assert ch.acheteur.tva.valeur == fx.TVA_ACHETEUR
    assert ch.acheteur.tva.valeur_brute.startswith("FR ")  # imprimée en groupes, gardée telle quelle
    assert ch.acheteur.siren.valeur == "000123459"
    assert ch.acheteur.nom.valeur == "Lumen Industrie SAS (FICTIF)"
    assert ch.vendeur.tva.valeur == "GB000000000"
    assert ch.acheteur.tva.valeur != fx.TVA_TRANSPORTEUR


def test_total_payable_et_lignes_de_pied(en):
    ch, _ = en
    t = ch.total_facture
    assert t.decimal() == Decimal("12540.00") and t.unite == "USD"
    assert t.total_origine is TotalOrigine.imprime
    assert t.valeur_brute == "USD 12,540.00" and t.ancree
    assert t.confiance >= 0.95  # recoupé : lignes + fret − remise = total
    st = {s.type: s.montant for s in ch.sous_totaux}
    assert st[TypeSousTotal.marchandises].decimal() == Decimal("11540.00")
    assert st[TypeSousTotal.fret].decimal() == Decimal("1250.00")
    assert st[TypeSousTotal.remise].decimal() == Decimal("250.00")
    assert st[TypeSousTotal.remise].signe_imprime is not None  # « -250.00 » : signe porté à part


def test_poids_et_colis_jamais_lus_comme_montants(en):
    ch, _ = en
    assert ch.masse_brute_totale.decimal() == Decimal("4749.595") and ch.masse_brute_totale.unite == "KGM"
    assert ch.masse_nette_totale.decimal() == Decimal("4123.911")
    assert ch.nombre_colis.valeur == "220"
    montants = {v.decimal() for v in [ch.total_facture] + [s.montant for s in ch.sous_totaux]}
    assert Decimal("4749.595") not in montants and Decimal("220") not in montants


def test_lignes_codes_dans_leur_colonne(en):
    ch, _ = en
    assert len(ch.lignes) == 3
    l0, l1, l2 = ch.lignes
    assert l0.code_marchandise_imprime.valeur == "63026000" and l0.code_marchandise_imprime.valeur_brute == "6302.60.00"
    assert l1.code_marchandise_imprime.valeur_brute == "2202 99 99"
    assert l2.code_marchandise_imprime.valeur == "731815"  # code à 6 chiffres
    assert l0.quantite.decimal() == Decimal("4930") and l0.quantite.unite == "C62"
    assert l1.quantite.unite == "LTR" and l2.quantite.unite == "KGM"
    assert l2.prix_unitaire.decimal() == Decimal("3.124")
    assert [ln.montant_ligne.decimal() for ln in ch.lignes] == [Decimal("5916.00"), Decimal("2500.00"),
                                                               Decimal("3124.00")]
    assert {ln.pays_origine.valeur for ln in ch.lignes} == {"GB", "CN"}
    codes = {ln.code_marchandise_imprime.valeur for ln in ch.lignes}
    # téléphone, SIREN, TVA, LTA de l'en-tête ne deviennent jamais des codes marchandise
    assert not codes & {"0102030405", "000555551", "123456789"}


# --- formats, multipage, total pour la douane ---------------------------------------------------------------


def test_facture_fr_multipage_total_pour_la_douane():
    ch, _ = _fc(fx.facture_fr_multipage())
    assert ch.numero.valeur == "00090/26"
    assert ch.date.valeur == "2026-05-08" and ch.date.confiance >= 0.9  # JJ/MM sur un document français
    assert ch.devise.valeur == "CHF"
    assert ch.incoterm.valeur == "FCA"
    # le « total de la page » 1 n'est pas le total général ; « valeur pour la douane » l'emporte
    assert ch.total_facture.decimal() == Decimal("65776.48") and ch.total_facture.page == 2
    assert ch.acheteur.tva.valeur == fx.TVA_ACHETEUR
    assert len(ch.lignes) == 2 and ch.lignes[1].montant_ligne.page == 2
    assert ch.lignes[0].montant_ligne.decimal() == Decimal("59900.00")
    assert ch.lignes[0].quantite.decimal() == Decimal("1000")
    assert ch.lignes[1].code_marchandise_imprime.valeur_brute == "8528 52"
    assert ch.masse_brute_totale.decimal() == Decimal("1120.773")
    assert ch.nombre_colis.valeur == "82"


def test_facture_es_jpy_sans_decimales_total_sous_le_libelle():
    ch, _ = _fc(fx.facture_es_jpy())
    assert ch.numero.valeur == "SZ26000210"
    assert ch.date.valeur == "2026-01-28"
    assert ch.devise.valeur == "JPY"
    assert ch.total_facture.decimal() == Decimal("527448")  # « 527,448 » : milliers, pas décimales
    assert ch.total_facture.valeur_brute == "JPY 527,448"
    assert ch.lignes[0].montant_ligne.decimal() == Decimal("79028")
    assert ch.lignes[0].quantite.unite == "C62"  # « uds »
    assert ch.masse_brute_totale.decimal() == Decimal("48.750")
    assert ch.acheteur.tva.valeur == fx.TVA_ACHETEUR


def test_total_absent_reconstruit_borne_basse():
    contenu = fx.facture_en(pied=[], total=None)
    ch, r = _fc(contenu)
    t = ch.total_facture
    assert t.decimal() == Decimal("11540.00")
    assert t.total_origine is TotalOrigine.reconstruit and t.methode is Methode.derive
    assert t.confiance <= 0.60
    assert set(t.derivee_de) == {ln.montant_ligne.id for ln in ch.lignes}
    assert "total_reconstruit" in r.avertissements


def test_total_incoherent_confiance_basse():
    # total imprimé qui ne recoupe ni les lignes ni les pieds : lu tel quel, mais jamais « sûr »
    ch, _ = _fc(fx.facture_en(total="USD 99,999.00"))
    assert ch.total_facture.decimal() == Decimal("99999.00")
    assert ch.total_facture.confiance < 0.9


def test_dollar_seul_devise_inconnue():
    contenu = fx.facture_en(devise_libelle=None, total="$ 12,540.00",
                            pied=[("Subtotal (goods)", "$ 11,540.00"), ("Freight", "$ 1,250.00"),
                                  ("Discount", "$ -250.00")])
    ch, _ = _fc(contenu)
    assert ch.devise is None or ch.devise.valeur in (None, "inconnue")
    if ch.devise is not None:
        assert ch.devise.confiance <= 0.3
    assert ch.total_facture.decimal() == Decimal("12540.00")
    assert ch.total_facture.confiance < 0.9  # devise incertaine


def test_titre_valeur_douane_et_pro_forma():
    ch, _ = _fc(fx.facture_en(titre="PROFORMA INVOICE"))
    assert ch.numero.valeur == "INV-2026-0815"
    assert ch.total_facture.decimal() == Decimal("12540.00")


def test_code_coupe_sur_deux_lignes():
    p = fx.PagePdf()
    p.t(42, 40, "Demo Exports Ltd (FICTITIOUS)")
    p.t(330, 60, "Invoice No.:")
    p.t(420, 60, "INV-77")
    p.t(330, 72, "Currency:")
    p.t(420, 72, "EUR")
    p.ligne(120, fx.COLS_EN)
    p.ligne(138, [(42, "1", False), (60, "X-1", False), (125, "Laptop computer", False), (285, "8471.30", False),
                  (345, "CN", False), (405, "2", True), (412, "pcs", False), (500, "600.00", True),
                  (555, "1,200.00", True)])
    p.ligne(150, [(125, "14 inch", False), (285, "00", False)])
    p.t(330, 180, "TOTAL")
    p.t(555, 180, "EUR 1,200.00", droite=True)
    ch, _ = _fc(fx.pdf([p]))
    assert len(ch.lignes) == 1
    code = ch.lignes[0].code_marchandise_imprime
    assert code.valeur == "84713000" and code.valeur_brute == "8471.30 00"
    assert ch.lignes[0].description.valeur == "Laptop computer 14 inch"


def test_tableur_formulaire_et_total_absent():
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Invoice"
    for row in (["COMMERCIAL INVOICE"], ["Great Lakes Demo Tools LLC (FICTITIOUS)"], [],
                ["Invoice No.", "No.202600070"], ["Date", "2026-08-25"], ["Currency", "USD"],
                ["Incoterms", "FOB Los Angeles"], ["Buyer", "Brindille Cosmétiques SAS (FICTIF)"],
                ["Buyer address", "7 chemin des Échantillons"], ["Buyer VAT No.", fx.TVA_ACHETEUR], [],
                ["#", "Item ref.", "Description", "HS code", "Origin", "Qty", "Unit", "Unit price", "Amount"],
                [1, "LA-9063-BK", "Kitchen knife stainless", "8211.91.00", "US", 1290, "C62", 6.58, 8488.2],
                [2, "LA-6623-A", "Switching power supply", "8504.40.82", "US", 380, "C62", 11.83, 4495.4],
                [], ["Total gross weight (kg)", 2311.287], ["Number of packages", 138]):
        ws.append(row)
    for r in (13, 14):
        for c in (8, 9):
            ws.cell(r, c).number_format = "#,##0.00"
    buf = io.BytesIO()
    wb.save(buf)
    ch, _ = _fc(buf.getvalue(), mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert ch.numero.valeur == "No.202600070"
    assert ch.devise.valeur == "USD" and ch.incoterm.valeur == "FOB" and ch.incoterm_lieu.valeur == "Los Angeles"
    assert ch.acheteur.tva.valeur == fx.TVA_ACHETEUR
    assert ch.acheteur.nom.valeur == "Brindille Cosmétiques SAS (FICTIF)"
    assert [ln.quantite.decimal() for ln in ch.lignes] == [Decimal("1290"), Decimal("380")]
    assert ch.lignes[0].quantite.unite == "C62"
    assert ch.total_facture.total_origine is TotalOrigine.reconstruit
    assert ch.total_facture.decimal() == Decimal("12983.60")
    assert ch.masse_brute_totale.decimal() == Decimal("2311.287")
    assert ch.nombre_colis.valeur == "138"


# --- OCR : confiance issue des mots, plafonds ---------------------------------------------------------------


def _page_ocr(lignes: list[list[tuple[str, float, float]]], conf: float = 0.95) -> PageText:
    """Page OCR synthétique : chaque ligne = [(texte, x0, x1)] ; confiance OCR uniforme."""
    out = []
    for i, mots in enumerate(lignes):
        y = 0.1 + 0.02 * i
        ms = tuple(Mot(t, x0, y, x1, y + 0.012, conf) for t, x0, x1 in mots)
        out.append(Ligne(texte="   ".join(m.texte for m in ms), mots=ms))
    return PageText(numero=1, texte="\n".join(li.texte for li in out), lignes=out, qualite=QualiteTexte.ocr,
                    source="ocr")


def test_ocr_confiance_plafonnee_et_correction_tva():
    pt = _page_ocr([
        [("Buyer", 0.06, 0.1), ("/", 0.105, 0.11), ("Bill", 0.115, 0.14), ("to", 0.145, 0.16),
         ("Invoice", 0.57, 0.62), ("No.:", 0.625, 0.65), ("EXP", 0.70, 0.73), ("-26-00180", 0.733, 0.80)],
        [("Lumen", 0.06, 0.1), ("Industrie", 0.105, 0.16), ("SAS", 0.165, 0.19), ("Invoice", 0.57, 0.62),
         ("date:", 0.625, 0.66), ("Aug", 0.70, 0.73), ("31,", 0.735, 0.755), ("2026", 0.76, 0.79)],
        [("VAT", 0.06, 0.09), ("No.:", 0.095, 0.12), ("FRO7000909341", 0.125, 0.25), ("Currency:", 0.57, 0.64),
         ("EUR", 0.70, 0.73)],
    ])
    ch, _ = extraire_facture_commerciale(vue_document([pt]), document_id="doc_test")
    # « EXP -26-00180 » : référence recollée, la date du dessous n'est jamais prise pour le numéro
    assert ch.numero.valeur_brute == "EXP -26-00180" and ch.numero.methode is Methode.ocr
    assert ch.numero.confiance < 0.9
    # « FRO7000909341 » : O lu pour 0 ; corrigé car la clé de la TVA française est valide
    assert ch.acheteur.tva.valeur == "FR07000909341" and ch.acheteur.tva.valeur_brute == "FRO7000909341"
    assert ch.acheteur.tva.confiance < 0.9


# --- outils de mise en page ---------------------------------------------------------------------------------------


def _mots(*ts: str) -> list[Mot]:
    out, x = [], 0.0
    for t in ts:
        out.append(Mot(t, x, 0, x + 0.006 * len(t), 0.01))
        x += 0.006 * len(t) + 0.004
    return out


@pytest.mark.parametrize("mots, attendu", [
    (("1", "234,56"), "1 234,56"),
    (("113,", "212.72"), "113, 212.72"),
    (("2,902", ".060", "kg"), "2,902 .060"),
    (("1'234.56",), "1'234.56"),
])
def test_nombres_groupes(mots, attendu):
    n = nombres_dans(_mots(*mots))
    assert n[0].texte == attendu


def test_texte_nombre_corrige_espace_ocr():
    assert texte_nombre("113, 212.72") == "113,212.72"
    assert texte_nombre("1 234,56") == "1 234,56"


def test_separateur_decimal_du_document():
    def vue(*lignes: str) -> VueDocument:
        ls = [Ligne(texte=t, mots=tuple(_mots(*t.split()))) for t in lignes]
        return vue_document([PageText(numero=1, texte="\n".join(lignes), lignes=ls)])

    assert inferer_separateur(vue("Total 1.234,56", "Prix 12,50")) == ","
    assert inferer_separateur(vue("Total 1,234.56", "0.479 kg")) == "."
    assert inferer_separateur(vue("Ref 2026")) is None


def test_tva_formats_nationaux():
    assert lire_tva_mots(_mots("VAT", "FR", "43", "000", "123", "459"))[2] == fx.TVA_ACHETEUR
    assert lire_tva_mots(_mots("DEMO307604768")) is None  # pas une TVA allemande
    assert lire_tva_mots(_mots("GB000000000"))[2] == "GB000000000"
    r = lire_tva_ocr(_mots("FRO7000909341"))
    assert r is not None and r[2] == "FR07000909341" and r[3] is True
    assert lire_tva_ocr(_mots("FRO7000909342")) is None  # clé invalide : pas de correction


def test_reference_coupee_par_ocr():
    assert accepte_reference(_mots("EXP", "-26-00180")) == (0, 2)
    assert accepte_reference(_mots("FAC/2026/0099", "-0")) == (0, 2)


def test_ancrage_de_toutes_les_valeurs_lues(en):
    ch, _ = en
    for v in ch.iter_valeurs():
        if v.methode is Methode.texte_natif:
            assert v.ancree and v.texte_contexte and v.zone is not None, v.chemin
            assert v.extracteur.type.value == "deterministe"
    assert anchor("USD 12,540.00", "TOTAL AMOUNT   USD   12,540.00")
