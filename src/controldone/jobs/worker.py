"""Worker de la file de tâches : ``python -m controldone.jobs.worker``.

Bail (``locked_until``) prolongé par un battement de cœur dans un fil séparé ; attente exponentielle en cas
d'échec (30 s × 2^(n-1), plafond 1 h) ; ``dead`` après 5 essais (alerte au fondateur) ; arrêt propre sur
SIGTERM/SIGINT : le job en cours se termine, aucun nouveau job n'est pris. Si le processus est tué, le
bail expire et un autre worker reprend le job (les handlers sont idempotents).

Battement de cœur (D-1303) : une erreur de la base (« database is locked »…) est journalisée et le
battement réessaie au tick suivant ; le bail n'est déclaré perdu que si la ligne n'est plus détenue
(``rowcount == 0``) ou si aucun renouvellement n'a réussi pendant ``lease_s - heartbeat_s`` secondes. Le
handler voit alors ``ctx.bail_perdu`` et ``ctx.exiger_bail(session)`` refuse la validation de ses résultats
(jeton ``locked_by`` + ``attempts``) : deux workers ne valident jamais le même job.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import socket
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any

from controldone.jobs.journal import configurer_journaux, evenement
from controldone.jobs.metriques import METRIQUES
from controldone.jobs.registre import (
    HANDLERS,
    BailPerdu,
    ErreurDefinitive,
    Handler,
    JobContext,
    Reporter,
    charger_handlers,
)
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
        verrou = threading.Lock()
        dernier_ok = [time.monotonic()]
        tentative = job.attempts

        def battre() -> bool:
            """Renouvelle le bail ; ``False`` seulement si le bail est perdu. Une erreur de base est
            journalisée puis retentée au battement suivant (jamais propagée au fil ni au handler)."""
            if perdu.is_set():
                return False
            with verrou:
                try:
                    ok = self.store.prolonger(job.id, self.worker_id, lease_s=self.lease_s, now=self.horloge(),
                                              tentative=tentative)
                except Exception as exc:
                    evenement(log, "battement_echec", logging.WARNING, erreur=type(exc).__name__, **champs)
                    if time.monotonic() - dernier_ok[0] >= max(self.heartbeat_s, self.lease_s - self.heartbeat_s):
                        perdu.set()  # le bail a pu expirer : on cesse d'agir pour ce job
                        evenement(log, "bail_perdu", logging.WARNING, motif="renouvellement_impossible", **champs)
                        return False
                    return True
                if ok:
                    dernier_ok[0] = time.monotonic()
                else:
                    perdu.set()
                    evenement(log, "bail_perdu", logging.WARNING, **champs)
                return ok

        def coeur() -> None:
            while not fini.wait(self.heartbeat_s):
                if not battre():
                    return

        fil = threading.Thread(target=coeur, name=f"heartbeat-{job.id}", daemon=True)
        fil.start()
        debut = time.perf_counter()
        ctx = JobContext(job=job, db=self.db, heartbeat=battre, services=self.services, perdu=perdu,
                         worker_id=self.worker_id)
        try:
            resultat = fn(ctx)
        except BailPerdu:
            statut, erreur = "perdu", "bail_perdu"
        except Reporter as exc:  # rien d'anormal : le job repasse en file sans consommer d'essai (D-1321)
            erreur = f"reporte: {str(exc)[:120]}"
            statut = self.store.reporter(job.id, self.worker_id, str(exc), delai_s=exc.delai_s, now=self.horloge(),
                                         tentative=tentative) or "perdu"
            statut = "reporte" if statut == "pending" else statut
        except ErreurDefinitive as exc:
            statut = self.store.echouer(job.id, self.worker_id, _code_erreur(exc), definitif=True,
                                        now=self.horloge(), tentative=tentative) or "perdu"
            erreur = _code_erreur(exc)
        except Exception as exc:
            statut = self.store.echouer(job.id, self.worker_id, _code_erreur(exc), now=self.horloge(),
                                        tentative=tentative) or "perdu"
            erreur = _code_erreur(exc)
        else:
            erreur = None
            if perdu.is_set():
                statut = "perdu"
            else:
                ok = self.store.terminer(job.id, self.worker_id, resultat if isinstance(resultat, dict) else None,
                                         now=self.horloge(), tentative=tentative)
                statut = "done" if ok else "perdu"
        finally:
            fini.set()
            fil.join(timeout=5)
        duree = time.perf_counter() - debut
        METRIQUES.duree(job.kind, duree)
        nom = {"done": "jobs_ok", "pending": "jobs_echec", "dead": "jobs_mort",
               "reporte": "jobs_reportes"}.get(statut, "jobs_bail_perdu")
        METRIQUES.incrementer(nom, job.kind)
        niveau = (logging.INFO if statut in ("done", "reporte") else logging.ERROR if statut == "dead"
                  else logging.WARNING)
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


def _journal_schema(message: str) -> None:
    """Attente d'une migration (D-4102) : événement JSON (sans texte libre) et message lisible sur stderr."""
    evenement(log, "schema_en_attente", logging.WARNING)
    print(f"ControlDOne worker : {message}", file=sys.stderr, flush=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m controldone.jobs.worker")
    parser.add_argument("--once", action="store_true", help="traiter les jobs prêts puis s'arrêter")
    parser.add_argument("--worker-id", default=None)
    from controldone.config import get_settings

    reglages = get_settings()
    parser.add_argument("--lease", type=int, default=reglages.job_lease_s)
    parser.add_argument("--poll", type=float, default=reglages.job_poll_s)
    parser.add_argument("--kinds", default=None, help="liste de kinds séparés par des virgules")
    parser.add_argument("--init-schema", action="store_true", help="créer les tables manquantes (dev)")
    args = parser.parse_args(argv)
    configurer_journaux(reglages.log_level)
    reglages.appliquer_repertoire_temporaire()
    charger_handlers()  # liste unique, partagée avec le worker intégré du web (D-1302)
    from controldone.storage.vault import FileVault

    db = Database()
    if args.init_schema:
        db.creer_schema(migrer=False)  # migrations : exiger_schema_a_jour (D-3503)
    from controldone.storage.db import SchemaPerime

    try:  # D-1322 : jamais d'erreur « no such column » en cours de job ; migration en attente : D-4102
        db.attendre_schema_a_jour(journal=_journal_schema)
    except SchemaPerime as exc:
        evenement(log, "schema_perime", logging.CRITICAL)
        print(f"ControlDOne worker : {exc}", file=sys.stderr, flush=True)  # noms d'étapes ou de colonnes seulement
        db.fermer()
        return 3
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
    # Exécuté comme ``python -m`` : passer par le module importé (sinon ``ErreurTemporaire`` existerait en
    # deux exemplaires, ``__main__`` et ``controldone.jobs.worker``, et ``_code_erreur`` ne la reconnaîtrait pas).
    from controldone.jobs.worker import main as _main

    raise SystemExit(_main())
