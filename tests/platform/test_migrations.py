"""Migrations de schéma versionnées (D-3503) : base neuve inscrite d'office, base ancienne (sans
``schema_version``, sans index ni colonne récente, sans tables récentes) migrée, étapes idempotentes, refus au
démarrage en production, migration automatique en dev/test, ``controldone migrer`` avec sauvegarde préalable.
SQLite toujours ; PostgreSQL si ``CONTROLDONE_TEST_PG_URL`` désigne un serveur jetable."""

from __future__ import annotations

from datetime import datetime

import pytest
from aides_pg import base_pg  # noqa: F401  (fixture)
from sqlalchemy import inspect, text

from controldone.config import reset_settings
from controldone.storage import Database, SchemaPerime
from controldone.storage.migrations import MIGRATIONS, appliquer, en_attente

INDEX = {"audit_log": {"ix_audit_log_action", "ix_audit_log_actor", "ix_audit_log_ts"},
         "jobs": {"ix_jobs_statut_cree", "ix_jobs_kind_statut", "ix_jobs_cree"}}
TABLES_RECENTES = ("debit_compteurs", "sessions_revoquees", "sessions_actives", "notifications_alertes")


def _index(db: Database, table: str) -> set[str]:
    return {i["name"] for i in inspect(db.engine).get_indexes(table)}


def _vieillir(db: Database) -> None:
    """Ramène la base à l'état d'une base créée avant les migrations (et avant les tables récentes)."""
    with db.engine.begin() as c:
        c.execute(text("DROP TABLE schema_version"))
        for noms in INDEX.values():
            for nom in noms:
                c.execute(text(f'DROP INDEX IF EXISTS "{nom}"'))
        c.execute(text('DROP INDEX IF EXISTS "ix_alertes_notifiee_le"'))
        c.execute(text("ALTER TABLE alertes DROP COLUMN notifiee_le"))
        for t in TABLES_RECENTES:
            c.execute(text(f'DROP TABLE IF EXISTS "{t}"'))


def _verifier_a_jour(db: Database) -> None:
    assert db.migrations_en_attente() == []
    for table, noms in INDEX.items():
        assert noms <= _index(db, table), table
    tables = set(inspect(db.engine).get_table_names())
    assert set(TABLES_RECENTES) <= tables
    assert "notifiee_le" in {c["name"] for c in inspect(db.engine).get_columns("alertes")}
    assert db.colonnes_manquantes() == []


def _scenario(url: str, monkeypatch) -> None:
    db = Database(url)
    try:
        db.creer_schema()
        assert db.migrations_en_attente() == []  # base neuve : toutes inscrites sans être exécutées
        _verifier_a_jour(db)
        with db.engine.begin() as c:  # alerte existante avant la mise à jour
            c.execute(text("INSERT INTO alertes (cle, kind, message, details, cree_le) VALUES "
                           "('k1', 'job_mort', 'FICTIF', '{}', :d)"), {"d": datetime(2026, 1, 1)})
        _vieillir(db)
        assert [m.version for m in db.migrations_en_attente()] == [m.version for m in MIGRATIONS]
        monkeypatch.setenv("CONTROLDONE_ENV", "prod")
        monkeypatch.delenv("CONTROLDONE_MIGRATION_AUTO", raising=False)
        with pytest.raises(SchemaPerime, match="controldone migrer"):
            db.exiger_schema_a_jour()
        faites = db.migrer()
        assert [m.nom for m in faites] == [m.nom for m in MIGRATIONS]
        _verifier_a_jour(db)
        db.exiger_schema_a_jour()
        with db.engine.connect() as c:  # l'historique n'est pas « à notifier »
            assert c.execute(text("SELECT notifiee_le FROM alertes WHERE cle = 'k1'")).scalar() is not None
        # idempotence : chaque étape rejouée sur une base déjà à jour ne change rien et ne lève pas
        with db.engine.begin() as c:
            c.execute(text("DELETE FROM schema_version"))
        assert len(appliquer(db.engine)) == len(MIGRATIONS)
        _verifier_a_jour(db)
    finally:
        db.fermer()


def test_migrations_sqlite(tmp_path, monkeypatch):
    _scenario(f"sqlite:///{tmp_path}/m.db", monkeypatch)


def test_migrations_postgresql(base_pg, monkeypatch):  # noqa: F811
    _scenario(base_pg, monkeypatch)


