"""Extracteur déterministe des documents support (SPEC §5.3.5)."""

from __future__ import annotations

from decimal import Decimal

import fixtures_fc as fx

from controldone.extract.deterministe import EXTRACTEURS_DETERMINISTES
from controldone.extract.deterministe.support import ExtracteurSupport
from controldone.model import Document
from controldone.model.enums import TypeDocument


def _sup(contenu: bytes, sous_type: str):
    r = fx.extraire(contenu, TypeDocument.document_support, sous_type=sous_type)
    assert r.champs is not None
    return r.champs


def test_registre():
    ext = EXTRACTEURS_DETERMINISTES["document_support"]
    assert isinstance(ext, ExtracteurSupport)
    assert not ext.supports(Document(type=TypeDocument.avoir), [])


def test_lta_tableau_entete_valeurs_maitre_et_maison():
    ch = _sup(fx.lta(), "titre_transport")
    assert ch.ref_transport_maitre.valeur == "999-70166073"
    assert ch.ref_transport_maison.valeur == "HWB-0042-77"
    assert ch.nombre_colis.valeur == "13"
    assert ch.masse_brute.decimal() == Decimal("258.806") and ch.masse_brute.unite == "KGM"
    assert ch.masse_taxable.decimal() == Decimal("312.500")
    # « 258.806 » sans autre indice : séparateur décimal présumé (3 décimales de masse) -> confiance réduite
    assert ch.masse_brute.confiance <= 0.7
    assert ch.expediteur.nom.valeur == "Pacific Sample Trading Inc. (FICTITIOUS)"
    assert ch.destinataire.nom.valeur == "Lumen Industrie SAS (FICTIF)"
    assert ch.destinataire.tva.valeur == fx.TVA_ACHETEUR
    assert ch.expediteur.tva is None
    for v in ch.iter_valeurs():
        assert v.ancree and v.page == 1 and v.zone is not None


def test_liste_colisage_totaux_et_reference_facture():
    ch = _sup(fx.liste_colisage(), "liste_colisage")
    assert ch.ref_transport_maitre.valeur == "DEMO307604768"
    # totaux de pied, jamais la première ligne du tableau des articles
    assert ch.masse_brute.decimal() == Decimal("1081.689") and ch.masse_brute.confiance >= 0.9
    assert ch.masse_nette.decimal() == Decimal("898.765")
    assert ch.nombre_colis.valeur == "329"
    assert [v.valeur for v in ch.refs_facture] == ["FAC/2026/0012-0"]
    assert ch.destinataire.nom.valeur == "Brindille Cosmétiques SAS (FICTIF)"
    assert ch.destinataire.tva is None  # « DEMO307604768 » n'est pas une TVA


def test_lettre_accompagnement_sans_masse_ni_colis():
    ch = _sup(fx.lettre_accompagnement(), "lettre_accompagnement")
    assert [v.valeur for v in ch.refs_facture] == ["FAC-2610007"]
    assert ch.masse_brute is None and ch.nombre_colis is None and ch.ref_transport_maitre is None
