from decimal import Decimal as D

import pytest

from controldone.controls.framework import (
    codes_confondables,
    confusion_applicable,
    confusion_test,
    confusion_test_fn,
    est_transposition_adjacente,
)
from controldone.model import QualiteTexte
from controldone.testing import vs

UN = D("1")


@pytest.mark.parametrize(
    ("brut", "autre"),
    [
        ("12 880,00", "12680.00"),  # 8 -> 6 (classe 0689)
        ("12 980,00", "12080.00"),  # 9 -> 0
        ("3 418,20", "3416.20"),  # 8 -> 6
        ("1 350,00", "1 380,00"),  # 5 -> 8 (classe 358)
        ("1 350,00", "1 330,00"),  # 5 -> 3
        ("4 100,00", "7 100,00"),  # 4 -> 7 (classe 147)
        ("1 000,00", "4 000,00"),  # 1 -> 4
    ],
)
def test_substitution_meme_classe(brut, autre):
    assert confusion_test(brut, D(autre.replace(" ", "").replace(",", ".")), D("0.01"))


@pytest.mark.parametrize(("brut", "autre"), [("12 540,00", "13540.00"), ("2 000,00", "7000.00"), ("100,00", "200.00")])
def test_substitution_hors_classe_negative(brut, autre):
    assert not confusion_test(brut, D(autre), D("0.01"))


@pytest.mark.parametrize(
    ("brut", "autre"),
    [("1O5,00", "105"), ("1D5,00", "105"), ("l05,00", "105"), ("1I5,00", "115"), ("S00,00", "500"),
     ("B00,00", "800"), ("Z00,00", "200"), ("G00,00", "600")],
)
def test_lettre_chiffre(brut, autre):
    assert confusion_test(brut, D(autre), D("0.01"))


def test_zero_final():
    assert confusion_test("84713", D("847130"), D("0"))  # zéro perdu
    assert confusion_test("8471300", D("847130"), D("0"))  # zéro ajouté


@pytest.mark.parametrize(("brut", "autre"), [("1254000", "12540.00"), ("125,40", "12540"), ("12,540", "12.54")])
def test_separateur_decimal_inverse(brut, autre):
    assert confusion_test(brut, D(autre), UN)


def test_transposition_adjacente_n_est_pas_une_confusion():
    assert est_transposition_adjacente(D("12450.00"), D("12540.00"))
    assert not confusion_test("12 450,00", D("12540.00"), UN)
    assert not confusion_test("12 860,00", D("12680.00"), D("0.01"))  # 8/6 permutés : transposition
    assert not est_transposition_adjacente(D("12450"), D("12450"))
    assert not est_transposition_adjacente(D("1245"), D("5241"))


def test_pas_d_ecart_pas_de_confusion():
    assert not confusion_test("12 540,00", D("12540.00"), UN)
    assert not confusion_test(None, D("1"), UN)


def test_une_seule_transformation():
    # deux substitutions nécessaires (6->8 et 3->5) : négatif
    assert not confusion_test("16 300,00", D("18500.00"), D("0.01"))


def test_forme_generale():
    # base 2091 lue 2O91 ; le montant 52,28 concorde avec 2091 × 2,5 %
    def accepte(v):
        return abs(v * D("2.5") / 100 - D("52.28")) <= D("0.01")

    assert confusion_test_fn("2O91,00", accepte)
    assert not confusion_test_fn("2091,00", accepte)  # déjà concordant : rien à expliquer


def test_applicabilite():
    assert confusion_applicable(vs("a", "1", methode="ocr"), QualiteTexte.ocr)
    assert confusion_applicable(vs("a", "1", methode="llm"), QualiteTexte.natif_faible)
    assert confusion_applicable(vs("a", "1", methode="ocr"), None)  # qualité inconnue : prudence
    assert not confusion_applicable(vs("a", "1", methode="ocr"), QualiteTexte.natif)
    assert not confusion_applicable(vs("a", "1", methode="texte_natif"), QualiteTexte.ocr)
    assert not confusion_applicable(vs("a", "1", methode="xml_structure"), QualiteTexte.ocr)


def test_codes_confondables():
    assert codes_confondables("847130", "847180")
    assert codes_confondables("847130", "847150")  # 3 -> 5
    assert codes_confondables("847130", "877150")  # deux chiffres, chacun dans sa classe
    assert not codes_confondables("847130", "847160")  # 3 -> 6 : classes différentes
    assert not codes_confondables("847130", "847120")  # 3 -> 2 : hors classe
    assert not codes_confondables("847130", "841730")  # transposition
    assert not codes_confondables("847130", "84713000")
