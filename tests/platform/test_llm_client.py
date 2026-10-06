"""Lecture par modèle côté plateforme (D-4004, D-4007) : opt-out du client, plafond mensuel transmis au pipeline
pour être vérifié avant chaque appel. Faux pipeline, aucun réseau."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from aides_plateforme import FONDATEUR, SYSTEME

from controldone.jobs import enqueue, etat_plafond
from controldone.jobs import handlers as handlers_mod
from controldone.jobs.couts import enregistrer_cout, llm_desactive
from controldone.jobs.worker import Worker
from controldone.storage.coltypes import maintenant


class _Horloge:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def horloge():
    return _Horloge(maintenant() + timedelta(seconds=1))


def test_llm_desactive_valeurs():
    assert llm_desactive({"llm_desactive": True}) and llm_desactive({"llm_desactive": "oui"})
    assert not llm_desactive({}) and not llm_desactive(None) and not llm_desactive({"llm_desactive": "non"})


def test_opt_out_du_client(monde):
    assert etat_plafond("cli_a", db=monde.db).llm_autorise
    with monde.db.operateur(FONDATEUR) as op:
        op.modifier_client("cli_a", reglages={"llm_desactive": True})
    e = etat_plafond("cli_a", db=monde.db)
    assert e.desactive and not e.llm_autorise and not e.arret
    assert etat_plafond("cli_b", db=monde.db).llm_autorise  # aucun effet sur un autre client


def _capturer(appels: list):
    def traiter(source, profil, grilles, *, options):
        appels.append(options)
        return []

    return traiter


def _traiter(monde, horloge, monkeypatch, cle: str) -> list:
    from controldone.pipeline import OptionsPipeline

    appels: list = []
    monkeypatch.setattr(handlers_mod, "charger_pipeline", lambda: (_capturer(appels), OptionsPipeline))
    enqueue("traiter_lot", {"lot_id": "lot_a"}, cle, "cli_a", db=monde.db)
    w = Worker(
        monde.db,
        handlers={"traiter_lot": handlers_mod.traiter_lot},
        services={"vault": monde.vault},
        horloge=horloge,
        worker_id="w_llm",
        poll_s=0.01,
    )
    w.executer_un()
    return appels


def test_worker_transmet_plafond_et_opt_out(monde, horloge, monkeypatch):
    with monde.db.operateur(FONDATEUR) as op:
        op.modifier_client("cli_a", plafond_cout_ia_mensuel_eur=Decimal("10.00"))
    with monde.db.tenant("cli_a", SYSTEME) as sc:
        enregistrer_cout(sc, cout_eur=Decimal("3.00"))
    (o,) = _traiter(monde, horloge, monkeypatch, "k1")
    assert o.llm is True and o.plafond_ia_client_mensuel_eur == Decimal("10.00")
    assert o.cout_ia_mois_eur == Decimal("3.00")
    with monde.db.operateur(FONDATEUR) as op:
        op.modifier_client("cli_a", reglages={"llm_desactive": True})
    from controldone.storage.models import Lot

    with monde.db.tenant("cli_a", SYSTEME) as sc:
        sc.obtenir(Lot, "lot_a").statut = "recu"
    (o,) = _traiter(monde, horloge, monkeypatch, "k2")
    assert o.llm is False
