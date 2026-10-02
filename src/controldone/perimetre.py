"""Ouverture du périmètre d'un client pour un acteur quelconque (exploitation : litiges, agents,
connecteurs, référentiel).

Le fondateur passe toujours par ``OperatorScope`` (accès tracé avec motif, SECURITY §1.2) ; les autres
rôles ouvrent un ``TenantScope`` ordinaire (les rôles client restent limités à **leur** client).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from controldone.auth.roles import Acteur, Role
from controldone.storage.db import Database
from controldone.storage.scope import TenantScope

__all__ = ["perimetre"]


@contextmanager
def perimetre(db: Database, tenant_id: str, acteur: Acteur, *, motif: str = "exploitation",
              lecture: bool = False) -> Iterator[TenantScope]:
    """``TenantScope`` validé à la sortie (rollback sur exception)."""
    if acteur.role is Role.fondateur:
        with db.operateur(acteur) as op:
            yield op.client(tenant_id, motif)
    else:
        with db.tenant(tenant_id, acteur, lecture=lecture) as scope:
            yield scope
