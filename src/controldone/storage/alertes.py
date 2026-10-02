"""Alertes pour le fondateur (job mort, plafond de coût IA…). Dédoublonnées par ``cle``."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from controldone.storage.coltypes import maintenant
from controldone.storage.models import Alerte

__all__ = ["emettre_alerte", "marquer_lue"]


def emettre_alerte(session: Session, *, cle: str, kind: str, message: str, tenant_id: str | None = None,
                   details: dict[str, Any] | None = None) -> bool:
    """Crée l'alerte si ``cle`` est nouvelle ; renvoie ``True`` si créée."""
    if session.execute(select(Alerte.id).where(Alerte.cle == cle)).scalar() is not None:
        return False
    try:
        with session.begin_nested():
            session.add(Alerte(cle=cle, kind=kind, message=message[:500], tenant_id=tenant_id,
                               details=details or {}))
    except IntegrityError:
        return False
    return True


def marquer_lue(session: Session, alerte_id: int) -> None:
    a = session.get(Alerte, alerte_id)
    if a is not None and a.lue_le is None:
        a.lue_le = maintenant()
