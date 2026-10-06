"""Sauvegarde PostgreSQL (D-3501) : dump ``pg_dump --format=custom`` dans l'archive ``CDSAV2`` + manifeste,
vérification, restauration dans une base vide, contrôle approfondi.

- Sans serveur : archive construite avec un faux dump (en-tête ``PGDMP``), outils remplacés — chemin de la ligne
  de commande, relecture, refus d'un dump illisible, paramètres de connexion jamais en argument.
- Avec un serveur jetable (``CONTROLDONE_TEST_PG_URL``, ``scripts/pg_jetable.sh``) : le vrai ``pg_dump`` /
  ``pg_restore`` sur une base peuplée, instantané cohérent, base cible non vide refusée, contrôle approfondi.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from aides_pg import base_pg, serveur_pg  # noqa: F401  (fixture)
from cryptography.fernet import Fernet

from controldone.config import reset_settings
from controldone.storage import ErreurIntegrite
from controldone.storage import sauvegarde as sv
from controldone.storage.controle_restauration import controler

URL_FICTIVE = "postgresql+pg8000://cd_fictif:MOTDEPASSE-FICTIF@db-fictive.test:5433/controldone?sslmode=require"


def _archive_factice(tmp_path: Path, cles: list[bytes], contenu: bytes) -> Path:
    def preparer(tmp: Path):
        dump = tmp / "controldone.dump"
        dump.write_bytes(contenu)
        return dump, "base/controldone.dump", {"moteur": "postgresql", "integrite": "ok", "tables": {"tenants": 2},
                                               "audit": {"entrees": 0, "tete": None}}

    coffre = tmp_path / "coffre" / "cli_a" / "fichiers"
    coffre.mkdir(parents=True)
    (coffre / "objet").write_bytes(b"objet chiffre FICTIF")
    return sv._creer_archive(tmp_path / "sv", cles, None, None, tmp_path / "coffre", None, preparer)


def test_env_libpq_sans_mot_de_passe_en_argument():
    env = sv._env_libpq(URL_FICTIVE)
    assert (env["PGHOST"], env["PGPORT"], env["PGUSER"], env["PGDATABASE"]) == (
        "db-fictive.test", "5433", "cd_fictif", "controldone")
    assert env["PGPASSWORD"] == "MOTDEPASSE-FICTIF" and env["PGSSLMODE"] == "require"


def test_archive_avec_dump_verifiee_et_restauree(tmp_path, monkeypatch):
    cles = [Fernet.generate_key()]
    archive = _archive_factice(tmp_path, cles, b"PGDMP" + b"\x00" * 64)
    r = sv.verifier(archive, cles)
    assert r.ok, r.problemes
    assert r.manifeste["base"]["moteur"] == "postgresql"
    assert "base/controldone.dump" in r.manifeste["fichiers"]

    def absent(nom):
        raise sv.OutilAbsent(nom)

    monkeypatch.setattr(sv, "_outil", absent)  # pas de pg_restore : relecture du dump sautée, fichiers restaurés
    cible = sv.restaurer(archive, tmp_path / "r", cles)
    assert (cible / "base" / "controldone.dump").read_bytes().startswith(b"PGDMP")
    rapport = controler(cible, cles)
    assert not rapport.ok and "base PostgreSQL non chargée" in rapport.problemes[0]


def test_dump_illisible_refuse(tmp_path):
    cles = [Fernet.generate_key()]
    archive = _archive_factice(tmp_path, cles, b"pas un dump")
    assert any("dump PostgreSQL illisible" in p for p in sv.verifier(archive, cles).problemes)
    with pytest.raises(ErreurIntegrite, match="dump PostgreSQL illisible"):
        sv.restaurer(archive, tmp_path / "r", cles)


def test_cli_choisit_pg_dump_pour_une_base_postgresql(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CONTROLDONE_DATABASE_URL", URL_FICTIVE)
    monkeypatch.setenv("CONTROLDONE_DATA_DIR", str(tmp_path / "var"))
    pytest.importorskip("pg8000")  # Database() ouvre le moteur (sans se connecter)
    appels = {}

    def faux(url, coffre, destination, cles, **kw):
        appels["url"] = url
        return _archive_factice(tmp_path, cles, b"PGDMP" + b"\x01" * 32)

    monkeypatch.setattr(sv, "sauvegarder_postgresql", faux)
    reset_settings()
    try:
        assert sv.main(["sauvegarder", "--destination", str(tmp_path / "sv"), "--sans-rotation"]) == sv.OK
    finally:
        reset_settings()
    assert appels["url"] == URL_FICTIVE
    assert "CONFORME" in capsys.readouterr().out


def test_pg_dump_absent_code_configuration(tmp_path, monkeypatch):
    pytest.importorskip("pg8000")
    monkeypatch.setenv("CONTROLDONE_DATABASE_URL", URL_FICTIVE)
    monkeypatch.setenv("CONTROLDONE_PG_DUMP", "pg_dump_introuvable_fictif")
    alertes = []
    monkeypatch.setattr(sv, "alerter", lambda kind, message, details=None: alertes.append(kind))
    reset_settings()
    try:
        assert sv.main(["sauvegarder", "--destination", str(tmp_path / "sv")]) == sv.ECHEC_CONFIGURATION
    finally:
        reset_settings()
    assert alertes == ["sauvegarde_echec"]


# --- serveur PostgreSQL réel (jetable) --------------------------------------------------------------------


def _peupler(url: str, cles: list[bytes], racine: Path) -> None:
    from aides_plateforme import FONDATEUR

    from controldone.storage import Database, FileVault

    db = Database(url)
    db.creer_schema()
    with db.operateur(FONDATEUR) as op:
        op.creer_client("cli_a", "CLIENT A FICTIF")
        op.creer_client("cli_b", "CLIENT B FICTIF")
    FileVault(racine / "coffre", cles)
    db.fermer()


def test_postgresql_reel_sauvegarde_restauration(base_pg, tmp_path, monkeypatch):  # noqa: F811
    from controldone.storage import Database

    cles = [Fernet.generate_key()]
    _peupler(base_pg, cles, tmp_path)
    avant = sv.instantane_postgresql(base_pg)
    assert avant["tables"]["tenants"] == 2 and avant["audit"]["entrees"] >= 2
    archive = sv.sauvegarder_postgresql(base_pg, tmp_path / "coffre", tmp_path / "sv", cles)
    brut = archive.read_bytes()
    assert b"PGDMP" not in brut and b"CLIENT A FICTIF" not in brut  # chiffré
    r = sv.verifier(archive, cles)
    assert r.ok, r.problemes
    assert r.manifeste["base"]["tables"] == avant["tables"]
    assert r.manifeste["base"]["audit"] == avant["audit"]
    cible = sv.restaurer(archive, tmp_path / "r", cles)

    serveur = serveur_pg()
    nom = "cd_test_cible_" + os.urandom(4).hex()
    url_cible = sv.creer_base_pg(serveur, nom)
    try:
        etat = sv.restaurer_postgresql(cible / "base" / "controldone.dump", url_cible)
        assert etat["tables"] == avant["tables"] and etat["audit"] == avant["audit"]
        rapport = controler(cible, cles, base_url=url_cible)
        assert rapport.ok, rapport.problemes
        with pytest.raises(FileExistsError, match="pas vide"):  # jamais par-dessus une base remplie
            sv.restaurer_postgresql(cible / "base" / "controldone.dump", url_cible)
        db = Database(url_cible)  # le journal restauré reste append-only (déclencheurs restaurés)
        from sqlalchemy import text

        with pytest.raises(Exception, match="append-only"), db.engine.begin() as c:
            c.execute(text("DELETE FROM audit_log"))
        db.fermer()
    finally:
        sv.supprimer_base_pg(serveur, nom)


def test_postgresql_reel_verification_profonde(base_pg, tmp_path, monkeypatch):  # noqa: F811
    cles = [Fernet.generate_key()]
    _peupler(base_pg, cles, tmp_path)
    archive = sv.sauvegarder_postgresql(base_pg, tmp_path / "coffre", tmp_path / "sv", cles)
    monkeypatch.delenv("BACKUP_PG_VERIFICATION_URL", raising=False)
    problemes, remarques = sv._verification_profonde(archive, cles)
    assert problemes == [] and "non fait" in remarques[0]
    monkeypatch.setenv("BACKUP_PG_VERIFICATION_URL", serveur_pg())
    problemes, remarques = sv._verification_profonde(archive, cles)
    assert problemes == [] and "chargée à l'essai" in remarques[0]
    problemes, _ = sv._verification_profonde(archive, [Fernet.generate_key()])
    assert problemes  # autre clé : archive illisible
