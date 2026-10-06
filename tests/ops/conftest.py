"""Fixtures des tests d'exploitation : base SQLite temporaire, coffre, deux clients FICTIFS (A et B),
comptes client, données de litige. Aucun réseau, aucune clé d'API."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from aides_ops import FONDATEUR, peupler_litige
from cryptography.fernet import Fernet

from controldone.auth.motdepasse import hacher_mot_de_passe
from controldone.auth.roles import Acteur, Role
from controldone.storage import Database, FileVault
from controldone.storage.comptes import creer_utilisateur


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("CONTROLDONE_ENV", "test")
    monkeypatch.setenv("CONTROLDONE_MASTER_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("CONTROLDONE_DATA_DIR", str(tmp_path / "var"))
    monkeypatch.delenv("CONTROLDONE_VEILLE_RESEAU", raising=False)
    from controldone.config import reset_settings

    reset_settings()
    yield
    reset_settings()


@pytest.fixture
def db(tmp_path):
    base = Database(f"sqlite:///{tmp_path}/ops.db")
    base.creer_schema()
    yield base
    base.fermer()


@pytest.fixture
def vault(tmp_path):
    return FileVault(tmp_path / "coffre", [Fernet.generate_key()])


@dataclass
class Monde:
    db: Database
    vault: FileVault
    acteurs: dict[str, Acteur] = field(default_factory=dict)
    donnees: dict[str, dict] = field(default_factory=dict)


@pytest.fixture
def monde(db, vault) -> Monde:
    with db.operateur(FONDATEUR) as op:
        op.creer_client("cli_a", "CLIENT A FICTIF", reglages={"contacts": ["compta@client-a-fictif.test"]})
        op.creer_client("cli_b", "CLIENT B FICTIF")
    m = Monde(db=db, vault=vault, acteurs={"fondateur": FONDATEUR})
    h = hacher_mot_de_passe("phrase-de-passe-FICTIVE-123")
    for tenant, nom in (("cli_a", "admin_a"), ("cli_b", "admin_b")):
        creer_utilisateur(
            db,
            user_id=f"usr_{nom}",
            email=f"{nom}@exemple-fictif.test",
            mot_de_passe_hash=h,
            role=Role.client_admin,
            acteur=FONDATEUR,
        )
        with db.operateur(FONDATEUR) as op:
            op.client(tenant, "création des comptes de test").ajouter_membre(f"usr_{nom}", Role.client_admin)
        m.acteurs[nom] = Acteur(f"usr_{nom}", Role.client_admin, tenant)
    m.donnees["cli_a"] = peupler_litige(db, "cli_a", transitaire="tra_a")
    m.donnees["cli_b"] = peupler_litige(db, "cli_b", transitaire="tra_b")
    return m
