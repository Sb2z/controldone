"""Chargement explicite des composants (D-1214) : tout est chargé, ou l'échec est bruyant."""

import pytest

from controldone.controls import registry
from controldone.controls.registry import charger_controles, controles_enregistres
from controldone.controls.specs import ORDRE_CONTROLES


def test_les_59_controles_sont_enregistres():
    charger_controles()
    assert len(ORDRE_CONTROLES) == 59
    assert list(controles_enregistres()) == list(ORDRE_CONTROLES)


def test_controle_manquant_echoue_bruyamment(monkeypatch):
    charger_controles()
    incomplet = {k: v for k, v in registry._REGISTRE.items() if k != "C5"}
    monkeypatch.setattr(registry, "_REGISTRE", incomplet)
    monkeypatch.setattr(registry, "MODULES_CONTROLES", ())
    with pytest.raises(RuntimeError, match="C5"):
        charger_controles()


def test_module_de_controles_absent_echoue_bruyamment(monkeypatch):
    monkeypatch.setattr(registry, "MODULES_CONTROLES", ("controldone.controls.famille_inexistante",))
    with pytest.raises(ModuleNotFoundError):
        charger_controles()


def test_composants_par_defaut_complets():
    from controldone.ingest import Decoupeur
    from controldone.pipeline import composants_par_defaut

    c = composants_par_defaut()
    assert isinstance(c.decoupeur, Decoupeur)
    ids = {e.id for e in c.extracteurs}
    assert {
        "declaration_regles",
        "facture_commerciale_regles",
        "ft_regles",
        "avoir_regles",
        "support_regles",
    } <= ids
    assert {"structure_facture_xml", "structure_declaration_export"} <= ids


def test_extracteur_en_erreur_d_import_n_est_pas_avale(monkeypatch):
    import importlib
    import sys

    import controldone.extract.deterministe as paquet

    monkeypatch.setitem(sys.modules, "controldone.extract.deterministe.support", None)  # import impossible
    with pytest.raises(ImportError):
        importlib.reload(paquet)
    monkeypatch.undo()
    importlib.reload(paquet)
