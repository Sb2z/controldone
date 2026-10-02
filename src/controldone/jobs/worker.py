"""Worker de la file de tâches : ``python -m controldone.jobs.worker``.

Bail (``locked_until``) prolongé par un battement de cœur dans un fil séparé ; attente exponentielle en cas
d'échec (30 s × 2^(n-1), plafond 1 h) ; ``dead`` après 5 essais (alerte au fondateur) ; arrêt propre sur
SIGTERM/SIGINT : le job en cours se termine, aucun nouveau job n'est pris. Si le processus est tué, le
bail expire et un autre worker reprend le job (les handlers sont idempotents).
"""

from __future__ import annotations

import argparse
import importlib
import logging
import os
import signal
import socket
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any

from controldone.jobs.journal import configurer_journaux, evenement
from controldone.jobs.metriques import METRIQUES
from controldone.jobs.registre import HANDLERS, ErreurDefinitive, Handler, JobContext
from controldone.storage.coltypes import maintenant
from controldone.storage.db import Database
from controldone.storage.file_jobs import JobInfo, JobStore

__all__ = ["ErreurTemporaire", "Worker", "main"]

log = logging.getLogger("controldone.jobs.worker")


class ErreurTemporaire(Exception):
    """Échec réessayable dont le message (court, sans contenu de document) peut être journalisé."""


def _code_erreur(exc: BaseException) -> str:
    """Nom de la classe seulement, sauf pour nos exceptions dont le message est maîtrisé."""
    nom = type(exc).__name__
    if isinstance(exc, ErreurDefinitive | ErreurTemporaire) and str(exc):
        return f"{nom}: {str(exc)[:120]}"
    return nom


