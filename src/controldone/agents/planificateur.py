"""Planificateur des agents : ``python -m controldone.agents.planificateur``.

Met en file un job ``agent`` par agent périodique et par client actif (agent de plateforme : un seul),
avec une clé d'idempotence **par période** (``agent:<nom>:<client>:<période>``) : relancer le
planificateur dans la même période ne crée aucun doublon. Périodes : ``heure`` (AAAA-MM-JJTHH),
``jour`` (AAAA-MM-JJ), ``semaine`` (AAAA-Wss ISO).

    python -m controldone.agents.planificateur                 # met en file puis s'arrête (cron)
    python -m controldone.agents.planificateur --executer      # … et exécute aussitôt les jobs d'agents
    python -m controldone.agents.planificateur --boucle --intervalle 900
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from controldone.storage.clients import clients_actifs
from controldone.storage.coltypes import maintenant
from controldone.storage.db import Database
from controldone.storage.file_jobs import JobStore

from .registre import AGENTS

__all__ = ["cle_periode", "executer_jobs_agents", "main", "planifier"]


def cle_periode(periode: str, quand: datetime) -> str:
    q = quand.astimezone(UTC)
    if periode == "heure":
        return q.strftime("%Y-%m-%dT%H")
    if periode == "jour":
        return q.strftime("%Y-%m-%d")
    if periode == "semaine":
        annee, semaine, _ = q.isocalendar()
        return f"{annee}-W{semaine:02d}"
    raise ValueError(f"période inconnue : {periode}")


def planifier(db: Database, *, agents: Sequence[str] | None = None, quand: datetime | None = None) -> list[dict[str, Any]]:
    """Met en file les jobs de la période ; renvoie ``[{agent, tenant_id, job_id, cree}]``."""
    quand = quand or maintenant()
    store = JobStore(db)
    clients = clients_actifs(db)
    sortie = []
    for nom, cls in AGENTS.items():
        if agents and nom not in agents:
            continue
        if cls.periode is None:
            continue
        periode = cle_periode(cls.periode, quand)
        cibles: list[str | None] = [None] if cls.plateforme else list(clients)
        for tenant in cibles:
            job, cree = store.enqueue("agent", {"agent": nom, "params": {}},
                                      f"agent:{nom}:{tenant or 'plateforme'}:{periode}", tenant, now=quand)
            sortie.append({"agent": nom, "tenant_id": tenant, "job_id": job.id, "cree": cree})
    return sortie


def executer_jobs_agents(db: Database, *, services: dict[str, Any] | None = None) -> int:
    """Exécute les jobs d'agents prêts (et les préparations de dossiers qu'ils demandent)."""
    import controldone.agents.jobs  # noqa: F401  (handlers)
    from controldone.jobs.worker import Worker

    worker = Worker(db, kinds=["agent", "preparer_reclamation"], services=services or {}, poll_s=0.01)
    n = 0
    while worker.executer_un() is not None:
        n += 1
    return n


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m controldone.agents.planificateur")
    parser.add_argument("--agents", default=None, help="liste d'agents séparés par des virgules")
    parser.add_argument("--executer", action="store_true", help="exécuter aussitôt les jobs d'agents")
    parser.add_argument("--boucle", action="store_true")
    parser.add_argument("--intervalle", type=int, default=900, help="secondes entre deux planifications")
    parser.add_argument("--init-schema", action="store_true")
    args = parser.parse_args(argv)
    db = Database()
    if args.init_schema:
        db.creer_schema()
    agents = args.agents.split(",") if args.agents else None
    try:
        while True:
            jobs = planifier(db, agents=agents)
            resume: dict[str, Any] = {"planifies": sum(1 for j in jobs if j["cree"]), "deja_planifies":
                                      sum(1 for j in jobs if not j["cree"])}
            if args.executer:
                from controldone.storage.vault import FileVault

                resume["executes"] = executer_jobs_agents(db, services={"vault": FileVault.depuis_env()})
            print(json.dumps(resume, ensure_ascii=False))
            if not args.boucle:
                break
            time.sleep(args.intervalle)
    finally:
        db.fermer()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
