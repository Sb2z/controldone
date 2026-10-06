"""Plateforme agréée partenaire du fondateur (bouchon) : dépôt idempotent, statuts de cycle de vie."""

from __future__ import annotations

from datetime import date

import pytest
from aides_facturation import FONDATEUR, approuver

from controldone.facturation.pa import STATUTS_OBLIGATOIRES, FactureADeposer, PlateformeAgreee
from controldone.storage import facturation as stock


def test_bouchon_respecte_l_interface(pa):
    assert isinstance(pa, PlateformeAgreee)
    assert set(STATUTS_OBLIGATOIRES) == {"200", "210", "212", "213"}


def test_depot_idempotent_et_statuts(pa):
    f = FactureADeposer(
        numero="F-2026-0001", facture_id="fac_1", siren_acheteur="000000001", contenu=b"%PDF-1.4 FICTIF"
    )
    a1 = pa.deposer_facture(f)
    a2 = pa.deposer_facture(f)
    assert a1 == a2 and a1.code == "200"
    assert len(list((pa.racine / "deposees").glob("*.pdf"))) == 1
    pa.simuler_statut(a1.identifiant_pa, "203")
    pa.simuler_statut(a1.identifiant_pa, "212")
    recus = pa.recevoir_statuts()
    assert [s.code for s in recus] == ["200", "203", "212"] and recus[-1].libelle == "Encaissée"
    assert pa.recevoir_statuts() == []  # chaque statut n'est rendu qu'une fois
    assert pa.statut(a1.identifiant_pa).code == "212"
    with pytest.raises(ValueError):
        pa.simuler_statut(a1.identifiant_pa, "999")
    with pytest.raises(KeyError):
        pa.simuler_statut("PA-INCONNUE", "200")
    with pytest.raises(ValueError):
        pa.deposer_facture(FactureADeposer(numero="X", facture_id="x", siren_acheteur="", contenu=b"<xml/>"))


def test_synchronisation_des_statuts_en_base(service, db, pa):
    a = service.proposer_diagnostic("cli_a", FONDATEUR)
    approuver(db, a.id)
    f = service.emettre_et_deposer(a.id, FONDATEUR, le=date(2026, 10, 2))
    ident = f"PA-BOUCHON-{f.numero}"
    pa.simuler_statut(ident, "210", motif="Facture mal adressée (FICTIF)")
    assert service.synchroniser_statuts_pa() == 1  # le 200 du dépôt est déjà enregistré
    assert service.synchroniser_statuts_pa() == 0
    statuts = stock.statuts_pa(db, facture_id=f.id)
    assert [s.code for s in statuts] == ["200", "210"] and statuts[-1].motif.startswith(
        "Facture mal adressée"
    )


def test_documentation_ne_pretend_pas_etre_une_pa():
    from pathlib import Path

    import controldone.facturation.pa as module

    assert "n'est pas une plateforme agréée et ne prétend pas l'être" in module.__doc__
    doc = (Path(__file__).resolve().parents[2] / "docs" / "FACTURATION.md").read_text(encoding="utf-8")
    assert (
        "n'est pas une plateforme agréée" in doc
        and "1er septembre 2026" in doc
        and "1er septembre 2027" in doc
    )
