"""Propriétés des tolérances et arrondis (controls/tolerances.py) : symétrie, monotonie, Decimal partout (D-3903)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from controldone.controls.tolerances import (
    Tolerances,
    arrondi_centime,
    arrondi_devise,
    arrondi_unite,
    dans_tolerance,
)
from controldone.model.referentiel import ProfilTolerances

pytestmark = pytest.mark.proprietes

T = Tolerances(ProfilTolerances())
montants = st.decimals(min_value=Decimal("-1e10"), max_value=Decimal("1e10"), places=4, allow_nan=False,
                       allow_infinity=False)
positifs = st.decimals(min_value=0, max_value=Decimal("1e10"), places=4, allow_nan=False, allow_infinity=False)

FONCTIONS_PAIRES = [T.t_valeur, T.s_valeur, T.t_conversion, T.s_conversion, T.t_masse]


@given(a=montants, b=montants, i=st.integers(0, len(FONCTIONS_PAIRES) - 1))
def test_tolerances_symetriques_et_decimales(a, b, i):
    f = FONCTIONS_PAIRES[i]
    assert f(a, b) == f(b, a)
    assert f(a, b) == f(-a, -b)
    assert type(f(a, b)) is Decimal
    assert f(a, b) >= f(a)  # la base est la plus grande des deux valeurs (D-015)


@given(a=positifs, b=positifs)
def test_seuil_de_certitude_jamais_sous_la_tolerance(a, b):
    assert T.s_valeur(a, b) >= T.t_valeur(a, b)
    assert T.s_conversion(a, b) >= T.t_conversion(a, b)


@given(a=positifs, b=positifs)
def test_tolerance_monotone(a, b):
    petit, grand = sorted([a, b])
    assert T.t_valeur(petit) <= T.t_valeur(grand)
    assert T.t_conversion(petit) <= T.t_conversion(grand)


@given(ecart=montants, tol=positifs)
def test_dans_tolerance_symetrique(ecart, tol):
    assert dans_tolerance(ecart, tol) == dans_tolerance(-ecart, tol)
    assert dans_tolerance(ecart, tol) == (abs(ecart) <= tol)


@given(n=st.integers(-5, 10_000))
def test_t_somme_et_debours_bornees(n):
    p = T.profil
    assert p.t_somme_minimum <= T.t_somme(n) <= max(p.t_somme_plafond, p.t_somme_minimum)
    assert p.t_debours_minimum <= T.t_debours(n) <= max(p.t_debours_plafond, p.t_debours_minimum)
    assert T.s_debours(n) >= T.t_debours(n)
    assert type(T.t_somme(n)) is Decimal and type(T.t_debours(n)) is Decimal


@given(x=montants)
def test_arrondis_idempotents_et_proches(x):
    c = arrondi_centime(x)
    assert arrondi_centime(c) == c
    assert abs(c - x) <= Decimal("0.005")
    assert arrondi_centime(-x) == -c  # demi « loin de zéro » : symétrique
    u = arrondi_unite(x)
    assert abs(u - x) <= Decimal("0.5")
    assert arrondi_devise(x, "JPY") == u
    assert arrondi_devise(x, "EUR") == c


@given(calcul=montants)
def test_taxe_ligne_concorde_avec_son_calcul_et_ses_arrondis(calcul):
    assert T.taxe_ligne_concorde(calcul, calcul)
    assert T.taxe_ligne_concorde(arrondi_unite(calcul), calcul)
    assert T.taxe_ligne_concorde(arrondi_centime(calcul), calcul)
    assert not T.taxe_ligne_concorde(calcul + Decimal("1.02"), calcul)


@given(unite=st.sampled_from([None, "KGM", "PCE", "LTR", "NAR", "PR"]), a=positifs, b=positifs)
def test_tolerance_quantite(unite, a, b):
    t = T.t_quantite(unite, a, b)
    assert type(t) is Decimal and t >= 0
    assert t == T.t_quantite(unite, b, a)