class Worker:
    def __init__(
        self,
        db: Database,
        *,
        worker_id: str | None = None,
        lease_s: int = 60,
        poll_s: float = 1.0,
        heartbeat_s: float | None = None,
        handlers: Mapping[str, Handler] | None = None,
        services: dict[str, Any] | None = None,
        kinds: Sequence[str] | None = None,
        horloge: Callable[[], datetime] = maintenant,
    ) -> None:
        self.db = db
        self.store = JobStore(db)
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
        self.lease_s = lease_s
        self.poll_s = poll_s
        self.heartbeat_s = heartbeat_s if heartbeat_s is not None else max(1.0, lease_s / 3)
        self.handlers = handlers if handlers is not None else HANDLERS
        self.services = services or {}
        self.kinds = list(kinds) if kinds else None
        self.horloge = horloge
        self._stop = threading.Event()

    # --- arrêt ---
    def arreter(self, *_: Any) -> None:
        self._stop.set()

    @property
    def arrete(self) -> bool:
        return self._stop.is_set()

    def installer_signaux(self) -> None:
        signal.signal(signal.SIGTERM, self.arreter)
        signal.signal(signal.SIGINT, self.arreter)

    # --- exécution ---
    def executer_un(self) -> str | None:
        """Prend et exécute un job ; renvoie son statut final (``done``, ``pending``, ``dead``) ou ``None``."""
        job = self.store.reserver(self.worker_id, lease_s=self.lease_s, now=self.horloge(), kinds=self.kinds)
        if job is None:
            return None
        return self._executer(job)

    def _executer(self, job: JobInfo) -> str:
        champs = {"job_id": job.id, "kind": job.kind, "tenant_id": job.tenant_id, "attempt": job.attempts,
                  "worker_id": self.worker_id}
        evenement(log, "job_debut", **champs)
        fn = self.handlers.get(job.kind)
        if fn is None:
            statut = self.store.echouer(job.id, self.worker_id, "handler_inconnu", definitif=True,
                                        now=self.horloge()) or "perdu"
            METRIQUES.incrementer("jobs_mort", job.kind)
            evenement(log, "job_mort", logging.ERROR, erreur="handler_inconnu", **champs)
            return statut

        fini = threading.Event()
        perdu = threading.Event()

        def battre() -> bool:
            ok = self.store.prolonger(job.id, self.worker_id, lease_s=self.lease_s, now=self.horloge())
            if not ok:
                perdu.set()
            return ok

        def coeur() -> None:
            while not fini.wait(self.heartbeat_s):
                if not battre():
                    evenement(log, "bail_perdu", logging.WARNING, **champs)
                    return

        fil = threading.Thread(target=coeur, name=f"heartbeat-{job.id}", daemon=True)
        fil.start()
        debut = time.perf_counter()
        ctx = JobContext(job=job, db=self.db, heartbeat=battre, services=self.services)
        try:
            resultat = fn(ctx)
        except ErreurDefinitive as exc:
            statut = self.store.echouer(job.id, self.worker_id, _code_erreur(exc), definitif=True,
                                        now=self.horloge()) or "perdu"
            erreur = _code_erreur(exc)
        except Exception as exc:
            statut = self.store.echouer(job.id, self.worker_id, _code_erreur(exc), now=self.horloge()) or "perdu"
            erreur = _code_erreur(exc)
        else:
            erreur = None
            if perdu.is_set():
                statut = "perdu"
            else:
                ok = self.store.terminer(job.id, self.worker_id, resultat if isinstance(resultat, dict) else None,
                                         now=self.horloge())
                statut = "done" if ok else "perdu"
        finally:
            fini.set()
            fil.join(timeout=5)
        duree = time.perf_counter() - debut
        METRIQUES.duree(job.kind, duree)
        nom = {"done": "jobs_ok", "pending": "jobs_echec", "dead": "jobs_mort"}.get(statut, "jobs_bail_perdu")
        METRIQUES.incrementer(nom, job.kind)
        niveau = logging.INFO if statut == "done" else logging.ERROR if statut == "dead" else logging.WARNING
        evenement(log, "job_fin", niveau, statut=statut, duree_ms=round(duree * 1000), erreur=erreur, **champs)
        return statut

    def boucle(self, *, max_jobs: int | None = None) -> int:
        """Boucle principale ; renvoie le nombre de jobs traités."""
        n = 0
        evenement(log, "worker_demarre", worker_id=self.worker_id)
        while not self._stop.is_set():
            statut = self.executer_un()
            if statut is None:
                self._stop.wait(self.poll_s)
                continue
            n += 1
            if max_jobs is not None and n >= max_jobs:
                break
        evenement(log, "worker_arrete", worker_id=self.worker_id, nombre=n)
        return n


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m controldone.jobs.worker")
    parser.add_argument("--once", action="store_true", help="traiter les jobs prêts puis s'arrêter")
    parser.add_argument("--worker-id", default=None)
    parser.add_argument("--lease", type=int, default=int(os.environ.get("CONTROLDONE_JOB_LEASE_S", "120")))
    parser.add_argument("--poll", type=float, default=float(os.environ.get("CONTROLDONE_JOB_POLL_S", "2")))
    parser.add_argument("--kinds", default=None, help="liste de kinds séparés par des virgules")
    parser.add_argument("--init-schema", action="store_true", help="créer les tables manquantes (dev)")
    args = parser.parse_args(argv)
    configurer_journaux(os.environ.get("CONTROLDONE_LOG_LEVEL", "INFO"))

    import controldone.jobs.handlers  # noqa: F401  (enregistre les handlers intégrés)

    # Handlers de l'exploitation (agents, litiges, connecteurs), s'ils sont installés.
    for module in ("controldone.agents.jobs", "controldone.litiges.jobs", "controldone.connecteurs.jobs",
                   "controldone.referentiel.jobs"):
        try:
            importlib.import_module(module)
        except ImportError:  # pragma: no cover
            log.warning("handlers indisponibles : %s", module)
    from controldone.storage.vault import FileVault

    db = Database()
    if args.init_schema:
        db.creer_schema()
    worker = Worker(db, worker_id=args.worker_id, lease_s=args.lease, poll_s=args.poll,
                    kinds=args.kinds.split(",") if args.kinds else None,
                    services={"vault": FileVault.depuis_env()})
    worker.installer_signaux()
    if args.once:
        while not worker.arrete and worker.executer_un() is not None:
            pass
    else:
        worker.boucle()
    db.fermer()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
