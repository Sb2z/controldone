"""deploy/scheduler.sh : exercice mensuel le premier dimanche du mois, désactivé par défaut (D-4702).

L'heure est simulée par un faux ``date`` (``date -d "$FAUX_DATE"``) ; ``python`` et ``backup-cron.sh`` sont des
faux qui notent leurs appels : aucun exercice réel n'est lancé."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from datetime import date, timedelta
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
VRAI_DATE = shutil.which("date")


def _executable(chemin: Path, contenu: str) -> Path:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text("#!/usr/bin/env bash\n" + contenu, encoding="utf-8")
    chemin.chmod(0o700)
    return chemin


def _premier_dimanche(annee: int, mois: int) -> date:
    j = date(annee, mois, 1)
    return j + timedelta(days=(6 - j.weekday()) % 7)


def _tour(tmp_path: Path, faux_date: str, **reglages: str) -> list[str]:
    """Un tour de boucle du planificateur à l'heure ``faux_date`` ; renvoie les appels notés."""
    d = tmp_path / "deploy"
    d.mkdir(exist_ok=True)
    shutil.copy(DEPLOY / "scheduler.sh", d / "scheduler.sh")
    journal = tmp_path / "appels.txt"
    journal.unlink(missing_ok=True)
    _executable(d / "backup-cron.sh", f'echo "sauvegarde $*" >> {journal}\n')
    faux_py = _executable(tmp_path / "bin" / "python", f'echo "python $*" >> {journal}\n')
    _executable(tmp_path / "bin" / "date", f'exec {VRAI_DATE} -d "$FAUX_DATE" "$@"\n')
    env = {
        **{k: v for k, v in os.environ.items() if not k.startswith(("SCHED_", "CONTROLDONE_", "BACKUP_"))},
        "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}",
        "FAUX_DATE": faux_date,
        "CONTROLDONE_PYTHON": str(faux_py),
        "CONTROLDONE_DATA_DIR": str(tmp_path / "var"),
        "BACKUP_DIR": str(tmp_path / "backups"),
        "SCHED_TICK_S": "30",
        **reglages,
    }
    p = subprocess.Popen(
        ["bash", str(d / "scheduler.sh")],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        fin = time.monotonic() + 20
        while time.monotonic() < fin and "agents.planificateur" not in (
            journal.read_text() if journal.exists() else ""
        ):
            time.sleep(0.1)
        time.sleep(1.5)  # fin du premier tour (tâches simulées : instantanées)
    finally:
        p.terminate()
        p.communicate(timeout=20)
    return journal.read_text().splitlines() if journal.exists() else []


def _exercices(appels: list[str]) -> list[str]:
    return [a for a in appels if "exercice-mensuel" in a]


@pytest.fixture
def dimanche() -> date:
    return _premier_dimanche(2026, 11)


def test_desactive_par_defaut(tmp_path, dimanche):
    assert _exercices(_tour(tmp_path, f"{dimanche} 05:00 UTC")) == []


def test_premier_dimanche_apres_l_heure(tmp_path, dimanche):
    appels = _exercices(_tour(tmp_path, f"{dimanche} 05:00 UTC", SCHED_EXERCICE_MENSUEL="1"))
    assert appels == [
        f"python -m controldone.cli sauvegarde exercice-mensuel --source {tmp_path / 'backups'} "
        f"--rapports {tmp_path / 'var' / 'exercices'}"
    ]


@pytest.mark.parametrize(
    "decalage, heure",
    [(0, "04:00"), (7, "05:00"), (1, "05:00")],
    ids=["avant-l-heure", "deuxieme-dimanche", "lundi"],
)
def test_pas_d_exercice_hors_du_creneau(tmp_path, dimanche, decalage, heure):
    jour = dimanche + timedelta(days=decalage)
    assert _exercices(_tour(tmp_path, f"{jour} {heure} UTC", SCHED_EXERCICE_MENSUEL="1")) == []


def test_pas_deux_fois_dans_le_mois(tmp_path, dimanche):
    rapports = tmp_path / "var" / "exercices"
    rapports.mkdir(parents=True)
    (rapports / f"exercice-mensuel-{dimanche:%Y%m%d}T044500Z.json").write_text("{}")
    assert _exercices(_tour(tmp_path, f"{dimanche} 05:00 UTC", SCHED_EXERCICE_MENSUEL="1")) == []
