"""Journaux structurés JSON **sans contenu de document** (SPEC §20.8).

Seuls les champs de ``CHAMPS_AUTORISES`` sont écrits (identifiants, durées, compteurs, codes d'erreur) ;
tout autre champ passé à ``evenement`` est ignoré. Les messages d'exception ne sont jamais journalisés :
seul le nom de la classe d'exception l'est (un message pourrait contenir du texte de document).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

__all__ = ["CHAMPS_AUTORISES", "FormateurJSON", "configurer_journaux", "evenement"]

CHAMPS_AUTORISES = frozenset(
    {
        "event",
        "job_id",
        "kind",
        "tenant_id",
        "worker_id",
        "attempt",
        "statut",
        "duree_ms",
        "erreur",
        "lot_id",
        "dossier_id",
        "dossiers",
        "constats",
        "cout_eur",
        "seuil",
        "nombre",
        "signal",
    }
)


class FormateurJSON(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        sortie: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "niveau": record.levelname,
            "logger": record.name,
        }
        champs = getattr(record, "champs", None)
        if isinstance(champs, dict):
            sortie.update({k: v for k, v in champs.items() if k in CHAMPS_AUTORISES})
        else:
            sortie["event"] = str(record.msg)[:100]
        return json.dumps(sortie, ensure_ascii=False, default=str)


def evenement(logger: logging.Logger, event: str, niveau: int = logging.INFO, **champs: Any) -> None:
    propres = {k: v for k, v in champs.items() if k in CHAMPS_AUTORISES}
    logger.log(niveau, event, extra={"champs": {"event": event, **propres}})


def configurer_journaux(niveau: str = "INFO") -> None:
    gestionnaire = logging.StreamHandler()
    gestionnaire.setFormatter(FormateurJSON())
    racine = logging.getLogger("controldone")
    racine.handlers[:] = [gestionnaire]
    racine.setLevel(niveau)
    racine.propagate = False
