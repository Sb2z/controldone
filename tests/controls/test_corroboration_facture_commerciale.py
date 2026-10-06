"""Réseau d'identités de la facture commerciale (controls/corroboration.py) : lignes q × PU, total, pieds de
facture (fret, assurance, remise), sous-total marchandises — branches non couvertes avant D-3902. FICTIF."""

from __future__ import annotations

from decimal import Decimal as D

from controldone.controls import corroboration
from controldone.model.champs import LigneFactureCommerciale, SousTotal
from controldone.model.enums import TypeSousTotal
from controldone.testing import contexte, facture_commerciale, vs

FC = "doc_fc_fictive"


def _v(chemin, x, **kw):
    return vs(f"facture_commerciale.{chemin}", x, document_id=FC, **kw) if x is not None else None


def _ligne(q, pu, m):
    return LigneFactureCommerciale(
        quantite=_v("lignes[].quantite", q),
        prix_unitaire=_v("lignes[].prix_unitaire", pu),
        montant_ligne=_v("lignes[].montant_ligne", m),
    )


def _st(type_, montant):
    return SousTotal(type=type_, montant=_v("sous_totaux[].montant", montant))


def _fc(*lignes, total=None, sous_totaux=()):
    return facture_commerciale(
        id=FC,
        numero=_v("numero", "INV-FICTIF-1"),
        lignes=list(lignes),
        total_facture=_v("total_facture", total),
        sous_totaux=list(sous_totaux),
    )


def _reseau(doc, utilisable=lambda v: v is not None):
    return {i.cle: i for i in corroboration.reseau(doc, utilisable, contexte([doc]).tol)}


def test_lignes_produit_et_total():
    r = _reseau(
        _fc(
            _ligne("3", "10.00", "30.00"),
            _ligne("2", "7.255", "14.51"),
            _ligne("1", "5.00", "5.00"),
            total="49.51",
        )
    )
    assert r["fc:ligne:0"].tient and r["fc:ligne:1"].tient  # prix unitaire à 3 décimales, arrondi au centime
    assert "fc:ligne:2" not in r  # quantité 1 : q × PU = PU, identité non probante
    assert r["fc:total"].tient and len(r["fc:total"].operandes) == 3


def test_ligne_fausse_et_total_faux():
    r = _reseau(_fc(_ligne("3", "10.00", "31.00"), _ligne("2", "5.00", "10.00"), total="40.00"))
    assert not r["fc:ligne:0"].tient
    assert not r["fc:total"].tient


def test_tolerance_ligne_proportionnelle_a_la_quantite():
    """Écart de 0,40 sur 100 pièces à prix unitaire arrondi : admis (½ centime par pièce) ; 0,60 refusé."""
    assert _reseau(_fc(_ligne("100", "0.123", "12.70")))["fc:ligne:0"].tient
    assert not _reseau(_fc(_ligne("100", "0.123", "12.90")))["fc:ligne:0"].tient


def test_pieds_de_facture_fret_assurance_remise():
    f = _fc(
        _ligne("2", "50.00", "100.00"),
        _ligne("4", "25.00", "100.00"),
        total="215.00",
        sous_totaux=[
            _st(TypeSousTotal.marchandises, "200.00"),
            _st(TypeSousTotal.fret, "20.00"),
            _st(TypeSousTotal.assurance, "5.00"),
            _st(TypeSousTotal.remise, "-10.00"),
            _st(TypeSousTotal.autre, "999.00"),
        ],
    )
    r = _reseau(f)
    assert not r["fc:total"].tient  # lignes seules ≠ total : les pieds manquent
    assert r["fc:total_pieds"].tient  # 200 + 20 + 5 − 10 (remise toujours soustraite, signe imprimé ou non)
    assert r["fc:sous_total:0"].tient  # sous-total marchandises = Σ lignes
    assert r["fc:total_sous_total:0"].tient  # total = sous-total + pieds
    assert len(r["fc:total_pieds"].operandes) == 5  # « autre » n'entre pas dans la somme


def test_remise_imprimee_positive_soustraite():
    r = _reseau(
        _fc(_ligne("2", "50.00", "100.00"), total="90.00", sous_totaux=[_st(TypeSousTotal.remise, "10.00")])
    )
    assert r["fc:total_pieds"].tient


def test_sous_total_marchandises_faux():
    r = _reseau(
        _fc(
            _ligne("2", "50.00", "100.00"),
            total="100.00",
            sous_totaux=[_st(TypeSousTotal.marchandises, "110.00")],
        )
    )
    assert r["fc:total"].tient
    assert not r["fc:sous_total:0"].tient
    assert "fc:total_pieds" not in r and "fc:total_sous_total:0" not in r


def test_total_absent_ou_ligne_illisible_pas_de_somme():
    assert "fc:total" not in _reseau(_fc(_ligne("2", "5.00", "10.00")))
    assert "fc:total" not in _reseau(
        _fc(_ligne("2", "5.00", None), _ligne("1", "3.00", "3.00"), total="13.00")
    )
    assert "fc:total" not in _reseau(_fc(total="13.00"))


def test_valeurs_inutilisables_ou_derivees_ignorees():
    f = _fc(_ligne("2", "5.00", "10.00"), total="10.00")
    assert _reseau(f, utilisable=lambda v: False) == {}
    derive = _fc(
        LigneFactureCommerciale(
            quantite=_v("lignes[].quantite", "2"),
            prix_unitaire=_v("lignes[].prix_unitaire", "5.00"),
            montant_ligne=_v("lignes[].montant_ligne", "10.00", methode="derive", regle_derivation="q_x_pu"),
        ),
        total="10.00",
    )
    assert _reseau(derive) == {}  # une valeur dérivée ne corrobore rien


def test_valeur_non_numerique_ignoree():
    r = _reseau(_fc(_ligne("deux", "5.00", "10.00"), total="10.00"))
    assert "fc:ligne:0" not in r and r["fc:total"].tient


def test_rangees_des_lignes():
    f = _fc(_ligne("2", "5.00", "10.00"), _ligne("1", "3.00", "3.00"), total="13.00")
    rang = corroboration.rangees(f)
    assert rang[f.fc.lignes[1].montant_ligne.id] == "lignes[1]"
    assert f.fc.total_facture.id not in rang


def test_montant_signe_negatif_lu():
    assert corroboration._Lecteur(lambda v: True).num(_v("total_facture", "-12.50")) == D("-12.50")
