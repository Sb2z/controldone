"""Audit final, facturation (F-08, F-09, F-10, F-19, D-1313, D-1314)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from aides_facturation import FONDATEUR, SYSTEME, approuver

from controldone.facturation import EmissionRefusee
from controldone.outbox import FileSortante
from controldone.storage import facturation as stock

LE = date(2026, 10, 2)


def test_f08_paiement_stripe_remplace_le_brouillon_de_l_agent(service, db):
    from controldone.litiges import LigneFacture, payload_facture

    # l'agent a proposé l'échéance au prix par défaut (99,00), sans le paiement
    payload = payload_facture(
        "abonnement",
        [LigneFacture("Contrôle continu — abonnement 2026-10", Decimal("99.00"))],
        destinataires=["x@client-b-fictif.test"],
        raison_sociale="CLIENT B FICTIF SARL",
    )
    agent = FileSortante(db).proposer(
        "facture_emise",
        payload,
        SYSTEME,
        tenant_id="cli_b",
        idempotency_key="facture:abonnement:cli_b:2026-10",
    )
    a = service.proposer_abonnement(
        "cli_b",
        SYSTEME,
        palier="pro",
        mois="2026-10",
        deja_paye=Decimal("238.80"),
        reference_paiement="in_FICTIF",
    )
    assert a.id == agent.id
    # avant : le brouillon de l'agent (99,00, sans « déjà payé ») était renvoyé tel quel
    assert a.payload["total_ht"] == "199.00" and a.payload["facturation"]["deja_paye"] == "238.80"
    approuver(db, a.id)
    f = service.emettre(a.id, FONDATEUR, le=LE)
    assert f.contenu["net_a_payer"] == "0.00"


def test_f08_agent_ne_propose_pas_un_abonnement_stripe_actif(db, monkeypatch):
    from controldone.agents import outils
    from controldone.agents.base import ContexteAgent

    stock.enregistrer_compte_paiement(
        db,
        "cli_b",
        fournisseur="stripe",
        abonnement_id="sub_FICTIF",
        palier="intensif",
        statut_abonnement="active",
    )
    ctx = ContexteAgent.__new__(ContexteAgent)
    ctx.db, ctx.tenant_id = db, "cli_b"
    info = outils._abonnement(ctx, "cli_b", {})
    assert info == {
        "prix": "349.00",
        "palier": "intensif",
        "stripe_actif": True,
    }  # avant : 99,00 et actif ignoré


def test_f09_second_avoir_avant_emission_refuse(service, db):
    a = service.proposer_diagnostic("cli_a", FONDATEUR)
    approuver(db, a.id)
    f = service.emettre(a.id, FONDATEUR, le=LE)
    premier = service.proposer_avoir(f.id, FONDATEUR, motif="geste commercial", montant_ht=Decimal("10"))
    with pytest.raises(EmissionRefusee, match="non émis"):  # avant : renvoyait le premier (10,00) en silence
        service.proposer_avoir(f.id, FONDATEUR, motif="autre geste", montant_ht=Decimal("50"))
    FileSortante(db).refuser(premier.id, FONDATEUR, "erreur de saisie")
    second = service.proposer_avoir(f.id, FONDATEUR, motif="autre geste", montant_ht=Decimal("50"))
    assert second.id != premier.id and second.payload["total_ht"] == "50.00"


def test_f10_une_seule_source_du_taux_de_commission(service, db):
    from controldone.litiges.commission import taux_commission

    with db.operateur(FONDATEUR) as op:
        reglages = next(dict(t.reglages or {}) for t in op.lister_clients() if t.id == "cli_a")
        op.modifier_client("cli_a", reglages={**reglages, "commission_taux": "0.10"})
    a = service.proposer_commission("cli_a", FONDATEUR, base=Decimal("1000.00"), avoir_id="av_FICTIF")
    assert a.payload["total_ht"] == "100.00"  # avant : 200,00 (taux du catalogue) contre 100,00 côté litiges
    assert service.taux_commission("cli_a") == taux_commission({"commission_taux": "0.10"})
    assert taux_commission({}) == service.catalogue.taux_commission


def test_commission_jamais_sur_un_remboursement_d_administration(service):
    with pytest.raises(ValueError, match="administration"):
        service.proposer_commission(
            "cli_a", FONDATEUR, base=Decimal("100"), avoir_id="remb", origine="administration"
        )


def test_f19_frontiere_de_mois_de_paris():
    from controldone.calendrier import mois_paris
    from controldone.jobs.couts import mois_courant

    instant = datetime(2026, 9, 30, 22, 30, tzinfo=UTC)  # 1er octobre, 0 h 30 à Paris
    assert (
        mois_paris(instant) == mois_courant(instant) == "2026-10"
    )  # avant : plafond IA en mois UTC (« 2026-09 »)


def test_cumul_des_avoirs_verifie_sous_le_verrou_de_numerotation(service, db):
    a = service.proposer_diagnostic("cli_a", FONDATEUR)
    approuver(db, a.id)
    f = service.emettre(a.id, FONDATEUR, le=LE)
    av = service.proposer_avoir(f.id, FONDATEUR, motif="total")
    approuver(db, av.id)
    vus = []
    original = stock.cumul_avoirs

    def espion(s, fid):
        vus.append(fid)
        return original(s, fid)

    import controldone.storage.facturation as module

    module.cumul_avoirs = espion
    try:
        service.emettre(av.id, FONDATEUR, le=LE)
    finally:
        module.cumul_avoirs = original
    assert vus == [f.id]
