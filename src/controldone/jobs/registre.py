"""Registre des handlers : ``@handler("traiter_lot")``."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from controldone.storage.db import Database
    from controldone.storage.file_jobs import JobInfo

__all__ = ["HANDLERS", "ErreurDefinitive", "Handler", "JobContext", "handler", "obtenir_handler"]


class ErreurDefinitive(Exception):
    """Échec non réessayable : le job passe ``dead`` immédiatement (avec alerte)."""


@dataclass
class JobContext:
    job: JobInfo
    db: Database
    heartbeat: Callable[[], bool] = field(default=lambda: True)
    services: dict[str, Any] = field(default_factory=dict)

    @property
    def payload(self) -> dict[str, Any]:
        return self.job.payload

    @property
    def tenant_id(self) -> str | None:
        return self.job.tenant_id


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
