"""File de tâches en base (D-004) : ``enqueue``, worker, handlers, plafonds de coût IA, métriques."""

from __future__ import annotations

from typing import Any

from controldone.jobs.couts import EtatPlafond, RegistreCoutsDB, cout_mensuel, enregistrer_cout, etat_plafond
from controldone.jobs.metriques import metriques, texte_prometheus
from controldone.jobs.registre import HANDLERS, ErreurDefinitive, JobContext, handler
from controldone.storage.db import Database
from controldone.storage.file_jobs import JobInfo, JobStore, delai_backoff

__all__ = [
    "HANDLERS",
    "ErreurDefinitive",
    "EtatPlafond",
    "JobContext",
    "JobInfo",
    "JobStore",
    "RegistreCoutsDB",
    "cout_mensuel",
    "delai_backoff",
    "enqueue",
    "enregistrer_cout",
    "etat_plafond",
    "handler",
    "metriques",
    "texte_prometheus",
]


def enqueue(
    kind: str,
    payload: dict[str, Any],
    idempotency_key: str,
    tenant_id: str | None = None,
    *,
    db: Database | None = None,
    **options: Any,
) -> JobInfo:
    """Met un job en file ; une clé d'idempotence déjà connue renvoie le job existant (aucun doublon)."""
    job, _cree = JobStore(db or Database()).enqueue(kind, payload, idempotency_key, tenant_id, **options)
    return job
