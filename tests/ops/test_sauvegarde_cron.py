"""deploy/backup-cron.sh : codes de retour, sonde externe, contrôles hors site (rclone, docker et curl simulés :
aucun réseau) ; exercice de restauration de bout en bout (lent)."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"


def _executable(chemin: Path, contenu: str) -> Path:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text("#!/usr/bin/env bash\n" + contenu, encoding="utf-8")
    chemin.chmod(0o700)
    return chemin


@pytest.fixture
def banc(tmp_path):
    """Copie de backup-cron.sh, faux scripts/backup.sh, faux curl/rclone/docker dans le PATH."""
    script = tmp_path / "deploy" / "backup-cron.sh"
    script.parent.mkdir()
    shutil.copy(DEPLOY / "backup-cron.sh", script)
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    journal = tmp_path / "appels.txt"
    bin_ = tmp_path / "bin"
    for nom in ("curl", "rclone", "docker"):
        _executable(bin_ / nom, f'echo "{nom} $*" >> {journal}\nexit "${{FAUX_{nom.upper()}_CODE:-0}}"\n')
    env = {k: v for k, v in os.environ.items() if not k.startswith("BACKUP_")}
    env.update({"PATH": f"{bin_}:{env['PATH']}", "BACKUP_VERIFICATION_PROFONDE_JOUR": "0"})
    return script, journal, env, tmp_path


def _appels(journal: Path) -> list[str]:
    return journal.read_text().splitlines() if journal.exists() else []


def test_echec_de_sauvegarde_propage_le_code_et_previent_la_sonde(banc):
    script, journal, env, tmp = banc
    _executable(tmp / "scripts" / "backup.sh", 'echo "backup $*" >> ' + str(journal) + "\nexit 3\n")
    env.update({"BACKUP_DIR": str(tmp / "s"), "BACKUP_PING_URL": "https://sonde.exemple.test/ping/abc"})
    p = subprocess.run([str(script)], env=env, capture_output=True, text=True)
    assert p.returncode == 3
    assert "curl -fsS -m 10 --retry 3 -o /dev/null https://sonde.exemple.test/ping/abc/3" in _appels(journal)


def test_succes_previent_la_sonde_et_verification_profonde_le_jour_venu(banc):
    script, journal, env, tmp = banc
    _executable(tmp / "scripts" / "backup.sh", 'echo "backup $*" >> ' + str(journal) + "\n")
    env.update({"BACKUP_DIR": str(tmp / "s"), "BACKUP_PING_URL": "https://sonde.exemple.test/p",
                "BACKUP_VERIFICATION_PROFONDE_JOUR": "tous"})
    subprocess.run([str(script)], env=env, check=True, capture_output=True)
    appels = _appels(journal)
    assert f"backup --destination {tmp / 's'} --verification-profonde" in appels
    assert appels[-1].endswith("https://sonde.exemple.test/p/0")


def test_sans_sonde_aucun_appel_reseau(banc):
    script, journal, env, tmp = banc
    _executable(tmp / "scripts" / "backup.sh", "exit 0\n")
    env["BACKUP_DIR"] = str(tmp / "s")
    subprocess.run([str(script)], env=env, check=True, capture_output=True)
    assert not [a for a in _appels(journal) if a.startswith("curl")]


def _archive_locale(dossier: Path, *, age_s: int = 0, empreinte_juste: bool = True) -> Path:
    dossier.mkdir(parents=True, exist_ok=True)
    a = dossier / f"controldone-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.tar.gz.enc"
    a.write_bytes(b"CDSAV2\nfictif")
    h = hashlib.sha256(a.read_bytes()).hexdigest() if empreinte_juste else "0" * 64
    (dossier / (a.name + ".sha256")).write_text(f"{h}  {a.name}\n")
    if age_s:
        t = a.stat().st_mtime - age_s
        os.utime(a, (t, t))
    return a


def test_hors_site_copie_puis_controle(banc):
    script, journal, env, tmp = banc
    _archive_locale(tmp / "backups")
    env.update({"BACKUP_HOST_DIR": str(tmp / "backups"), "BACKUP_RCLONE_REMOTE": "objeu:sauv"})
    p = subprocess.run([str(script), "--hors-site"], env=env, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    appels = _appels(journal)
    assert appels[0].startswith(f"rclone copy {tmp / 'backups'} objeu:sauv --include controldone-*.tar.gz.enc "
                                "--include controldone-*.tar.gz.enc.sha256 --immutable --checksum")
    assert appels[1].startswith(f"rclone check {tmp / 'backups'} objeu:sauv") and "--one-way" in appels[1]


@pytest.mark.parametrize(("cas", "code", "kind"), [
    ("ancienne", 4, "sauvegarde_absente"),
    ("empreinte", 3, "sauvegarde_verification_echec"),
    ("copie", 5, "sauvegarde_hors_site_echec"),
    ("aucune", 4, "sauvegarde_absente"),
])
def test_hors_site_echecs_codes_et_alerte_applicative(banc, cas, code, kind):
    script, journal, env, tmp = banc
    if cas != "aucune":
        _archive_locale(tmp / "backups", age_s=30 * 3600 if cas == "ancienne" else 0,
                        empreinte_juste=cas != "empreinte")
    env.update({"BACKUP_HOST_DIR": str(tmp / "backups"), "BACKUP_RCLONE_REMOTE": "objeu:sauv",
                "BACKUP_ALERTE_COMPOSE": "/srv/app/deploy/docker-compose.yml", "BACKUP_PING_URL": "https://s.test/x"})
    if cas == "copie":
        env["FAUX_RCLONE_CODE"] = "1"
    p = subprocess.run([str(script), "--hors-site"], env=env, capture_output=True, text=True)
    assert p.returncode == code, p.stderr
    appels = _appels(journal)
    alerte = [a for a in appels if a.startswith("docker compose")]
    assert len(alerte) == 1 and f"alerter --kind {kind} --message" in alerte[0]
    assert appels[-1].endswith(f"https://s.test/x/{code}")


def test_hors_site_sans_distant_refuse(banc):
    script, _, env, _ = banc
    assert subprocess.run([str(script), "--hors-site"], env=env, capture_output=True).returncode == 2


@pytest.mark.lent
def test_exercice_de_restauration_de_bout_en_bout(tmp_path):
    """make restauration-test : init-demo, sauvegarde, effacement, restauration ailleurs, web sur les données
    restaurées (une dizaine de secondes)."""
    from controldone.services.exercice_restauration import executer_exercice

    res = executer_exercice(tmp_path / "exercice")
    assert res.ok, "\n".join(res.lignes())
    assert not (tmp_path / "exercice" / "source").exists()  # la source a bien été effacée
    assert [n for n, _, _ in res.etapes][-1] == "parcours web (connexion, rapport)"


def test_exercice_refuse_var_demo_web(tmp_path):
    from controldone.config import RACINE_DEPOT
    from controldone.services.exercice_restauration import executer_exercice, main

    res = executer_exercice(RACINE_DEPOT / "var" / "demo_web")
    assert not res.ok and "interdit" in (res.echec or "")
    occupe = tmp_path / "occupe"
    occupe.mkdir()
    (occupe / "garder").write_text("x")
    assert main(["--repertoire", str(occupe)]) == 2
    assert (occupe / "garder").exists()
