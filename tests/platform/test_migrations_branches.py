"""Couverture des migrations de schéma (``storage.migrations``, bloc O4, D-4901) : étapes idempotentes sur une
base partielle, colonne NOT NULL refusée, inscription concurrente (deux processus au démarrage), étape appliquée
pendant l'attente du verrou. SQLite seulement (PostgreSQL : ``test_migrations.py`` avec une base jetable)."""

from __future__ import annotations

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from controldone.storage import migrations as mig
from controldone.storage.models import Base


@pytest.fixture
def moteur(tmp_path):
    e = create_engine(f"sqlite:///{tmp_path}/m.db")
    yield e
    e.dispose()


def test_index_sur_table_absente_ignore(moteur):
    with moteur.begin() as conn:
        mig._creer_index(conn, "ix_x", "table_absente", ("a",))
        mig._m0002_index_journal_taches(conn)  # aucune des tables : rien à faire, sans erreur
    assert inspect(moteur).get_table_names() == []


def test_colonne_ajoutee_une_seule_fois(moteur):
    with moteur.begin() as conn:
        conn.execute(text("CREATE TABLE users (id VARCHAR(64) PRIMARY KEY)"))
        assert mig._ajouter_colonne(conn, "users", "langue") is True
        assert mig._ajouter_colonne(conn, "users", "langue") is False
        assert mig._ajouter_colonne(conn, "table_absente", "langue") is False
    assert "langue" in {c["name"] for c in inspect(moteur).get_columns("users")}


def test_colonne_non_nullable_refusee(moteur, monkeypatch):
    meta = MetaData()
    Table(
        "essai",
        meta,
        Column("id", Integer, primary_key=True),
        Column("obligatoire", String(5), nullable=False),
    )
    monkeypatch.setattr(mig.Base, "metadata", meta)
    with moteur.begin() as conn:
        conn.execute(text("CREATE TABLE essai (id INTEGER PRIMARY KEY)"))
        with pytest.raises(RuntimeError, match="nullable"):
            mig._ajouter_colonne(conn, "essai", "obligatoire")


def test_alertes_existantes_marquees_notifiees(moteur):
    with moteur.begin() as conn:
        conn.execute(text("CREATE TABLE alertes (id INTEGER PRIMARY KEY, cree_le TIMESTAMP)"))
        conn.execute(text("INSERT INTO alertes (id, cree_le) VALUES (1, '2026-09-01 12:00:00')"))
    with moteur.begin() as conn:
        mig._m0003_alertes_notifiees(conn)
        mig._m0003_alertes_notifiees(conn)  # idempotente
        assert conn.execute(text("SELECT notifiee_le FROM alertes")).scalar() == "2026-09-01 12:00:00"


def test_base_neuve_et_versions(moteur):
    assert mig.base_neuve(moteur)
    with moteur.connect() as conn:
        assert mig.versions_appliquees(conn) == set()
    mig.SchemaVersion.__table__.create(moteur)
    assert mig.base_neuve(moteur)  # schema_version seule ne compte pas
    Base.metadata.tables["users"].create(moteur)
    assert not mig.base_neuve(moteur)


def test_appliquer_puis_rien_en_attente(moteur):
    with moteur.begin() as conn:
        conn.execute(text("CREATE TABLE users (id VARCHAR(64) PRIMARY KEY)"))
    lignes: list[str] = []
    faites = mig.appliquer(moteur, journal=lignes.append)
    assert [m.version for m in faites] == [m.version for m in mig.MIGRATIONS]
    assert len(lignes) == len(mig.MIGRATIONS) and lignes[0].startswith("migration 0001 socle")
    assert mig.en_attente(moteur) == [] and mig.appliquer(moteur) == []


def test_inscription_concurrente_ignoree(moteur, monkeypatch):
    """Un autre processus inscrit la même étape entre la lecture et l'écriture : conflit ignoré."""
    vraie = mig._inscrire
    appels = []

    def inscrire(conn, m):
        appels.append(m.version)
        if m.version == 2:
            raise IntegrityError("INSERT", {}, Exception("déjà inscrite (FICTIF)"))
        vraie(conn, m)

    monkeypatch.setattr(mig, "_inscrire", inscrire)
    mig.inscrire_toutes(moteur)
    assert 2 in appels
    assert [m.version for m in mig.en_attente(moteur)] == [2]
    faites = mig.appliquer(moteur)  # rejouée, encore en conflit : ni levée, ni comptée
    assert faites == []


def test_etape_appliquee_pendant_l_attente_non_rejouee(moteur, monkeypatch):
    executees = []
    mig.SchemaVersion.__table__.create(moteur)
    premiere = mig.MIGRATIONS[0]
    vraies = mig.versions_appliquees
    lectures = [0]

    def versions(conn):
        lectures[0] += 1
        return {premiere.version} if lectures[0] > 1 else vraies(conn)  # inscrite par un autre entre-temps

    monkeypatch.setattr(mig, "versions_appliquees", versions)
    monkeypatch.setattr(
        mig, "MIGRATIONS", (mig.Migration(1, "socle", "test", lambda conn: executees.append(1)),)
    )
    assert mig.appliquer(moteur) == [] and executees == []
