"""Branches de rejet de la normalisation des montants, devises, codes et saisies (non couvertes avant D-3902) :
une forme incohérente n'est jamais lue comme un autre nombre."""

from __future__ import annotations

from decimal import Decimal

import pytest

from controldone.normalize.amounts import _lire_noyau, parse_decimal, parse_nombre
from controldone.normalize.codes import code_marchandise
from controldone.normalize.currency import exposant_devise, normalize_currency
from controldone.services.plateforme import RequeteInvalide
from controldone.services.saisie import montant_saisi


@pytest.mark.parametrize("noyau", [
    "1 234.5.6",     # espaces de milliers puis deux séparateurs restants
    "1  234",        # groupe vide (deux espaces)
    "1234 567",      # premier groupe de plus de 3 chiffres
    "1 23",          # groupe final de 2 chiffres
    "1 2345 678",    # groupe intermédiaire de 4 chiffres
    "1,234,5",       # groupes de milliers invalides
    "1234,567.12",   # partie entière mal groupée avec virgule de milliers
    "1.234,56,7",    # séparateur décimal répété
    "12,34,5",       # groupement indien incomplet
])
def test_noyaux_incoherents_refuses(noyau):
    assert _lire_noyau(noyau, None, False) is None


@pytest.mark.parametrize("texte", ["1.234.56,7,8", "1,23.4,5", "1.2,3.4", "1,,000"])
def test_nombre_incoherent_non_lu(texte):
    assert parse_nombre(texte) is None


def test_groupement_indien_et_ambiguite():
    assert _lire_noyau("12,34,56,789", None, False) == (Decimal("123456789"), False)
    assert _lire_noyau("1,234", ",", False) == (Decimal("1.234"), False)  # séparateur décimal connu
    assert _lire_noyau("1,234", ".", False) == (Decimal("1234"), False)
    assert _lire_noyau("1,234", None, True) == (Decimal("1234"), False)  # devise sans décimales
    assert _lire_noyau("0,125", None, False) == (Decimal("0.125"), False)  # « 0 » de tête : décimal


def test_parse_decimal_sans_nombre():
    assert parse_decimal("taux non indiqué") is None
    assert parse_decimal(None) is None
    assert parse_decimal("-2,5 %") == Decimal("-2.5")


def test_devises_a_trois_decimales_et_vides():
    assert exposant_devise("KWD") == 3 and exposant_devise("BHD") == 3
    assert exposant_devise("JPY") == 0 and exposant_devise(None) == 2
    assert normalize_currency("   ") is None and normalize_currency(None) is None
    assert normalize_currency("USD ou EUR") == "inconnue"  # deux codes ISO différents : ambigu


def test_code_marchandise_non_numerique():
    assert code_marchandise("84A1.30") is None
    assert code_marchandise("8471.30.00") == "84713000"
    assert code_marchandise("84713") is None


@pytest.mark.parametrize("texte, message", [
    (None, "obligatoire"), ("1" * 41, "trop longue"), ("€", "obligatoire"), ("-", "obligatoire"),
    ("1,234.567", "nombre attendu"), ("1.234,5,6", "nombre attendu"), ("1 234 5", "nombre attendu"),
    ("12,345", "décimales"), ("-5", "positive"), ("0", "non nulle"), ("2 000 000 000", "trop élevée"),
])
def test_saisie_refus_lisibles(texte, message):
    with pytest.raises(RequeteInvalide, match=message):
        montant_saisi(texte)


def test_saisie_acceptees():
    assert montant_saisi("1 234,56 €") == Decimal("1234.56")
    assert montant_saisi("EUR 1.234,5") == Decimal("1234.50")
    assert montant_saisi("-12,3", negatif=True) == Decimal("-12.30")
    assert montant_saisi("0", zero=True) == Decimal("0.00")
    assert montant_saisi("1,2345", decimales=4) == Decimal("1.2345")
