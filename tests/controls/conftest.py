"""Tests unitaires de la logique des contrôles (familles A à G).

Ces tests bâtissent des documents **minimaux** : une ligne, un total, sans la redondance arithmétique d'un
document réel. La lecture corroborée (D-1700) les classerait tous ``a_verifier`` faute d'identité qui confirme
la lecture : elle n'est donc pas exigée ici, sauf dans ``test_corroboration.py`` qui l'éprouve (et sauf si le
test passe explicitement ``exiger_lecture_corroboree``). Les tests de bout en bout (``tests/assembly``,
``tests/test_famille_b1.py``, ``tests/test_findings_io.py``) l'exigent, comme la production.
"""

from __future__ import annotations

import functools

import pytest

from controldone.controls.context import ControlContext


@pytest.fixture(autouse=True)
def _lecture_corroboree_non_exigee(request, monkeypatch):
    if request.module.__name__.endswith("test_corroboration"):
        yield
        return
    origine = ControlContext.construire.__func__

    @functools.wraps(origine)
    def construire(cls, *args, exiger_lecture_corroboree=False, **kwargs):
        return origine(cls, *args, exiger_lecture_corroboree=exiger_lecture_corroboree, **kwargs)

    monkeypatch.setattr(ControlContext, "construire", classmethod(construire))
    yield
