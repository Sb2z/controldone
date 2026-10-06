"""Facture de transitaire lue par OCR : membres d'une somme imprimée qui tient (D-2904). Données fictives."""

from __future__ import annotations

from dataclasses import replace

from test_facture_transitaire import MRN_1, _entete, _pdf

from controldone.extract.base import ExtractionContext
from controldone.extract.deterministe.facture_transitaire import ExtracteurFactureTransitaire
from controldone.ids import IdGenerator
from controldone.ingest import OptionsPages, extraire_pages
from controldone.ingest.texte import Ligne, PageText
from controldone.model import Document, Page, PageRef
from controldone.model.enums import QualiteTexte, TypeDocument


def _facture(ttc: str = "1 278,62", total_ht: str = "190,00") -> bytes:
    el = _entete("FACTURE", "N° F-2610777")
    el += [
        (0.08, 0.23, "Désignation", "g"),
        (0.62, 0.23, "Qté", "d"),
        (0.68, 0.23, "Montant HT", "d"),
        (0.80, 0.23, "TVA %", "d"),
        (0.90, 0.23, "Mt TVA", "d"),
        (0.08, 0.25, "Droits de douane (débours)", "g"),
        (0.62, 0.25, "1", "d"),
        (0.68, 0.25, "1 050,62", "d"),
        (0.80, 0.25, "0,00", "d"),
        (0.90, 0.25, "0,00", "d"),
        (0.08, 0.27, "Frais de dédouanement", "g"),
        (0.62, 0.27, "1", "d"),
        (0.68, 0.27, "65,00", "d"),
        (0.80, 0.27, "20,00", "d"),
        (0.90, 0.27, "13,00", "d"),
        (0.08, 0.29, "Livraison", "g"),
        (0.62, 0.29, "1", "d"),
        (0.68, 0.29, "125,00", "d"),
        (0.80, 0.29, "20,00", "d"),
        (0.90, 0.29, "25,00", "d"),
        (0.60, 0.33, "Total débours", "g"),
        (0.93, 0.33, "1 050,62", "d"),
        (0.60, 0.35, "Total HT prestations", "g"),
        (0.93, 0.35, total_ht, "d"),
        (0.60, 0.37, "Total TVA", "g"),
        (0.93, 0.37, "38,00", "d"),
        (0.60, 0.39, "Total TTC", "g"),
        (0.93, 0.39, ttc, "d"),
    ]
    return _pdf(el)


def _extraire_ocr(contenu: bytes, conf: float):
    pe = extraire_pages(contenu, options=OptionsPages(ocr=False, isoler=False))[0]
    lignes = [
        Ligne(texte=li.texte, mots=tuple(replace(m, confiance=conf) for m in li.mots))
        for li in pe.texte.lignes
    ]
    pt = PageText(
        numero=1,
        texte=pe.texte.texte,
        lignes=lignes,
        qualite=QualiteTexte.ocr,
        source="ocr",
        score_ocr=0.9,
        largeur=595.0,
        hauteur=842.0,
    )
    page = Page(fichier_id="fic_test", numero=1, qualite_texte=QualiteTexte.ocr, texte=pt.texte)
    doc = Document(
        type=TypeDocument.facture_transitaire,
        pages=[PageRef(fichier_id="fic_test", numero=1, qualite_texte=QualiteTexte.ocr)],
    )
    ctx = ExtractionContext(ids=IdGenerator.deterministe(7), options={"textes_pages": {1: pt}})
    res = ExtracteurFactureTransitaire().extract(doc, [page], ctx)
    assert res.champs is not None
    return res.champs


def test_ttc_egal_ht_des_prestations_plus_tva_plus_debours():
    c = _extraire_ocr(_facture(), conf=0.8)
    assert (c.total_ht.valeur, c.total_tva.valeur, c.total_ttc.valeur) == ("190.00", "38.00", "1278.62")
    for v in (c.total_ht, c.total_tva, c.total_ttc, c.total_debours):
        assert v.confiance >= 0.9, v.chemin


def test_somme_qui_ne_tient_pas_rien_n_est_releve():
    c = _extraire_ocr(_facture(ttc="1 288,62"), conf=0.8)
    assert c.total_ttc.confiance < 0.9
    assert c.total_tva.confiance >= 0.9  # Σ TVA des lignes = total TVA imprimé : confirmé par ses lignes


def test_taux_imprime_avec_decimales_et_ht_confirme_par_la_tva():
    c = _extraire_ocr(_facture(total_ht="199,00"), conf=0.8)  # total HT faux : Σ HT et TTC ne tiennent pas
    assert c.total_ht.confiance < 0.9
    livraison = next(lg for lg in c.lignes if lg.montant_ht is not None and lg.montant_ht.valeur == "125.00")
    # TVA de la ligne confirmée par Σ TVA = total TVA, puis HT × 20 % = TVA : le HT est confirmé
    assert livraison.montant_tva.confiance >= 0.9 and livraison.montant_ht.confiance >= 0.9


def test_mots_peu_lisibles_jamais_releves():
    c = _extraire_ocr(_facture(), conf=0.5)
    assert all(v.confiance < 0.9 for v in (c.total_ht, c.total_tva, c.total_ttc))


def test_lignes_de_prestations_confirmees_par_leur_total():
    c = _extraire_ocr(_facture(), conf=0.8)
    prest = [lg for lg in c.lignes if not lg.nature.est_debours]
    assert [lg.montant_ht.valeur for lg in prest] == ["65.00", "125.00"]
    assert all(lg.montant_ht.confiance >= 0.9 for lg in prest)
    assert MRN_1  # en-tête commun aux tests de facture de transitaire


def test_ligne_de_credit_valeurs_deduites_negatives():
    from test_facture_transitaire import _extraire

    from controldone.model.enums import SigneImprime

    el = _entete("RECHNUNG", "Nr. F-2610778")
    el += [
        (0.08, 0.23, "Bezeichnung", "g"),
        (0.62, 0.23, "Menge", "d"),
        (0.76, 0.23, "Betrag", "d"),
        (0.08, 0.25, "Verzollung", "g"),
        (0.62, 0.25, "1", "d"),
        (0.76, 0.25, "65.00", "d"),
        (0.08, 0.27, "Gutschrift zu Rechnung FIC-26-0001", "g"),
        (0.62, 0.27, "1", "d"),
        (0.76, 0.27, "-18.50", "d"),
        (0.60, 0.31, "Total netto", "g"),
        (0.93, 0.31, "46.50", "d"),
    ]
    c = _extraire(_pdf(el))
    credit = next(lg for lg in c.lignes if lg.libelle is not None and "Gutschrift" in lg.libelle.valeur)
    assert credit.montant_ht.signe_imprime is SigneImprime.negatif
    for v in (credit.prix_unitaire, credit.montant_tva):
        if v is not None:
            assert v.signe_imprime is SigneImprime.negatif and v.decimal_signe() < 0
