"""Sauvegardes chiffrées, restauration, rotation."""

from __future__ import annotations

import os
import sqlite3
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from aides_plateforme import SYSTEME
from cryptography.fernet import Fernet

from controldone.storage import Database, ErreurIntegrite, FileVault
from controldone.storage.models import Fichier, Lot
from controldone.storage.sauvegarde import restaurer, rotation, sauvegarder


def test_sauvegarde_et_restauration(monde, tmp_path, cles):
    with monde.db.tenant("cli_a", SYSTEME) as sc:  # écriture en cours de journée (base ouverte)
        sc.creer_lot("lot_sauvegarde")
    archive = sauvegarder(monde.db.chemin_sqlite(), monde.vault.racine, tmp_path / "sauv", cles,
                          now=datetime(2026, 9, 30, 2, 0, tzinfo=UTC))
    assert archive.name == "controldone-20260930T020000Z.tar.gz.enc"
    assert stat.S_IMODE(os.stat(archive).st_mode) == 0o600
    assert b"SQLite format" not in archive.read_bytes() and b"lot_sauvegarde" not in archive.read_bytes()
    cible = restaurer(archive, tmp_path / "restauree", cles)
    db2 = Database(f"sqlite:///{cible}/base/controldone.db")
    try:
        with db2.tenant("cli_a", SYSTEME) as sc:
            assert sc.obtenir(Lot, "lot_sauvegarde")
            ref = sc.obtenir(Fichier, "fic_a").coffre_ref
    finally:
        db2.fermer()
    assert FileVault(cible / "coffre", cles).lire("cli_a", ref) == b"PDF FICTIF cli_a"


def test_restauration_mauvaise_cle(monde, tmp_path, cles):
    archive = sauvegarder(monde.db.chemin_sqlite(), None, tmp_path / "s", cles)
    with pytest.raises(ErreurIntegrite):
        restaurer(archive, tmp_path / "r", [Fernet.generate_key()])


def test_restauration_refuse_une_archive_piegee(tmp_path, cles):
    import io
    import tarfile

    from controldone.storage.sauvegarde import _fernet

    tampon = io.BytesIO()
    with tarfile.open(fileobj=tampon, mode="w:gz") as tar:
        info = tarfile.TarInfo("../../evasion.txt")
        info.size = 3
        tar.addfile(info, io.BytesIO(b"abc"))
    piege = tmp_path / "controldone-20260101T000000Z.tar.gz.enc"
    piege.write_bytes(_fernet(cles).encrypt(tampon.getvalue()))
    with pytest.raises(ErreurIntegrite):
        restaurer(piege, tmp_path / "r", cles)
    assert not (tmp_path / "evasion.txt").exists()


def test_rotation_7_jours_4_semaines(tmp_path):
    debut = datetime(2026, 10, 2, 3, 0, tzinfo=UTC)
    for i in range(60):  # deux sauvegardes par jour pendant 30 jours
        d = debut - timedelta(hours=12 * i)
        (tmp_path / f"controldone-{d.strftime('%Y%m%dT%H%M%SZ')}.tar.gz.enc").write_bytes(b"x")
    (tmp_path / "autre_fichier.txt").write_text("conservé")
    supprimes = rotation(tmp_path)
    restants = sorted(p.name for p in tmp_path.glob("controldone-*"))
    jours = {n[12:20] for n in restants}
    assert len(restants) <= 11 and len(supprimes) == 60 - len(restants)
    assert {(debut - timedelta(days=i)).strftime("%Y%m%d") for i in range(7)} <= jours
    semaines = {datetime.strptime(n[12:20], "%Y%m%d").isocalendar()[:2] for n in restants}
    assert len(semaines) >= 4
    assert (tmp_path / "autre_fichier.txt").exists()
    assert rotation(tmp_path) == []  # stable


def test_base_sqlite_restauree_coherente(monde, tmp_path, cles):
    archive = sauvegarder(monde.db.chemin_sqlite(), None, tmp_path / "s", cles)
    cible = restaurer(archive, tmp_path / "r", cles)
    con = sqlite3.connect(str(cible / "base" / "controldone.db"))
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    con.close()


def test_script_backup_present_et_executable():
    script = Path(__file__).resolve().parents[2] / "scripts" / "backup.sh"
    assert script.exists() and os.access(script, os.X_OK)
    assert "controldone.storage.sauvegarde" in script.read_text()
