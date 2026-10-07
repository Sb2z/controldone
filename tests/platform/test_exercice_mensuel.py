"""Exercice mensuel sur une vraie archive (D-4702) et empreinte publique de la clé maîtresse (D-4703).

L'archive « de production » est celle du monde de test (deux clients fictifs) ; avec un serveur PostgreSQL
jetable (``CONTROLDONE_TEST_PG_URL``), la même chose sur une archive ``pg_dump`` chargée dans une base jetable.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

import pytest
from aides_pg import base_pg, serveur_pg  # noqa: F401  (fixture)
from cryptography.fernet import Fernet

from controldone.config import reset_settings
from controldone.services import exercice_mensuel as em
from controldone.storage import sauvegarde as sv
from controldone.storage.cles import empreinte_cle

_CLE: list[bytes] = []


def _cle() -> bytes:
    return _CLE[-1]


def _archive(monde, tmp_path: Path) -> Path:
    """Archive « de production » du monde de test ; ``_cle()`` : la clé maîtresse de son coffre."""
    _CLE.append(monde.vault.cles_maitresses[0])
    os.environ["CONTROLDONE_MASTER_KEY"] = _cle().decode()  # (remis par la fixture _env à chaque test)
    return sv.sauvegarder(monde.db.chemin_sqlite(), monde.vault.racine, tmp_path / "sv", [_cle()])


def _restes(dossier: Path) -> list[Path]:
    return list(dossier.glob(".cd-exercice-mensuel-*"))


def test_exercice_conforme_copie_detruite_compte_rendu_sans_donnee_client(monde, tmp_path):
    archive = _archive(monde, tmp_path)
    cr = em.executer_exercice_mensuel(archive, cles=[_cle()])
    assert cr.ok, cr.echec
    assert cr.copie_detruite and not _restes(archive.parent)
    noms = [e["nom"] for e in cr.etapes]
    assert noms[0] == "sélection de l'archive" and noms[-1] == "destruction de la copie"
    assert "démarrage de l'application (lecture seule)" in noms and "lecture seule vérifiée" in noms
    assert cr.sha256 == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert cr.empreinte_externe == "conforme" and cr.moteur == "sqlite"
    assert cr.cle_rang == 0 and cr.cle_empreinte == empreinte_cle(_cle())
    assert cr.manifeste["tables"] > 10 and cr.controle["objets_coffre"] > 0

    md, js = em.ecrire_compte_rendu(cr, tmp_path / "exercices")
    assert md.name.startswith("exercice-mensuel-2") and md.suffix == ".md"
    for f in (md, js):
        assert stat.S_IMODE(f.stat().st_mode) == 0o600
    texte = md.read_text(encoding="utf-8") + js.read_text(encoding="utf-8")
    assert json.loads(js.read_text(encoding="utf-8"))["resultat"] == "CONFORME"
    # aucune donnée client : ni identifiant ni nom de client, de transitaire, de compte ; ni la clé
    for interdit in ("cli_a", "cli_b", "FICTIF", "TRANSITAIRE", "@", _cle().decode(), str(tmp_path)):
        assert interdit not in texte, interdit


def test_archive_alteree_echec_et_copie_detruite(monde, tmp_path):
    archive = _archive(monde, tmp_path)
    octets = bytearray(archive.read_bytes())
    octets[len(octets) // 2] ^= 0x01
    archive.write_bytes(bytes(octets))
    cr = em.executer_exercice_mensuel(archive, cles=[_cle()])
    assert not cr.ok and "empreinte" in cr.echec
    assert cr.copie_detruite and not _restes(archive.parent)


def test_mauvaise_cle_refusee(monde, tmp_path):
    archive = _archive(monde, tmp_path)
    cr = em.executer_exercice_mensuel(archive, cles=[Fernet.generate_key()])
    assert not cr.ok and cr.echec.startswith("relecture")
    assert cr.copie_detruite


def test_ancienne_cle_reperee_par_son_rang(monde, tmp_path, monkeypatch):
    archive = _archive(monde, tmp_path)
    monkeypatch.setattr(em, "_rendre_un_rapport", lambda *a: "rendu non testé ici")
    monkeypatch.setattr(em, "_get", lambda url, chemin: 200)
    nouvelle = Fernet.generate_key()
    cr = em.executer_exercice_mensuel(archive, cles=[nouvelle, _cle()])
    assert cr.ok, cr.echec
    assert cr.cle_rang == 1 and cr.cle_empreinte == empreinte_cle(_cle())
    assert any("rang 1" in r for r in cr.remarques)


def test_ecriture_dans_la_copie_detectee(monde, tmp_path, monkeypatch):
    import sqlite3

    archive = _archive(monde, tmp_path)

    def ecrire(base_url: str, coffre: Path, cles) -> str:
        con = sqlite3.connect(base_url.removeprefix("sqlite:///"))
        con.execute("CREATE TABLE intrus (x INTEGER)")
        con.commit()
        con.close()
        return "écrit"

    monkeypatch.setattr(em, "_rendre_un_rapport", ecrire)
    cr = em.executer_exercice_mensuel(archive, cles=[_cle()])
    assert not cr.ok and "modifiée" in cr.echec and "intrus" in cr.echec
    assert cr.copie_detruite


def test_archive_trop_ancienne(monde, tmp_path):
    archive = _archive(monde, tmp_path)
    vieille = archive.with_name("controldone-20200101T000000Z.tar.gz.enc")
    archive.rename(vieille)
    cr = em.executer_exercice_mensuel(vieille, cles=[_cle()], age_max_h=36)
    assert not cr.ok and "vieille de" in cr.echec


def test_ligne_de_commande(monde, tmp_path, monkeypatch, capsys):
    from controldone.cli import main as cli

    archive = _archive(monde, tmp_path)
    monkeypatch.setenv("CONTROLDONE_DATA_DIR", str(tmp_path / "donnees"))
    reset_settings()
    alertes = []
    monkeypatch.setattr(sv, "alerter", lambda kind, message, details=None: alertes.append(kind))
    try:
        assert (
            cli(["sauvegarde", "exercice-mensuel", "--source", str(tmp_path / "vide")])
            == em.ECHEC_CONFIGURATION
        )
        code = cli(
            [
                "sauvegarde",
                "exercice-mensuel",
                "--source",
                str(archive.parent),
                "--rapports",
                str(tmp_path / "cr"),
            ]
        )
        assert code == em.OK, capsys.readouterr().out[-2000:]
        assert len(list((tmp_path / "cr").glob("exercice-mensuel-*.md"))) == 1
        # en échec : compte rendu écrit quand même, alerte au fondateur, code 1
        archive.write_bytes(archive.read_bytes()[:-100])
        archive.with_name(archive.name + ".sha256").unlink()
        assert cli(["sauvegarde", "exercice-mensuel", "--archive", str(archive)]) == em.ECHEC
        assert alertes == ["sauvegarde_verification_echec"]
        assert len(list((tmp_path / "donnees" / "exercices").glob("exercice-mensuel-*.json"))) == 1
        monkeypatch.delenv("CONTROLDONE_MASTER_KEY")
        assert cli(["sauvegarde", "exercice-mensuel", "--archive", str(archive)]) == em.ECHEC_CONFIGURATION
    finally:
        reset_settings()


def test_archive_postgresql_sans_serveur_de_verification(tmp_path, monkeypatch):
    from test_sauvegarde_postgresql import _archive_factice

    def absent(nom):
        raise sv.OutilAbsent(nom)

    monkeypatch.setattr(sv, "_outil", absent)  # faux dump : relecture par pg_restore sautée

    cles = [Fernet.generate_key()]
    archive = _archive_factice(tmp_path, cles, b"PGDMP" + b"\x00" * 64)
    cr = em.executer_exercice_mensuel(archive, cles=cles, pg_serveur=None)
    assert not cr.ok and "BACKUP_PG_VERIFICATION_URL" in cr.echec
    assert cr.copie_detruite and not _restes(archive.parent)


def test_empreinte_publique_de_la_cle_formule_documentee():
    """La procédure de la copie papier (docs/EXPLOITATION.md § 3.5) recalcule cette formule hors application."""
    cle = Fernet.generate_key()
    h = hashlib.sha256(b"controldone:empreinte-cle:" + cle).hexdigest()[:16]
    assert empreinte_cle(cle) == " ".join(h[i : i + 4] for i in range(0, 16, 4))
    assert empreinte_cle(cle.decode() + "\n") == empreinte_cle(cle)
    assert cle.decode()[:8] not in empreinte_cle(cle)


@pytest.mark.postgresql
def test_exercice_sur_une_archive_postgresql(tmp_path, base_pg):  # noqa: F811
    from sqlalchemy import create_engine, text

    from controldone.storage import Database

    db = Database(base_pg)
    try:
        db.creer_schema()
    finally:
        db.fermer()
    cles = [Fernet.generate_key()]
    (tmp_path / "coffre").mkdir()
    archive = sv.sauvegarder_postgresql(base_pg, tmp_path / "coffre", tmp_path / "sv", cles)
    serveur = serveur_pg()
    cr = em.executer_exercice_mensuel(archive, cles=cles, pg_serveur=serveur)
    assert cr.ok, cr.echec
    assert cr.moteur == "postgresql" and cr.copie_detruite
    assert any("aucun rapport publié" in r for r in cr.remarques)
    moteur = create_engine(serveur)
    try:
        with moteur.connect() as c:
            restantes = c.execute(
                text("SELECT datname FROM pg_database WHERE datname LIKE 'cd_mensuel_%'")
            ).all()
    finally:
        moteur.dispose()
    assert restantes == []
