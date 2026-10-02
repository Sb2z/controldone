"""Fixtures de la facturation : base SQLite temporaire, deux clients FICTIFS avec identité de facturation,
catalogue lu dans ``config/offres.yaml``, plateforme agréée et paiement en bouchon. Aucun réseau, aucune
clé Stripe (les variables ``STRIPE_*`` sont retirées)."""

from __future__ import annotations

from dataclasses import replace

import pytest
from aides_facturation import CONFIG, FACTURATION_A, FACTURATION_B, FONDATEUR, VENDEUR_FICTIF
from cryptography.fernet import Fernet

from controldone.facturation import (
    PaiementBouchon,
    PlateformeAgreeeBouchon,
    ServiceFacturation,
    charger_offres,
)
from controldone.storage import Database


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("CONTROLDONE_ENV", "test")
    monkeypatch.setenv("CONTROLDONE_MASTER_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("CONTROLDONE_DATA_DIR", str(tmp_path / "var"))
    for k in ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "STRIPE_LIVE_OK", "CONTROLDONE_TVA_APPLICABLE"):
        monkeypatch.delenv(k, raising=False)
    from controldone.config import reset_settings

    reset_settings()
    yield
    reset_settings()


@pytest.fixture
def db(tmp_path):
    base = Database(f"sqlite:///{tmp_path}/facturation.db")
    base.creer_schema()
    with base.operateur(FONDATEUR) as op:
        op.creer_client("cli_a", "CLIENT A FICTIF SAS", offre="diagnostic",
                        reglages={"contacts": ["compta@client-a-fictif.test"], "facturation": FACTURATION_A})
        op.creer_client("cli_b", "CLIENT B FICTIF SARL", offre="continu", reglages={"facturation": FACTURATION_B})
        for i in range(3):
            op.creer_client(f"cli_c{i}", f"CLIENT C{i} FICTIF", reglages={"facturation": {"siren": f"00000010{i}"}})
    yield base
    base.fermer()


@pytest.fixture
def catalogue():
    c = charger_offres(CONFIG, env={})
    return replace(c, vendeur=replace(c.vendeur, **VENDEUR_FICTIF))


@pytest.fixture
def pa(tmp_path) -> PlateformeAgreeeBouchon:
    return PlateformeAgreeeBouchon(tmp_path / "pa_bouchon")


@pytest.fixture
def bouchon(tmp_path) -> PaiementBouchon:
    return PaiementBouchon(tmp_path / "paiement_bouchon", "whsec_test_FICTIF")


@pytest.fixture
def service(db, catalogue, pa, bouchon, tmp_path) -> ServiceFacturation:
    return ServiceFacturation(db, catalogue=catalogue, pa=pa, paiement=bouchon, dossier_sorties=tmp_path / "sorties",
                              prod=False)
