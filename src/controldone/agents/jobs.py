"""Handler de job ``agent`` : exécute un agent pour un client (ou pour la plateforme).

Payload : ``{"agent": "<nom>", "params": {...}}`` ; le client est celui du job (``tenant_id``), jamais
un paramètre. Le modèle de langage est utilisé si une clé est configurée ; la veille n'accède au réseau
que si ``CONTROLDONE_VEILLE_RESEAU=1``.
"""

from __future__ import annotations

import os
from typing import Any

import controldone.litiges.jobs  # noqa: F401  (enregistre « preparer_reclamation »)
from controldone.jobs.registre import ErreurDefinitive, JobContext, handler

from .base import ContexteAgent
from .llm import redacteur_par_defaut
from .registre import AGENTS

__all__ = ["executer_agent", "reseau_veille"]


def reseau_veille() -> bool:
    return os.environ.get("CONTROLDONE_VEILLE_RESEAU", "").strip().lower() in ("1", "oui", "true", "yes")


@handler("agent")
def executer_agent(ctx: JobContext) -> dict[str, Any]:
    nom = ctx.payload.get("agent")
    if nom not in AGENTS:
        raise ErreurDefinitive("agent inconnu")
    agent = AGENTS[nom]()
    params = dict(ctx.payload.get("params") or {})
    contexte = ContexteAgent(db=ctx.db, tenant_id=ctx.tenant_id, llm=ctx.services.get("llm", redacteur_par_defaut()),
                             reseau=bool(ctx.services.get("reseau", reseau_veille())), services=dict(ctx.services))
    return agent.executer(contexte, **params).en_dict()