def test_creer_schema_sans_migrer_laisse_les_etapes_en_attente(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path}/m.db"
    db = Database(url)
    db.creer_schema()
    _vieillir(db)
    db.creer_schema(migrer=False)  # « serve --init-schema » : tables manquantes seulement
    assert len(db.migrations_en_attente()) == len(MIGRATIONS)
    monkeypatch.setenv("CONTROLDONE_ENV", "prod")
    monkeypatch.setenv("CONTROLDONE_MIGRATION_AUTO", "1")  # migration au démarrage choisie explicitement
    db.exiger_schema_a_jour()
    _verifier_a_jour(db)
    db.fermer()


def test_dev_migre_au_demarrage(tmp_path, monkeypatch):
    db = Database(f"sqlite:///{tmp_path}/m.db")
    db.creer_schema()
    _vieillir(db)
    monkeypatch.setenv("CONTROLDONE_ENV", "dev")
    db.exiger_schema_a_jour()
    _verifier_a_jour(db)
    db.fermer()


def test_worker_refuse_en_production_sans_migration(tmp_path, monkeypatch):
    from controldone.jobs import worker

    url = f"sqlite:///{tmp_path}/m.db"
    db = Database(url)
    db.creer_schema()
    _vieillir(db)
    db.fermer()
    monkeypatch.setenv("CONTROLDONE_ENV", "prod")
    monkeypatch.setenv("CONTROLDONE_SECRET_KEY", "s" * 40)
    monkeypatch.setenv("CONTROLDONE_DATABASE_URL", url)
    monkeypatch.setenv("CONTROLDONE_TMP_DIR", str(tmp_path / "tmp"))
    monkeypatch.setenv("CONTROLDONE_MIGRATION_ATTENTE_S", "0")  # pas d'attente du service « migrer » (D-4102)
    reset_settings()
    try:
        assert worker.main(["--once"]) == 3
    finally:
        reset_settings()


def test_attente_production_demarre_des_que_la_migration_est_faite(tmp_path, monkeypatch):
    """D-4102 : en production, une migration en attente fait attendre le démarrage (message clair) au lieu
    d'une sortie immédiate ; le processus démarre de lui-même dès que « migrer » l'a appliquée."""
    import threading

    url = f"sqlite:///{tmp_path}/m.db"
    db = Database(url)
    db.creer_schema()
    _vieillir(db)
    monkeypatch.setenv("CONTROLDONE_ENV", "prod")
    monkeypatch.delenv("CONTROLDONE_MIGRATION_AUTO", raising=False)
    messages: list[str] = []
    autre = Database(url)  # le service ponctuel « migrer », dans un autre processus en production
    minuteur = threading.Timer(0.3, autre.migrer)
    minuteur.start()
    try:
        db.attendre_schema_a_jour(attente_s=30, intervalle_s=0.05, journal=messages.append)
    finally:
        minuteur.join()
        autre.fermer()
    _verifier_a_jour(db)
    assert "controldone migrer" in messages[0] and "démarrage suspendu" in messages[0]
    assert messages[-1].startswith("migrations appliquées")
    assert len(messages) == 2  # un message, pas une rafale (rappel toutes les 60 s)
    db.fermer()


def test_attente_production_sort_une_fois_apres_le_delai(tmp_path, monkeypatch):
    from controldone.storage import MigrationEnAttente

    db = Database(f"sqlite:///{tmp_path}/m.db")
    db.creer_schema()
    _vieillir(db)
    monkeypatch.setenv("CONTROLDONE_ENV", "prod")
    monkeypatch.delenv("CONTROLDONE_MIGRATION_AUTO", raising=False)
    messages: list[str] = []
    with pytest.raises(MigrationEnAttente, match="attente de 0 s écoulée"):
        db.attendre_schema_a_jour(attente_s=0.2, intervalle_s=0.05, rappel_s=60, journal=messages.append)
    assert len(messages) == 1 and len(db.migrations_en_attente()) == len(MIGRATIONS)  # rien n'est migré
    monkeypatch.setenv("CONTROLDONE_MIGRATION_ATTENTE_S", "0")
    with pytest.raises(MigrationEnAttente):
        db.attendre_schema_a_jour()  # réglage par l'environnement : sortie immédiate
    db.fermer()


