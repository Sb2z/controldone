"""Essai d'endurance : N passages du corpus de développement par la file de jobs (chemin du web), un seul worker.

    python scripts/fuzz/endurance.py --corpus bench/corpus/dev --passages 5 --out var/fuzz/endurance.json

Chaque passage dépose chaque dossier du corpus (``services.depot.deposer``, comme l'interface web, un client
neuf par passage pour que les fichiers ne soient pas des doublons) ; un unique ``Worker`` de longue durée traite
ensuite les jobs ``traiter_lot`` du passage. Après chaque job : mémoire résidente, descripteurs ouverts, fils,
processus enfants, fichiers temporaires, taille de la base et du coffre, entrées du registre des textes. Tout se
passe dans un répertoire de données neuf (rien n'est écrit dans ``var/`` du dépôt hors ``--out``).
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import tempfile
import time
from pathlib import Path


def _rss_mo() -> float:
    with open("/proc/self/statm") as f:
        return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 2**20


def _enfants() -> int:
    n = 0
    for tid in os.listdir("/proc/self/task"):
        try:
            with open(f"/proc/self/task/{tid}/children") as f:
                n += len(f.read().split())
        except OSError:
            pass
    return n


def _taille(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return sum(x.stat().st_size for x in p.rglob("*") if x.is_file()) if p.exists() else 0


def _nb_fichiers(p: Path) -> int:
    return sum(1 for _ in p.rglob("*")) if p.exists() else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="bench/corpus/dev")
    ap.add_argument("--passages", type=int, default=5)
    ap.add_argument("--limite", type=int, default=0, help="nombre de dossiers par passage (0 = tous)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--data-dir", default=None)
    a = ap.parse_args(argv)

    corpus = Path(a.corpus).resolve()
    sortie = Path(a.out).resolve()
    data = Path(a.data_dir or tempfile.mkdtemp(prefix="cdo-endurance-")).resolve()
    data.mkdir(parents=True, exist_ok=True)
    from cryptography.fernet import Fernet

    os.environ.update(
        {
            "CONTROLDONE_ENV": "dev",
            "CONTROLDONE_DATA_DIR": str(data),
            "CONTROLDONE_DATABASE_URL": f"sqlite:///{data}/controldone.db",
            "CONTROLDONE_MASTER_KEY": Fernet.generate_key().decode(),
            "CONTROLDONE_LOG_LEVEL": "WARNING",
        }
    )
    os.environ.pop("CONTROLDONE_PAGES_CACHE_DIR", None)  # chemin de production : pas de cache de pages
    os.environ.pop("ANTHROPIC_API_KEY", None)

    from controldone.auth.roles import Acteur, Role
    from controldone.config import get_settings
    from controldone.ingest import decoupage
    from controldone.jobs.registre import charger_handlers
    from controldone.jobs.worker import Worker
    from controldone.services import depot
    from controldone.services.admin import creer_client, creer_utilisateur_client
    from controldone.services.plateforme import Plateforme
    from controldone.storage.comptes import utilisateur_par_email

    reglages = get_settings()
    tmp = reglages.appliquer_repertoire_temporaire()
    charger_handlers()
    pf = Plateforme.depuis_env()
    pf.db.creer_schema()
    fondateur = Acteur("usr_fondateur_endurance", Role.fondateur)
    worker = Worker(pf.db, worker_id="endurance", lease_s=600, services={"vault": pf.vault})
    dossiers = sorted(p for p in corpus.iterdir() if (p / "docs").is_dir())
    if a.limite:
        dossiers = dossiers[: a.limite]

    mesures: list[dict] = []
    statuts: dict[str, int] = {}
    t0 = time.monotonic()
    n = 0

    def mesurer(**extra) -> dict:
        m = {
            "n": n,
            "t_s": round(time.monotonic() - t0, 1),
            "rss_mo": round(_rss_mo(), 1),
            "fds": len(os.listdir("/proc/self/fd")),
            "fils": len(os.listdir("/proc/self/task")),
            "enfants": _enfants(),
            "tmp_fichiers": _nb_fichiers(tmp),
            "tmp_systeme": len(
                [x for x in os.listdir("/tmp") if x.startswith(("cdo", "cd-", "tmp", "pymp"))]
            ),
            "db_mo": round(
                sum(_taille(Path(str(data / "controldone.db") + s)) for s in ("", "-wal", "-shm")) / 2**20, 2
            ),
            "coffre_mo": round(_taille(data / "coffre") / 2**20, 1),
            "registre_textes": len(decoupage._REGISTRE),
            "objets_gc": len(gc.get_objects()),
            **extra,
        }
        return m

    mesures.append(mesurer(passage=0))
    for passage in range(1, a.passages + 1):
        tid = creer_client(pf, fondateur, f"Client endurance {passage} FICTIF")
        email = f"endurance{passage}@exemple.invalid"
        creer_utilisateur_client(pf, fondateur, tid, email, "client_admin")
        acteur = Acteur(utilisateur_par_email(pf.db, email).id, Role.client_admin, tid)
        for d in dossiers:
            racine = d / "docs"
            fichiers = [
                depot.FichierTransmis(
                    nom=p.relative_to(racine).as_posix(), contenu=p.read_bytes(), taille=p.stat().st_size
                )
                for p in sorted(racine.rglob("*"))
                if p.is_file()
            ]
            depot.deposer(pf, acteur, fichiers)
        while True:
            statut = worker.executer_un()
            if statut is None:
                break
            statuts[statut] = statuts.get(statut, 0) + 1
            n += 1
            if n % 10 == 0 or n <= 3:
                m = mesurer(passage=passage)
                mesures.append(m)
                print(json.dumps(m), flush=True)
    gc.collect()
    mesures.append(mesurer(passage=a.passages, fin=True))
    from controldone.storage.file_jobs import JobStore  # noqa: F401  (diagnostic : jobs restants)

    par_100 = [m for m in mesures if (m["n"] % 100 == 0 and m["n"] > 0) or m.get("fin") or m["n"] == 0]
    bilan = {
        "dossiers_par_passage": len(dossiers),
        "passages": a.passages,
        "jobs": n,
        "statuts": statuts,
        "duree_s": round(time.monotonic() - t0, 1),
        "par_100": par_100,
        "mesures": mesures,
        "data_dir": str(data),
    }
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(json.dumps(bilan, indent=1), "utf-8")
    print(json.dumps({k: v for k, v in bilan.items() if k != "mesures"}, indent=1))
    pf.db.fermer()
    return 0


if __name__ == "__main__":
    sys.exit(main())
