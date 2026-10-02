"""Persistance de la file de tâches (D-004). La logique (worker, handlers) est dans ``controldone.jobs``.

- ``enqueue`` : clé d'idempotence unique -> jamais de doublon (renvoie le job existant) ;
- ``reserver`` : prise atomique d'un job prêt (``pending`` et ``run_after`` échu, ou ``running`` dont le bail
  a expiré : le worker précédent est mort) ; ``attempts`` est incrémenté à la prise ; un job dont le bail a
  expiré après le dernier essai passe ``dead`` ;
- ``prolonger`` (battement de cœur), ``terminer``, ``echouer`` (attente exponentielle : 30 s × 2^(n-1),
  plafonnée à 1 h ; ``dead`` après ``max_attempts`` essais, avec une alerte au fondateur).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from controldone.ids import Prefixe, nouvel_id
from controldone.storage.alertes import emettre_alerte
from controldone.storage.audit import journaliser
from controldone.storage.coltypes import maintenant
from controldone.storage.db import Database
from controldone.storage.models import Job

__all__ = ["BACKOFF_BASE_S", "BACKOFF_MAX_S", "MAX_ATTEMPTS", "JobInfo", "JobStore", "delai_backoff"]

BACKOFF_BASE_S = 30
BACKOFF_MAX_S = 3600
MAX_ATTEMPTS = 5


def delai_backoff(attempts: int) -> timedelta:
    """Attente avant l'essai suivant, après ``attempts`` essais échoués (1 -> 30 s, 2 -> 60 s …, ≤ 1 h)."""
    n = max(1, attempts)
    return timedelta(seconds=min(BACKOFF_BASE_S * 2 ** (n - 1), BACKOFF_MAX_S))


@dataclass(frozen=True)
class JobInfo:
    id: str
    kind: str
    payload: dict[str, Any]
    idempotency_key: str
    tenant_id: str | None
    statut: str
    attempts: int
    max_attempts: int
    run_after: datetime
    locked_until: datetime | None
    locked_by: str | None
    last_error: str | None
    resultat: dict[str, Any] | None


def _info(j: Job) -> JobInfo:
    return JobInfo(j.id, j.kind, dict(j.payload or {}), j.idempotency_key, j.tenant_id, j.statut, j.attempts,
                   j.max_attempts, j.run_after, j.locked_until, j.locked_by, j.last_error, j.resultat)


class JobStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def enqueue(self, kind: str, payload: dict[str, Any], idempotency_key: str, tenant_id: str | None = None,
                *, max_attempts: int = MAX_ATTEMPTS, run_after: datetime | None = None,
                now: datetime | None = None) -> tuple[JobInfo, bool]:
        """Renvoie ``(job, cree)`` ; ``cree = False`` si la clé existait déjà."""
        if not idempotency_key:
            raise ValueError("clé d'idempotence obligatoire")
        now = now or maintenant()
        with self.db.transaction_systeme() as s:
            existant = s.execute(select(Job).where(Job.idempotency_key == idempotency_key)).scalar_one_or_none()
            if existant is not None:
                return _info(existant), False
            job = Job(id=nouvel_id(Prefixe.job), kind=kind, payload=payload, idempotency_key=idempotency_key,
                      tenant_id=tenant_id, max_attempts=max_attempts, run_after=run_after or now, cree_le=now)
            try:
                with s.begin_nested():
                    s.add(job)
            except IntegrityError:  # course avec un autre producteur : la clé existe désormais
                existant = s.execute(select(Job).where(Job.idempotency_key == idempotency_key)).scalar_one()
                return _info(existant), False
            return _info(job), True

    def reserver(self, worker_id: str, *, lease_s: int = 60, now: datetime | None = None,
                 kinds: list[str] | None = None) -> JobInfo | None:
        now = now or maintenant()
        pret = or_(
            and_(Job.statut == "pending", Job.run_after <= now),
            and_(Job.statut == "running", Job.locked_until < now),
        )
        for _ in range(10):
            with self.db.transaction_systeme() as s:
                q = select(Job).where(pret)
                if kinds:
                    q = q.where(Job.kind.in_(kinds))
                job = s.execute(
                    q.order_by(Job.run_after, Job.cree_le).limit(1).with_for_update(skip_locked=True)
                ).scalar_one_or_none()
                if job is None:
                    return None
                if job.statut == "running" and job.attempts >= job.max_attempts:
                    self._mort(s, job, "bail_expire", now)
                    continue
                res = s.execute(
                    update(Job).where(Job.id == job.id, pret).values(
                        statut="running", attempts=Job.attempts + 1, locked_by=worker_id,
                        locked_until=now + timedelta(seconds=lease_s), heartbeat_at=now,
                    ).execution_options(synchronize_session=False)
                )
                if res.rowcount != 1:
                    continue
                s.flush()
                s.expire(job)
                return _info(s.get(Job, job.id))  # type: ignore[arg-type]
        return None

    def prolonger(self, job_id: str, worker_id: str, *, lease_s: int = 60, now: datetime | None = None) -> bool:
        """Battement de cœur : prolonge le bail si ce worker le détient encore."""
        now = now or maintenant()
        with self.db.transaction_systeme() as s:
            res = s.execute(
                update(Job).where(Job.id == job_id, Job.locked_by == worker_id, Job.statut == "running")
                .values(locked_until=now + timedelta(seconds=lease_s), heartbeat_at=now)
                .execution_options(synchronize_session=False)
            )
            return res.rowcount == 1

    def terminer(self, job_id: str, worker_id: str, resultat: dict[str, Any] | None = None,
                 *, now: datetime | None = None) -> bool:
        now = now or maintenant()
        with self.db.transaction_systeme() as s:
            res = s.execute(
                update(Job).where(Job.id == job_id, Job.locked_by == worker_id, Job.statut == "running")
                .values(statut="done", resultat=resultat, termine_le=now, locked_until=None, last_error=None)
                .execution_options(synchronize_session=False)
            )
            return res.rowcount == 1

    def echouer(self, job_id: str, worker_id: str, erreur: str, *, definitif: bool = False,
                now: datetime | None = None) -> str | None:
        """Enregistre un échec ; renvoie le nouveau statut (``pending`` ou ``dead``), ``None`` si le bail
        a été perdu entre-temps."""
        now = now or maintenant()
        with self.db.transaction_systeme() as s:
            job = s.execute(
                select(Job).where(Job.id == job_id, Job.locked_by == worker_id, Job.statut == "running")
            ).scalar_one_or_none()
            if job is None:
                return None
            job.last_error = erreur[:300]
            if definitif or job.attempts >= job.max_attempts:
                self._mort(s, job, erreur, now)
                return "dead"
            job.statut = "pending"
            job.locked_by = None
            job.locked_until = None
            job.run_after = now + delai_backoff(job.attempts)
            return "pending"

    @staticmethod
    def _mort(s: Any, job: Job, erreur: str, now: datetime) -> None:
        job.statut, job.locked_by, job.locked_until, job.termine_le = "dead", None, None, now
        job.last_error = erreur[:300]
        emettre_alerte(s, cle=f"job_mort:{job.id}", kind="job_mort", tenant_id=job.tenant_id,
                       message=f"Job {job.kind} {job.id} mort après {job.attempts} essai(s) : {erreur[:100]}",
                       details={"job_id": job.id, "kind": job.kind, "attempts": job.attempts})
        journaliser(s, actor="systeme:worker", role="systeme", action="job_mort", tenant_id=job.tenant_id,
                    target=f"jobs:{job.id}", details={"kind": job.kind, "erreur": erreur[:100]})

    def obtenir(self, job_id: str) -> JobInfo | None:
        with self.db.transaction_systeme() as s:
            j = s.get(Job, job_id)
            return _info(j) if j else None

    def lister(self, *, statut: str | None = None, tenant_id: str | None = None, limite: int = 200) -> list[JobInfo]:
        with self.db.transaction_systeme() as s:
            q = select(Job).order_by(Job.cree_le).limit(limite)
            if statut:
                q = q.where(Job.statut == statut)
            if tenant_id:
                q = q.where(Job.tenant_id == tenant_id)
            return [_info(j) for j in s.execute(q).scalars()]

    def compter_par_statut(self) -> dict[str, int]:
        with self.db.transaction_systeme() as s:
            return {st: n for st, n in s.execute(select(Job.statut, func.count()).group_by(Job.statut))}

    def relancer(self, job_id: str, *, acteur_id: str, now: datetime | None = None) -> bool:
        """Remet un job ``dead`` en file (décision du fondateur ; essais remis à zéro)."""
        now = now or maintenant()
        with self.db.transaction_systeme() as s:
            j = s.get(Job, job_id)
            if j is None or j.statut != "dead":
                return False
            j.statut, j.attempts, j.run_after, j.termine_le = "pending", 0, now, None
            journaliser(s, actor=acteur_id, role="fondateur", action="relancer_job", tenant_id=j.tenant_id,
                        target=f"jobs:{job_id}")
            return True

    def supprimer_client(self, s: Any, tenant_id: str) -> int:
        """Effacement RGPD : supprime les jobs du client (dans la transaction ``s``)."""
        jobs = list(s.execute(select(Job).where(Job.tenant_id == tenant_id)).scalars())
        for j in jobs:
            s.delete(j)
        return len(jobs)
