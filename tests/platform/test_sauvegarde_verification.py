"""Sauvegardes : manifeste, vérification, restauration dans un répertoire vide, contrôle approfondi, rotation,
codes de retour et alertes (D-3301 à D-3306)."""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import subprocess
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from aides_plateforme import FONDATEUR
from cryptography.fernet import Fernet

from controldone.config import reset_settings
from controldone.storage import ErreurIntegrite
from controldone.storage import sauvegarde as sv
from controldone.storage.controle_restauration import controler
from controldone.storage.sauvegarde import (
    MANIFESTE,
    instantane_base,
    restaurer,
    rotation,
    sauvegarder,
    verifier,
)

NOW = datetime(2026, 10, 6, 2, 15, tzinfo=UTC)


@pytest.fixture
def sorties(tmp_path):
    d = tmp_path / "outbox_envoyee" / "rapport_publication"
    d.mkdir(parents=True)
    (d / "out_1.json").write_text('{"id": "out_1", "note": "FICTIF"}', encoding="utf-8")
    return d.parent


@pytest.fixture
def archive(monde, tmp_path, cles, sorties):
    return sauvegarder(
        monde.db.chemin_sqlite(), monde.vault.racine, tmp_path / "sauv", cles, now=NOW, sorties=sorties
    )


def _manifeste(archive, cles) -> dict:
    r = verifier(archive, cles)
    assert r.ok, r.problemes
    return r.manifeste


def test_manifeste_couvre_chaque_fichier(monde, archive, cles, sorties):
    m = _manifeste(archive, cles)
    coffre = {
        f"coffre/{p.relative_to(monde.vault.racine).as_posix()}"
        for p in monde.vault.racine.rglob("*")
        if p.is_file()
    }
    assert coffre and coffre <= set(m["fichiers"])
    assert "base/controldone.db" in m["fichiers"]
    assert "outbox_envoyee/rapport_publication/out_1.json" in m["fichiers"]
    for nom in coffre:  # empreinte des octets chiffrés du coffre, tels quels
        chemin = monde.vault.racine / nom.removeprefix("coffre/")
        assert m["fichiers"][nom]["sha256"] == hashlib.sha256(chemin.read_bytes()).hexdigest()
    attendu = instantane_base(monde.db.chemin_sqlite())
    assert m["base"]["tables"] == attendu["tables"] and m["base"]["integrite"] == "ok"
    assert m["base"]["audit"]["entrees"] == attendu["audit"]["entrees"] > 0


def test_empreinte_externe_au_format_sha256sum(archive):
    empreinte = archive.with_name(archive.name + ".sha256")
    assert empreinte.read_text() == f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n"
    subprocess.run(["sha256sum", "-c", "--status", empreinte.name], cwd=archive.parent, check=True)


def test_aucune_cle_dans_l_archive(monde, tmp_path, cles):
    data = monde.vault.racine.parent
    (data / "dev_master.key").write_text(Fernet.generate_key().decode())
    (data / ".env").write_text("CONTROLDONE_MASTER_KEY=secret\n")
    a = sauvegarder(
        monde.db.chemin_sqlite(), monde.vault.racine, tmp_path / "s", cles, sorties=data / "absent"
    )
    noms = set(_manifeste(a, cles)["fichiers"])
    assert not [n for n in noms if n.endswith((".key", ".env"))]
    assert cles[0] not in a.read_bytes()


