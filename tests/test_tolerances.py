from decimal import Decimal as D

import pytest

from controldone.controls.framework import Tolerances, arrondi_centime, arrondi_devise, dans_tolerance
from controldone.model import ProfilTolerances

T = Tolerances(ProfilTolerances())


def test_arrondis_8_2():
    assert arrondi_centime(D("52.275")) == D("52.28")  # demi vers le haut
    assert arrondi_centime(D("52.2749")) == D("52.27")
    assert arrondi_centime(D("-0.005")) == D("-0.01")
    assert arrondi_devise(D("1250.5"), "JPY") == D("1251")
    assert arrondi_devise(D("1.005"), "EUR") == D("1.01")


def test_t_ligne_t_somme():
    assert T.t_ligne() == D("0.01")
    assert T.t_somme(0) == D("0.01")
    assert T.t_somme(1) == D("0.01")
    assert T.t_somme(7) == D("0.07")
    assert T.t_somme(50) == D("0.50")
    assert T.t_somme(200) == D("0.50")


def test_t_taxe_ligne_arrondi_euro():
    calcul = D("52.2750")
    assert T.taxe_ligne_concorde(D("52.28"), calcul)
    assert T.taxe_ligne_concorde(D("52.27"), calcul)
    assert T.taxe_ligne_concorde(D("52"), calcul)  # arrondi inférieur / au plus proche
    assert T.taxe_ligne_concorde(D("53"), calcul)  # arrondi supérieur
    assert not T.taxe_ligne_concorde(D("52.30"), calcul)
    assert not T.taxe_ligne_concorde(D("51"), calcul)


def test_valeur_et_conversion():
    assert T.t_valeur(D("100")) == D("1")
    assert T.t_valeur(D("12540")) == D("12.540")
    assert T.s_valeur(D("100")) == D("5")
    assert T.s_valeur(D("12540")) == D("62.700")
    assert T.t_valeur(D("100"), D("5000")) == D("5.000")  # base = plus grande valeur
    assert T.t_conversion(D("500")) == D("1.00")
    assert T.s_conversion(D("2000")) == D("10.000")


def test_bande_indicative():
    assert T.bande_indicative("USD") == D("0.25")
    assert T.bande_indicative("TRY") == D("0.40")


@pytest.mark.parametrize(("n", "t"), [(0, "0.05"), (3, "0.05"), (8, "0.08"), (60, "0.50")])
def test_t_debours(n, t):
    assert T.t_debours(n) == D(t)


def test_seuils():
    assert T.s_debours() == D("1.00")
    assert T.t_tarif() == D("0.01") and T.s_tarif() == D("0.10")
    assert T.s_arith() == D("1.00") and T.s_calcul_declaration() == D("1.00")


def test_masse_quantite_colis():
    assert T.t_masse(D("50")) == D("0.5")
    assert T.t_masse(D("1000")) == D("5.000")
    assert T.t_quantite("C62", D("100")) == 0
    assert T.t_quantite("PR", D("100")) == 0
    assert T.t_quantite("KGM", D("1000")) == D("5.000")
    assert T.t_colis() == 0


def test_dans_tolerance():
    assert dans_tolerance(D("-0.05"), D("0.05"))
    assert not dans_tolerance(D("0.051"), D("0.05"))
