from decimal import Decimal as D

import pytest

from controldone.normalize import parse_amount, parse_decimal, parse_int


@pytest.mark.parametrize(
    ("texte", "valeur"),
    [
        ("1.234,56", "1234.56"),
        ("1,234.56", "1234.56"),
        ("1 234,56", "1234.56"),
        ("1 234,56", "1234.56"),  # insécable
        ("1 234,56", "1234.56"),  # fine insécable
        ("1 234,56", "1234.56"),  # fine
        ("1'234.56", "1234.56"),
        ("1’234.56", "1234.56"),
        ("1.234.567,89", "1234567.89"),
        ("1,234,567.89", "1234567.89"),
        ("12540.00", "12540.00"),
        ("12540,00", "12540.00"),
        ("0,125", "0.125"),
        ("12 540", "12540"),
        ("USD 12,540.00", "12540.00"),
        ("12 540,00 €", "12540.00"),
        ("€12,540.00", "12540.00"),
        ("TOTAL AMOUNT DUE  USD 12,540.00", "12540.00"),
        ("1234.567", "1234.567"),
        ("3", "3"),
    ],
)
def test_formats(texte, valeur):
    m = parse_amount(texte)
    assert m is not None
    assert m.valeur == D(valeur)
    assert m.negatif is False


@pytest.mark.parametrize("texte", ["(1 234,56)", "-1 234,56", "1 234,56-", "−12,00", "EUR -12.50", "(EUR 12.00)", "-€12"])
def test_negatifs_valeur_absolue(texte):
    m = parse_amount(texte)
    assert m is not None and m.negatif is True and m.valeur > 0


def test_plage_n_est_pas_un_negatif():
    assert parse_amount("10-20").negatif is False


@pytest.mark.parametrize(
    ("texte", "devise", "valeur"),
    [
        ("1,250,000 KRW", "KRW", "1250000"),
        ("1.250.000 KRW", "KRW", "1250000"),
        ("JPY 125,000", "JPY", "125000"),
        ("1,250", "JPY", "1250"),  # devise sans décimales : séparateur de milliers, non ambigu
    ],
)
def test_devises_sans_decimales(texte, devise, valeur):
    m = parse_amount(texte, devise=devise if texte == "1,250" else None)
    assert m.valeur == D(valeur)
    assert m.devise == devise
    assert m.ambigu is False


def test_ambiguite_trois_chiffres():
    m = parse_amount("1,234")
    assert m.valeur == D("1234") and m.ambigu is True
    assert parse_amount("1,234", separateur_decimal=",").valeur == D("1.234")
    assert parse_amount("1.234", separateur_decimal=",").valeur == D("1234")


def test_devise_detectee():
    assert parse_amount("USD 12,540.00").devise == "USD"
    assert parse_amount("12 540,00 EUR").devise == "EUR"
    assert parse_amount("12 540,00").devise is None
    assert parse_amount("$ 100.00").devise == "inconnue"
    assert parse_amount("$ 100.00", pays_vendeur="US").devise == "USD"


@pytest.mark.parametrize("texte", ["", None, "abc", "1 23 4", "1,23,45"])
def test_illisible(texte):
    assert parse_amount(texte) is None


def test_soudure_de_deux_nombres():
    # « 10 » (quantité) collé au montant par une espace : on garde le dernier nombre valide
    assert parse_amount("10 1 234,56").valeur == D("1234.56")


def test_parse_decimal_et_int():
    assert parse_decimal("2,5 %") == D("2.5")
    assert parse_decimal("1,08542") == D("1.08542")
    assert parse_decimal("-3,5") == D("-3.5")
    assert parse_int("1 250") == 1250
    assert parse_int("12") == 12
    assert parse_int("12,5") is None
    assert parse_int("x") is None


@pytest.mark.parametrize(
    ("texte", "attendu"),
    [
        # F13 / D-1209 : tiret isolé après un mot ou un nombre = séparateur
        ("Frais de dossier - 45,00", "45.00"),
        ("Dédouanement - 45,00 EUR", "45.00"),
        ("Ligne 3 - 1 234,56", "1234.56"),
        ("N° 12 - EUR 100", "100"),
        # le signe moins reste lu
        ("- 12,00", "-12.00"),
        ("-12,00", "-12.00"),
        ("EUR - 12,00", "-12.00"),
        ("Remise : - 12,00", "-12.00"),
        ("Total : -12,00", "-12.00"),
        ("45,00-", "-45.00"),
        ("(1 234,56)", "-1234.56"),
    ],
)
def test_tiret_separateur_ou_signe(texte, attendu):
    from decimal import Decimal

    assert parse_amount(texte).valeur_signee == Decimal(attendu)
