"""Lectures de déclaration corrigées pendant la mise au point de la précision (D-712). Données fictives."""

from __future__ import annotations

from test_declaration import _cases, _extraire, _extraire_pdf, _page_ocr, _pdf


def test_case_voisine_lue_par_ocr_n_est_pas_une_masse():
    # ligne de libellés lue par OCR : « 35 Masse brute (kg) 38 Masse nette (kg) », valeurs dessous
    page = _page_ocr([
        [("DÉCLARATION", 0.06, 0.16), ("EN", 0.17, 0.19), ("DOUANE", 0.20, 0.27)],
        [("31", 0.06, 0.07), ("Colis", 0.075, 0.10), ("et", 0.105, 0.115), ("désignation", 0.12, 0.17),
         ("-", 0.175, 0.18), ("article", 0.185, 0.215), ("1", 0.22, 0.225)],
        [("MRN", 0.06, 0.09), ("26FRK7G7KR9KVHGNG3", 0.10, 0.25)],
        [("32", 0.60, 0.61), ("Article", 0.615, 0.645), ("n°", 0.65, 0.66), ("33", 0.75, 0.76), ("Code", 0.765, 0.785),
         ("des", 0.79, 0.80), ("marchandises", 0.805, 0.86)],
        [("1", 0.61, 0.615), ("0902300000", 0.76, 0.82)],
        [("34", 0.06, 0.07), ("origine", 0.075, 0.105), ("35", 0.30, 0.31), ("Masse", 0.312, 0.335),
         ("brute", 0.337, 0.358), ("(kg)", 0.36, 0.375), ("38", 0.378, 0.388), ("Masse", 0.40, 0.423),
         ("nette", 0.425, 0.445), ("(kg)", 0.447, 0.462)],
        [("CN", 0.06, 0.07), ("50,250", 0.305, 0.335), ("45,000", 0.40, 0.43)],
    ])
    c = _extraire([page])
    assert c.articles, "article non lu"
    a = c.articles[0]
    assert a.masse_brute is not None and a.masse_brute.valeur == "50.250"


def test_formulaire_a_cases_inchange():
    c = _extraire_pdf(_cases())
    assert (c.articles[0].masse_brute.valeur, c.articles[0].masse_nette.valeur) == ("50.250", "45.000")


def test_montant_condense_virgule_lue_comme_barre_et_statut_colle():
    p1 = [
        (0.06, 0.05, "PREUVE DE DÉDOUANEMENT", 12),
        (0.06, 0.09, "MRN.......: 26FRK7G7KR9KVHGNG3"), (0.55, 0.18, "Nb articles: 1"),
        (0.06, 0.23, "N"), (0.09, 0.23, "Code"), (0.20, 0.23, "Désignation"), (0.40, 0.23, "Or"),
        (0.52, 0.23, "Mt facturé", 8, "d"), (0.61, 0.23, "Base droits", 8, "d"), (0.66, 0.23, "Tx", 8, "d"),
        (0.73, 0.23, "Droits", 8, "d"), (0.82, 0.23, "Base TVA", 8, "d"), (0.89, 0.23, "TVA", 8, "d"),
        (0.92, 0.23, "St"),
        (0.06, 0.245, "1"), (0.09, 0.245, "8413702100"), (0.20, 0.245, "POMPE CENTRIFUGE"), (0.40, 0.245, "MX"),
        (0.52, 0.245, "1874,62", 8, "d"), (0.61, 0.245, "1874,62", 8, "d"), (0.66, 0.245, "1,7", 8, "d"),
        (0.73, 0.245, "31/87", 8, "d"), (0.82, 0.245, "1906,49", 8, "d"), (0.915, 0.245, "381,307", 8, "d"),
        (0.06, 0.39, "St (statut paiement) : 0 = comptant ; 1 = différé ; 7 = TVA autoliquidée", 7),
    ]
    c = _extraire_pdf(_pdf([p1]))
    montants = {t.categorie.value: t.montant.valeur for t in c.taxations if t.montant is not None}
    assert montants.get("droit") == "31.87"
    assert montants.get("tva") == "381.30"


def test_condense_droit_specifique_code_minuscule_ou_illisible():
    # Holdout 1 (D-903) : sous-lignes de droit spécifique d'un tableau condensé lu par OCR ; « x01 » (lettre
    # lue en minuscule) et « x1 » (code illisible). Ignorer ces lignes rendait la somme des lignes incomplète.
    entete = [(0.06, 0.23, "N"), (0.09, 0.23, "Code"), (0.20, 0.23, "Désignation"), (0.40, 0.23, "Or"),
              (0.52, 0.23, "Mt facturé", 8, "d"), (0.61, 0.23, "Base droits", 8, "d"), (0.66, 0.23, "Tx", 8, "d"),
              (0.73, 0.23, "Droits", 8, "d"), (0.82, 0.23, "Base TVA", 8, "d"), (0.89, 0.23, "TVA", 8, "d"),
              (0.92, 0.23, "St")]

    def article(y, n, code, des, mt, tx, dr, btva, tva):
        return [(0.06, y, n), (0.09, y, code), (0.20, y, des), (0.40, y, "JP"), (0.52, y, mt, 8, "d"),
                (0.61, y, mt, 8, "d"), (0.66, y, tx, 8, "d"), (0.73, y, dr, 8, "d"), (0.82, y, btva, 8, "d"),
                (0.89, y, tva, 8, "d"), (0.92, y, "1")]

    def sous_ligne(y, code, base, taux, montant):
        return [(0.09, y, code), (0.20, y, "Droit spécifique (fictif)"), (0.61, y, base, 8, "d"),
                (0.66, y, taux, 8, "d"), (0.73, y, montant, 8, "d"), (0.92, y, "1")]

    p1 = [
        (0.06, 0.05, "PREUVE DE DÉDOUANEMENT", 12),
        (0.06, 0.09, "MRN.......: 26FRK7G7KR9KVHGNG3"), (0.55, 0.18, "Nb articles: 2"),
        *entete,
        *article(0.245, "1", "1509200000", "HUILE FICTIVE", "1718,14", "0", "0,00", "1792,90", "358,58"),
        *sous_ligne(0.26, "x01", "623 LTR", "0,12", "74,76"),
        *article(0.275, "2", "2204210000", "BOISSON FICTIVE", "1000,00", "0", "0,00", "1117,60", "223,52"),
        *sous_ligne(0.29, "x1", "980 LTR", "0,12", "117,60"),
        (0.06, 0.39, "St (statut paiement) : 0 = comptant ; 1 = différé ; 7 = TVA autoliquidée", 7),
    ]
    c = _extraire_pdf(_pdf([p1]))
    autres = [t for t in c.taxations if t.categorie.value == "autre_taxe"]
    assert [t.montant.valeur for t in autres] == ["74.76", "117.60"]
    x01, illisible = autres
    assert x01.type_taxe.valeur == "X01" and x01.base_quantite.valeur == "623"
    assert illisible.type_taxe is None and illisible.montant.confiance <= 0.85
    assert illisible.article.valeur == "2"