def test_attente_inutile_pour_des_colonnes_sans_migration(tmp_path, monkeypatch):
    """Colonnes manquantes sans étape en attente : attendre ne réparerait rien, arrêt immédiat."""
    from controldone.storage import MigrationEnAttente

    db = Database(f"sqlite:///{tmp_path}/m.db")
    db.creer_schema()
    with db.engine.begin() as c:
        c.execute(text('DROP INDEX IF EXISTS "ix_alertes_notifiee_le"'))
        c.execute(text("ALTER TABLE alertes DROP COLUMN notifiee_le"))
    monkeypatch.setenv("CONTROLDONE_ENV", "prod")
    with pytest.raises(SchemaPerime, match="colonnes manquantes") as exc:
        db.attendre_schema_a_jour(attente_s=30, intervalle_s=0.05)
    assert not isinstance(exc.value, MigrationEnAttente)
    db.fermer()


def test_defaut_d_attente_selon_le_mode(tmp_path, monkeypatch):
    """600 s en production (service « migrer » en cours), aucune attente ailleurs (dev/test migrent seuls)."""
    import time as _time

    db = Database(f"sqlite:///{tmp_path}/m.db")
    db.creer_schema()
    _vieillir(db)
    monkeypatch.setenv("CONTROLDONE_ENV", "prod")
    monkeypatch.delenv("CONTROLDONE_MIGRATION_ATTENTE_S", raising=False)
    attentes: list[float] = []
    monkeypatch.setattr(_time, "sleep", lambda s: (attentes.append(s), (_ for _ in ()).throw(KeyboardInterrupt))[0])
    with pytest.raises(KeyboardInterrupt):
        db.attendre_schema_a_jour(intervalle_s=5)
    assert attentes == [5]
    monkeypatch.setenv("CONTROLDONE_MIGRATION_ATTENTE_S", "x")  # valeur illisible : défaut prudent (attente)
    with pytest.raises(KeyboardInterrupt):
        db.attendre_schema_a_jour(intervalle_s=5)
    monkeypatch.setenv("CONTROLDONE_ENV", "test")  # hors production : migration au démarrage, aucune attente
    monkeypatch.delenv("CONTROLDONE_MIGRATION_ATTENTE_S")
    db.attendre_schema_a_jour()
    assert db.migrations_en_attente() == []
    db.fermer()


def test_cli_migrer_sauvegarde_avant(tmp_path, monkeypatch, capsys):
    from controldone.cli import main

    url = f"sqlite:///{tmp_path}/var/m.db"
    db = Database(url)
    db.creer_schema()
    _vieillir(db)
    db.fermer()
    monkeypatch.setenv("CONTROLDONE_DATABASE_URL", url)
    reset_settings()
    try:
        assert main(["migrer", "--etat"]) == 0
        assert "0001 socle" in capsys.readouterr().out
        assert main(["migrer"]) == 0
        sortie = capsys.readouterr().out
        assert "sauvegarde avant migration" in sortie and "schéma à jour" in sortie
        assert list((tmp_path / "var" / "sauvegardes").glob("controldone-*.tar.gz.enc"))
        db = Database(url)
        _verifier_a_jour(db)
        db.fermer()
        assert main(["migrer"]) == 0  # rien à faire : aucune nouvelle sauvegarde
        assert len(list((tmp_path / "var" / "sauvegardes").glob("controldone-*.tar.gz.enc"))) == 1
    finally:
        reset_settings()


def test_cli_migrer_abandonne_si_la_sauvegarde_echoue(tmp_path, monkeypatch):
    from controldone.cli import main
    from controldone.storage import sauvegarde

    url = f"sqlite:///{tmp_path}/var/m.db"
    db = Database(url)
    db.creer_schema()
    _vieillir(db)
    db.fermer()
    monkeypatch.setenv("CONTROLDONE_DATABASE_URL", url)
    monkeypatch.setattr(sauvegarde, "main", lambda argv: 1)
    reset_settings()
    try:
        assert main(["migrer"]) == 1
        db = Database(url)
        assert len(en_attente(db.engine)) == len(MIGRATIONS)  # rien n'a été touché
        db.fermer()
    finally:
        reset_settings()


def test_migrations_ordonnees_et_uniques():
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions) == list(range(1, len(versions) + 1))
    assert len({m.nom for m in MIGRATIONS}) == len(MIGRATIONS)


def test_index_declares_dans_les_modeles():
    """Une base neuve ne passe pas par les étapes : chaque index migré doit aussi être déclaré."""
    from controldone.storage.models import Base

    for table, noms in INDEX.items():
        assert noms <= {i.name for i in Base.metadata.tables[table].indexes}
    assert "notifiee_le" in Base.metadata.tables["alertes"].c

