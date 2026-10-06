import json

from controldone.controls.framework import (
    CONTROL_SPECS,
    ORDRE_CONTROLES,
    get_spec,
    specs_as_dicts,
    specs_json,
)
from controldone.model import NatureMontant


def test_annexe_a_complete():
    attendus = (
        [f"P{i}" for i in range(1, 6)]
        + [f"A{i}" for i in range(1, 16)]
        + [f"B{i}" for i in range(1, 6)]
        + [f"C{i}" for i in range(1, 9)]
        + [f"D{i}" for i in range(1, 10)]
        + [f"E{i}" for i in range(1, 7)]
        + [f"F{i}" for i in range(1, 6)]
        + [f"G{i}" for i in range(1, 7)]
    )
    assert list(ORDRE_CONTROLES) == attendus


def test_quelques_lignes():
    assert get_spec("C5").equivalents == ("C5", "C1", "C2", "C3", "C4")
    assert (
        get_spec("A12").nature_montant is NatureMontant.renvoi and get_spec("A12").eligible_certain is False
    )
    assert (
        get_spec("D8").eligible_certain is False
        and get_spec("D8").nature_montant is NatureMontant.recouvrable
    )
    assert get_spec("B4").eligible_certain is True and get_spec("B4").note == "oui (a), non (b)"
    assert get_spec("P3").eligible_certain is None and not get_spec("P3").produit_constat
    assert get_spec("G4").equivalents == ("G4", "G5", "C1", "C5")
    assert get_spec("F5").nature_montant is NatureMontant.ecart_documentaire


def test_coherence():
    for s in CONTROL_SPECS.values():
        if s.produit_constat:
            assert s.id in s.equivalents
        if s.est_renvoi:
            assert s.eligible_certain is False


def test_export():
    d = specs_as_dicts()
    assert len(d) == 59 and d[0]["id"] == "P1"
    assert json.loads(specs_json())[20]["id"] == "B1"
