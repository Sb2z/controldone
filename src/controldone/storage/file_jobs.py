"""Persistance de la file de tâches (D-004). La logique (worker, handlers) est dans ``controldone.jobs``.

- ``enqueue`` : clé d'idempotence unique -> jamais de doublon (renvoie le job existant) ;
- ``reserver`` : prise atomique d'un job prêt (``pending`` et ``run_after`` échu, ou ``running`` dont le bail
  a expiré : le worker précédent est mort) ; ``attempts`` est incrémenté à la prise ; un job dont le bail a
  expiré après le dernier essai passe ``dead`` ;
- ``prolonger`` (battement de cœur), ``terminer``, ``echouer`` (attente exponentielle : 30 s × 2^(n-1),
  plafonnée à 1 h ; ``dead`` après ``max_attempts`` essais, avec une alerte au fondateur).
- **Jeton de clôture** (D-1303) : un bail est détenu par ``(locked_by, attempts)`` ; ``prolonger``,
  ``terminer`` et ``echouer`` acceptent ``tentative`` et ``detient`` vérifie le bail **dans la transaction**
  d'écriture du handler : deux workers de même identifiant ne peuvent pas valider le même job.
- **Ordonnancement équitable** (D-1311) : parmi les jobs prêts, ``reserver`` sert d'abord le client dont
  l'activité la plus récente est la plus ancienne (tourniquet entre clients) ; FIFO au sein d'un client.
- ``purger_termines`` : suppression des jobs ``done`` anciens (30 jours par défaut, D-1309).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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
#: Nombre de jobs prêts examinés pour l'ordonnancement équitable entre clients.
FENETRE_EQUITE = 200


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
    #: Création de la tâche (tri et colonne « Créée » de l'écran Tâches) ; ``run_after`` : prochain essai.
    cree_le: datetime | None = None
    termine_le: datetime | None = None


def _info(j: Job) -> JobInfo:
    return JobInfo(j.id, j.kind, dict(j.payload or {}), j.idempotency_key, j.tenant_id, j.statut, j.attempts,
                   j.max_attempts, j.run_after, j.locked_until, j.locked_by, j.last_error, j.resultat,
                   cree_le=j.cree_le, termine_le=j.termine_le)


class JobStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def enqueue(self, kind: str, payload: dict[str, Any], idempotency_key: str, tenant_id: str | None = None,
                *, max_attempts: int = MAX_ATTEMPTS, run_after: datetime | None = None,
                now: datetime | None = None) -> tuple[JobInfo, bool]:
        """Renvoie ``(job, cree)`` ; ``cree = False`` si la clé existait déjà."""
        if not idempotency_key:
            raise ValueError("clé d'idempotence obligatoire")
        with self.db.transaction_systeme() as s:
            return self.enqueue_dans(s, kind, payload, idempotency_key, tenant_id, max_attempts=max_attempts,
                                     run_after=run_after, now=now)

    @staticmethod
    def enqueue_dans(s: Session, kind: str, payload: dict[str, Any], idempotency_key: str,
                     tenant_id: str | None = None, *, max_attempts: int = MAX_ATTEMPTS,
                     run_after: datetime | None = None, now: datetime | None = None) -> tuple[JobInfo, bool]:
        """Mise en file **dans la transaction de l'appelant** (D-1306) : le job est validé avec les écritures
        qui le motivent (correction, dépôt), ou annulé avec elles. Idempotent (clé unique ; ``IntegrityError``
        d'une course rattrapée par un point de sauvegarde, sûr sous PostgreSQL)."""
        if not idempotency_key:
            raise ValueError("clé d'idempotence obligatoire")
        now = now or maintenant()
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
                candidats = list(s.execute(
                    q.order_by(Job.run_after, Job.cree_le).limit(FENETRE_EQUITE).with_for_update(skip_locked=True)
                ).scalars())
                if not candidats:
                    return None
                job = self._choisir_equitable(s, candidats)
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

    @staticmethod
    def _choisir_equitable(s: Session, candidats: list[Job]) -> Job:
        """Tourniquet entre clients : le client dont la dernière prise de job est la plus ancienne passe
        d'abord ; à égalité (ou au sein d'un client) l'ordre FIFO est conservé."""
        clients = {c.tenant_id for c in candidats}
        if len(clients) <= 1:
            return candidats[0]
        connus = [t for t in clients if t is not None]
        derniere: dict[str | None, datetime] = {}
        if connus:
            derniere.update(s.execute(select(Job.tenant_id, func.max(Job.heartbeat_at))
                                      .where(Job.tenant_id.in_(connus)).group_by(Job.tenant_id)).all())
        derniere[None] = s.execute(select(func.max(Job.heartbeat_at)).where(Job.tenant_id.is_(None))).scalar()
        premier: dict[str | None, int] = {}
        for i, c in enumerate(candidats):
            premier.setdefault(c.tenant_id, i)
        jamais = datetime.min

        def cle(t: str | None) -> tuple[datetime, int]:
            d = derniere.get(t)
            if d is not None and d.tzinfo is not None:
                d = d.replace(tzinfo=None)
            return (d or jamais, premier[t])

        choisi = min(premier, key=cle)
        return candidats[premier[choisi]]

    @staticmethod
    def _detenu(job_id: str, worker_id: str, tentative: int | None) -> Any:
        cond = and_(Job.id == job_id, Job.locked_by == worker_id, Job.statut == "running")
        return and_(cond, Job.attempts == tentative) if tentative is not None else cond

    @staticmethod
    def detient(s: Session, job_id: str, worker_id: str, tentative: int | None = None) -> bool:
        """Jeton de clôture lu **dans la transaction de l'appelant** (verrou de ligne sous PostgreSQL)."""
        q = select(Job.id).where(JobStore._detenu(job_id, worker_id, tentative))
        if s.get_bind().dialect.name != "sqlite":
            q = q.with_for_update()
        return s.execute(q).scalar_one_or_none() is not None

    def prolonger(self, job_id: str, worker_id: str, *, lease_s: int = 60, now: datetime | None = None,
                  tentative: int | None = None) -> bool:
        """Battement de cœur : prolonge le bail si ce worker le détient encore."""
        now = now or maintenant()
        with self.db.transaction_systeme() as s:
            res = s.execute(
                update(Job).where(self._detenu(job_id, worker_id, tentative))
                .values(locked_until=now + timedelta(seconds=lease_s), heartbeat_at=now)
                .execution_options(synchronize_session=False)
            )
            return res.rowcount == 1

    def terminer(self, job_id: str, worker_id: str, resultat: dict[str, Any] | None = None,
                 *, now: datetime | None = None, tentative: int | None = None) -> bool:
        now = now or maintenant()
        with self.db.transaction_systeme() as s:
            res = s.execute(
                update(Job).where(self._detenu(job_id, worker_id, tentative))
                .values(statut="done", resultat=resultat, termine_le=now, locked_until=None, last_error=None)
                .execution_options(synchronize_session=False)
            )
            return res.rowcount == 1

    def echouer(self, job_id: str, worker_id: str, erreur: str, *, definitif: bool = False,
                now: datetime | None = None, tentative: int | None = None) -> str | None:
        """Enregistre un échec ; renvoie le nouveau statut (``pending`` ou ``dead``), ``None`` si le bail
        a été perdu entre-temps."""
        now = now or maintenant()
        with self.db.transaction_systeme() as s:
            job = s.execute(
                select(Job).where(self._detenu(job_id, worker_id, tentative))
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

    def reporter(self, job_id: str, worker_id: str, motif: str, *, delai_s: int = 30, now: datetime | None = None,
                 tentative: int | None = None) -> str | None:
        """Remet en file un job que son handler ne peut pas faire avancer maintenant (``Reporter``) : retour
        à ``pending`` dans ``delai_s`` secondes, l'essai pris à la réservation est rendu (D-1321). ``None`` si
        le bail a été perdu entre-temps."""
        now = now or maintenant()
        with self.db.transaction_systeme() as s:
            job = s.execute(select(Job).where(self._detenu(job_id, worker_id, tentative))).scalar_one_or_none()
            if job is None:
                return None
            job.statut, job.locked_by, job.locked_until = "pending", None, None
            job.attempts = max(0, job.attempts - 1)
            job.run_after = now + timedelta(seconds=max(1, delai_s))
            job.last_error = f"reporte: {motif}"[:300]
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

    def lister(self, *, statut: str | None = None, tenant_id: str | None = None, limite: int = 200,
               recents: bool = False) -> list[JobInfo]:
        """Jobs triés par création croissante ; ``recents=True`` : les ``limite`` **plus récents** (le tri
        est fait en SQL avant la limite, D-1309), renvoyés eux aussi en ordre croissant."""
        with self.db.session(lecture=True) as s:
            s.info["controldone_systeme"] = True
            q = select(Job)
            if statut:
                q = q.where(Job.statut == statut)
            if tenant_id:
                q = q.where(Job.tenant_id == tenant_id)
            if recents:
                lignes = list(s.execute(q.order_by(Job.cree_le.desc(), Job.id.desc()).limit(limite)).scalars())
                return [_info(j) for j in reversed(lignes)]
            return [_info(j) for j in s.execute(q.order_by(Job.cree_le, Job.id).limit(limite)).scalars()]

    def rechercher(self, *, statut: str | None = None, kind: str | None = None, tenant_id: str | None = None,
                   croissant: bool = False, decalage: int = 0, limite: int = 50) -> tuple[list[JobInfo], int]:
        """Page de la liste des tâches filtrée (D-3401) : ``(tâches, total)``, tri par création."""
        conds = []
        if statut:
            conds.append(Job.statut == statut)
        if kind:
            conds.append(Job.kind == kind)
        if tenant_id:
            conds.append(Job.tenant_id == tenant_id)
        with self.db.session(lecture=True) as s:
            s.info["controldone_systeme"] = True
            total = int(s.execute(select(func.count()).select_from(Job).where(*conds)).scalar() or 0)
            ordre = (Job.cree_le.asc(), Job.id.asc()) if croissant else (Job.cree_le.desc(), Job.id.desc())
            q = select(Job).where(*conds).order_by(*ordre).offset(max(0, decalage)).limit(max(1, min(limite, 500)))
            return [_info(j) for j in s.execute(q).scalars()], total

    def valeurs(self) -> tuple[list[str], list[str]]:
        """Types et clients présents dans la file (listes fermées des filtres)."""
        with self.db.session(lecture=True) as s:
            s.info["controldone_systeme"] = True
            kinds = [k for (k,) in s.execute(select(Job.kind).distinct().order_by(Job.kind))]
            clients = [t for (t,) in s.execute(select(Job.tenant_id).where(Job.tenant_id.is_not(None)).distinct()
                                               .order_by(Job.tenant_id))]
            return kinds, clients

    def marquer_etape(self, job_id: str, worker_id: str, etape: str, *, tentative: int | None = None) -> bool:
        """Étape en cours d'un job détenu par ce worker (suivi en direct, D-3402), écrite dans ``resultat``
        (remplacé par le résultat final à ``terminer``). Sans effet si le bail n'est plus détenu."""
        with self.db.transaction_systeme() as s:
            res = s.execute(
                update(Job).where(self._detenu(job_id, worker_id, tentative))
                .values(resultat={"etape": etape[:32]})
                .execution_options(synchronize_session=False)
            )
            return res.rowcount == 1

    def par_cle(self, idempotency_key: str) -> JobInfo | None:
        """Job d'une clé d'idempotence (index unique) : ``traiter_lot:<client>:<lot>``…"""
        with self.db.session(lecture=True) as s:
            s.info["controldone_systeme"] = True
            j = s.execute(select(Job).where(Job.idempotency_key == idempotency_key)).scalar_one_or_none()
            return _info(j) if j else None

    def compter(self, *, statut: str | None = None, avec_erreur: bool = False) -> int:
        with self.db.session(lecture=True) as s:
            s.info["controldone_systeme"] = True
            q = select(func.count()).select_from(Job)
            if statut:
                q = q.where(Job.statut == statut)
            if avec_erreur:
                q = q.where(Job.attempts > 0, Job.last_error.is_not(None))
            return int(s.execute(q).scalar() or 0)

    def purger_termines(self, *, jours: int = 30, now: datetime | None = None) -> int:
        """Supprime les jobs ``done`` terminés depuis plus de ``jours`` jours (les ``dead`` restent, pour
        décision du fondateur). La clé d'idempotence d'un job purgé peut resservir."""
        limite = (now or maintenant()) - timedelta(days=jours)
        with self.db.transaction_systeme() as s:
            res = s.execute(delete(Job).where(Job.statut == "done", Job.termine_le.is_not(None),
                                              Job.termine_le < limite).execution_options(synchronize_session=False))
            return int(res.rowcount or 0)

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
