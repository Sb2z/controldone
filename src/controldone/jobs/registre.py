"""Registre des handlers : ``@handler("traiter_lot")``.

``charger_handlers()`` importe **tous** les modules qui enregistrent des handlers : c'est la seule liste,
utilisée par le worker (``python -m controldone.jobs.worker``) et par le worker intégré du web
(``controldone serve``) — D-1302.
"""

from __future__ import annotations

import importlib
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from typing import Any as Session  # session SQLAlchemy (type seulement)

    from controldone.storage.db import Database
    from controldone.storage.file_jobs import JobInfo

__all__ = ["HANDLERS", "MODULES_HANDLERS", "BailPerdu", "ErreurDefinitive", "Handler", "JobContext",
           "charger_handlers", "handler", "obtenir_handler"]

log = logging.getLogger("controldone.jobs.registre")

#: Modules qui enregistrent des handlers (``@handler``), dans l'ordre d'import.
MODULES_HANDLERS: tuple[str, ...] = (
    "controldone.jobs.handlers",  # traiter_lot, purger_retention, recontroler_dossier
    "controldone.connecteurs.jobs",  # controle_avant_paiement
    "controldone.agents.jobs",  # agent
    "controldone.litiges.jobs",  # preparer_reclamation
    "controldone.referentiel.jobs",  # referentiel_recalculer
)


class ErreurDefinitive(Exception):
    """Échec non réessayable : le job passe ``dead`` immédiatement (avec alerte)."""


class BailPerdu(Exception):
    """Le bail du job n'est plus détenu par ce worker (expiré, repris par un autre) : le handler s'arrête
    **sans rien écrire** ; l'autre détenteur termine le job (jeton de clôture, D-1303)."""


@dataclass
class JobContext:
    job: JobInfo
    db: Database
    heartbeat: Callable[[], bool] = field(default=lambda: True)
    services: dict[str, Any] = field(default_factory=dict)
    #: Positionné par le worker quand le bail est perdu ou n'a pas pu être renouvelé à temps.
    perdu: threading.Event = field(default_factory=threading.Event)
    #: Identifiant du worker détenteur (jeton de clôture : ``locked_by`` + ``attempts``).
    worker_id: str | None = None

    @property
    def payload(self) -> dict[str, Any]:
        return self.job.payload

    @property
    def tenant_id(self) -> str | None:
        return self.job.tenant_id

    @property
    def bail_perdu(self) -> bool:
        return self.perdu.is_set()

    def exiger_bail(self, session: Session | None = None) -> None:
        """Lève ``BailPerdu`` si le bail est perdu. Avec ``session`` (transaction d'écriture du handler,
        juste avant la validation des résultats), relit la ligne du job **dans cette transaction** : jeton
        de clôture — si un autre worker a repris le job, rien n'est validé."""
        if self.perdu.is_set():
            raise BailPerdu(self.job.id)
        if session is None or self.worker_id is None:
            return
        from controldone.storage.file_jobs import JobStore

        if not JobStore.detient(session, self.job.id, self.worker_id, self.job.attempts):
            self.perdu.set()
            raise BailPerdu(self.job.id)


Handler = Callable[[JobContext], "dict[str, Any] | None"]
HANDLERS: dict[str, Handler] = {}


def handler(kind: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        if kind in HANDLERS and HANDLERS[kind] is not fn:
            raise ValueError(f"handler déjà enregistré pour {kind!r}")
        HANDLERS[kind] = fn
        return fn

    return deco


def obtenir_handler(kind: str) -> Handler | None:
    return HANDLERS.get(kind)


def charger_handlers(modules: tuple[str, ...] = MODULES_HANDLERS) -> dict[str, Handler]:
    """Importe les modules de ``MODULES_HANDLERS`` (idempotent) et renvoie le registre complet."""
    for module in modules:
        try:
            importlib.import_module(module)
        except ImportError:  # pragma: no cover - paquet optionnel absent
            log.warning("handlers_indisponibles module=%s", module)
    return HANDLERS
