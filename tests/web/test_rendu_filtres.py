"""Filtres d'affichage et garde de redirection de l'interface (web/rendu.py) : branches non couvertes avant D-3902.
Une valeur inattendue s'affiche telle quelle ou en « — », jamais une erreur 500."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from controldone.web.rendu import _date, _montant, _nombre, _taille, environnement, retour_sur, texte_visible

NB = " "


def test_montant():
    assert _montant(None) == "—" and _montant("") == "—"
    assert _montant(Decimal("1234.5")) == f"1{NB}234,50{NB}EUR"
    assert _montant("12", "JPY") == f"12{NB}JPY"
    assert _montant("pas un nombre") == "pas un nombre"


def test_nombre():
    assert _nombre(None) == "—"
    assert _nombre(2500) == f"2{NB}500"
    assert _nombre("abc") == "abc"


def test_date():
    assert _date(None) == "—" and _date("") == "—"
    assert _date("pas une date") == "pas une date"
    # UTC -> heure de Paris (UTC+2 en été)
    assert _date("2026-08-14T10:05:00Z") == "14 août 2026 à 12:05"
    assert _date(datetime(2026, 1, 3, 23, 30, tzinfo=UTC), heure=False) == "4 janv. 2026"
    assert _date(datetime(2026, 12, 1, 8, 0)) == "1 déc. 2026 à 09:00"  # naïve : lue comme UTC
    assert _date(date(2026, 5, 1)) == "2026-05-01"


@pytest.mark.parametrize(
    "n, attendu",
    [
        (None, "—"),
        ("x", "—"),
        (0, "0 o"),
        (1023, "1023 o"),
        (1024, "1,0 Ko"),
        (5 * 1024 * 1024, "5,0 Mo"),
        (3 * 1024**4, "3072,0 Go"),
    ],
)
def test_taille(n, attendu):
    assert _taille(n) == attendu


def test_environnement_echappe_et_filtres():
    env = environnement()
    t = env.from_string("{{ x }}|{{ m|montant }}|{{ b|b64 }}|{{ v|b64 }}")
    assert t.render(x="<script>", m="1", b=b"ab", v=b"") == f"&lt;script&gt;|1,00{NB}EUR|YWI=|"


@pytest.mark.parametrize(
    "valeur", ["//evil.example", "https://evil.example", "/a b", "/\\x", None, 3, "", "a/b"]
)
def test_retour_refuse(valeur):
    assert retour_sur(valeur, "/espace") == "/espace"


def test_retour_admis_et_texte_visible():
    assert retour_sur("/espace/recouvrement?page=2#liste", "/") == "/espace/recouvrement?page=2#liste"
    html = "<style>.x{}</style><p>Bonjour&nbsp;<b>FICTIF</b></p><script>alert(1)</script>"
    assert texte_visible(html) == "Bonjour FICTIF"  # balises, style et script retirés, espaces réduits