def test_verifier_refuse_alteration_autre_cle_et_empreinte(archive, tmp_path, cles):
    assert not verifier(archive, [Fernet.generate_key()]).ok
    alteree = tmp_path / archive.name
    octets = bytearray(archive.read_bytes())
    octets[len(octets) // 2] ^= 0x01
    alteree.write_bytes(bytes(octets))
    assert not verifier(alteree, cles).ok
    # copie intacte mais empreinte externe différente (copie hors site corrompue en transit, par exemple)
    archive.with_name(archive.name + ".sha256").write_text("0" * 64 + f"  {archive.name}\n")
    r = verifier(archive, cles)
    assert not r.ok and r.empreinte_externe == "différente"


def _archive_forgee(chemin: Path, cles, membres: dict[str, bytes], *, manifeste: dict | None) -> Path:
    with chemin.open("wb") as sortie:
        ecrivain = sv._EcrivainChiffre(sortie, sv._fernet(cles))
        with tarfile.open(fileobj=ecrivain, mode="w|gz") as tar:
            for nom, contenu in membres.items():
                tar.addfile(sv._entree_tar(nom, taille=len(contenu)), io.BytesIO(contenu))
            if manifeste is not None:
                brut = json.dumps(manifeste).encode()
                tar.addfile(sv._entree_tar(MANIFESTE, taille=len(brut)), io.BytesIO(brut))
        ecrivain.terminer()
    return chemin


def test_verifier_compare_au_manifeste(monde, tmp_path, cles):
    base = monde.db.chemin_sqlite().read_bytes()
    decl = {
        "base/controldone.db": {"taille": len(base), "sha256": hashlib.sha256(base).hexdigest()},
        "coffre/cli_a/fichiers/ab/absent": {"taille": 1, "sha256": "0" * 64},
    }
    a = _archive_forgee(
        tmp_path / "f.tar.gz.enc",
        cles,
        {"base/controldone.db": base, "coffre/cli_a/en_trop": b"x"},
        manifeste={"fichiers": decl, "base": {"integrite": "ok"}},
    )
    problemes = verifier(a, cles).problemes
    assert "fichier absent : coffre/cli_a/fichiers/ab/absent" in problemes
    assert "fichier non déclaré : coffre/cli_a/en_trop" in problemes
    with pytest.raises(ErreurIntegrite, match="manifeste"):
        restaurer(a, tmp_path / "r", cles)


def test_archive_sans_manifeste_reste_restaurable(monde, tmp_path, cles):
    a = _archive_forgee(
        tmp_path / "ancienne.tar.gz.enc",
        cles,
        {"base/controldone.db": monde.db.chemin_sqlite().read_bytes()},
        manifeste=None,
    )
    r = verifier(a, cles)
    assert r.ok and r.manifeste is None
    assert (restaurer(a, tmp_path / "r", cles) / "base" / "controldone.db").is_file()


def test_archive_avec_entree_inattendue_refusee(monde, tmp_path, cles):
    a = _archive_forgee(
        tmp_path / "p.tar.gz.enc", cles, {"base/controldone.db": b"x", "dev_master.key": b"k"}, manifeste=None
    )
    assert not verifier(a, cles).ok
    with pytest.raises(ErreurIntegrite, match="inattendue"):
        restaurer(a, tmp_path / "r", cles)


def test_restauration_dans_un_repertoire_vide_seulement(archive, tmp_path, cles):
    occupe = tmp_path / "occupe"
    occupe.mkdir()
    (occupe / "existant").write_text("ne pas écraser")
    with pytest.raises(FileExistsError):
        restaurer(archive, occupe, cles)
    assert (occupe / "existant").read_text() == "ne pas écraser"
    cible = restaurer(archive, tmp_path / "vide", cles)
    assert sorted(p.name for p in cible.iterdir()) == [MANIFESTE, "base", "coffre", "outbox_envoyee"]


def test_controle_approfondi_conforme_puis_detecte_les_defauts(archive, tmp_path, cles):
    cible = restaurer(archive, tmp_path / "r", cles)
    rapport = controler(cible, cles)
    assert rapport.ok, rapport.problemes
    assert rapport.objets_coffre >= 4 and rapport.references >= 4 and rapport.audit_entrees > 0
    # mauvaise clé : aucun objet du coffre ne se déchiffre
    assert any("coffre" in p for p in controler(cible, [Fernet.generate_key()]).problemes)
    # objet référencé supprimé, objet altéré
    objets = sorted(p for p in (cible / "coffre").rglob("*") if p.is_file())
    objets[0].unlink()
    octets = bytearray(objets[1].read_bytes())
    octets[-1] ^= 0x01
    objets[1].write_bytes(bytes(octets))
    # entrée du journal d'audit modifiée (le déclencheur append-only retiré, comme le ferait un attaquant)
    con = sqlite3.connect(str(cible / "base" / "controldone.db"))
    con.execute("DROP TRIGGER audit_log_sans_update")
    con.execute("UPDATE audit_log SET action = 'falsifiee' WHERE id = (SELECT MIN(id) FROM audit_log)")
    con.commit()
    con.close()
    problemes = controler(cible, cles).problemes
    assert any("référencé absent" in p for p in problemes)
    assert any(p.startswith("coffre ") for p in problemes)
    assert any("contenu modifié" in p for p in problemes)


def test_rotation_supprime_empreintes_et_restes(tmp_path):
    debut = datetime(2026, 10, 6, 2, 15, tzinfo=UTC)
    for i in range(20):
        nom = f"controldone-{(debut - timedelta(days=i)).strftime('%Y%m%dT%H%M%SZ')}.tar.gz.enc"
        (tmp_path / nom).write_bytes(b"x")
        (tmp_path / (nom + ".sha256")).write_text("x")
    vieux = tmp_path / "controldone-20260101T000000Z.tar.gz.enc.partiel"
    vieux.write_bytes(b"x")
    reste = tmp_path / ".cd-verification-abc"
    reste.mkdir()
    recent = tmp_path / "controldone-20261006T030000Z.tar.gz.enc.partiel"
    recent.write_bytes(b"x")
    import os

    ancien = debut.timestamp() - 3 * 86400
    os.utime(vieux, (ancien, ancien))
    os.utime(reste, (ancien, ancien))
    supprimes = rotation(tmp_path, maintenant=debut.timestamp())
    assert supprimes
    for p in supprimes:
        assert not p.with_name(p.name + ".sha256").exists()
    archives = list(tmp_path.glob("controldone-*.tar.gz.enc"))
    assert len(list(tmp_path.glob("*.sha256"))) == len(archives)
    assert not vieux.exists() and not reste.exists() and recent.exists()


# --- ligne de commande : codes de retour et alertes ---------------------------------------------------------


@pytest.fixture
def cli_env(monde, monkeypatch, cles):
    data = monde.vault.racine.parent
    monkeypatch.setenv("CONTROLDONE_DATABASE_URL", f"sqlite:///{monde.db.chemin_sqlite()}")
    monkeypatch.setenv("CONTROLDONE_DATA_DIR", str(data))
    monkeypatch.setenv("CONTROLDONE_MASTER_KEY", cles[0].decode())
    reset_settings()
    yield data
    reset_settings()


def _alertes(monde) -> list[str]:
    with monde.db.operateur(FONDATEUR) as op:
        return [a.kind for a in op.alertes()]


def test_cli_sauvegarder_verifie_et_controle(monde, cli_env, tmp_path, capsys):
    dest = tmp_path / "dest"
    assert sv.main(["sauvegarder", "--destination", str(dest), "--verification-profonde"]) == sv.OK
    sortie = capsys.readouterr().out
    assert "CONFORME" in sortie and "restauration d'essai conforme" in sortie
    assert len(list(dest.glob("controldone-*.tar.gz.enc"))) == 1
    assert sv.main(["verifier", "--dernier", "--destination", str(dest), "--profond"]) == sv.OK
    assert not list(dest.glob(".cd-verification-*"))  # répertoire d'essai effacé


def test_cli_archive_illisible_mise_a_l_ecart_et_alerte(monde, cli_env, tmp_path, monkeypatch):
    dest = tmp_path / "dest"
    monkeypatch.setattr(sv, "verifier", lambda a, c: sv.RapportVerification(archive=a, problemes=["simulé"]))
    assert sv.main(["sauvegarder", "--destination", str(dest)]) == sv.ECHEC_VERIFICATION
    assert not list(dest.glob("controldone-*.tar.gz.enc"))  # ne compte pas comme « sauvegarde du jour »
    assert list(dest.glob("controldone-*.tar.gz.enc.invalide"))
    assert "sauvegarde_verification_echec" in _alertes(monde)


def test_cli_sauvegarde_trop_ancienne(monde, cli_env, tmp_path, cles):
    dest = tmp_path / "dest"
    sauvegarder(
        monde.db.chemin_sqlite(), monde.vault.racine, dest, cles, now=datetime.now(UTC) - timedelta(hours=30)
    )
    assert (
        sv.main(["verifier", "--dernier", "--destination", str(dest), "--age-max-h", "26"])
        == sv.ECHEC_FRAICHEUR
    )
    assert sv.main(["verifier", "--dernier", "--destination", str(tmp_path / "vide")]) == sv.ECHEC_FRAICHEUR
    assert "sauvegarde_absente" in _alertes(monde)


def test_cli_cle_absente_en_production(monde, cli_env, monkeypatch, tmp_path):
    monkeypatch.setenv("CONTROLDONE_ENV", "prod")
    monkeypatch.delenv("CONTROLDONE_MASTER_KEY")
    assert sv.main(["sauvegarder", "--destination", str(tmp_path / "d")]) == sv.ECHEC_CONFIGURATION
    assert "sauvegarde_echec" in _alertes(monde)


def test_cli_restaurer_codes(monde, cli_env, tmp_path, archive, capsys):
    assert sv.main(["restaurer", str(archive), str(tmp_path / "r"), "--controler"]) == sv.OK
    assert "CONFORME" in capsys.readouterr().out
    assert sv.main(["restaurer", str(archive), str(tmp_path / "r")]) == sv.ECHEC_CONFIGURATION  # non vide
    octets = bytearray(archive.read_bytes())
    octets[100] ^= 0x01
    archive.write_bytes(bytes(octets))
    assert sv.main(["restaurer", str(archive), str(tmp_path / "r2")]) == sv.ECHEC_VERIFICATION


def test_cli_alerter(monde, cli_env):
    assert (
        sv.main(["alerter", "--kind", "sauvegarde_hors_site_echec", "--message", "rclone en échec"]) == sv.OK
    )
    assert "sauvegarde_hors_site_echec" in _alertes(monde)


def test_commande_controldone_sauvegarde(monde, cli_env, tmp_path):
    from controldone.cli import main

    assert main(["sauvegarde", "sauvegarder", "--destination", str(tmp_path / "d"), "--sans-rotation"]) == 0
