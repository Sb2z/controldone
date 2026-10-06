"""Persistance de la file de validation des actions sortantes (outbox). La logique (transitions,
garde-fous, autonomie) est dans ``controldone.outbox`` ; ce module ne fait que lire et écrire, dans la
transaction fournie (session système ouverte par ``Database.transaction_systeme``)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from controldone.storage.coltypes import maintenant
from controldone.storage.models import AutonomieSortie, Outbox, Tenant

__all__ = [
    "autonomie",
    "client_existe",
    "definir_autonomie",
    "inserer",
    "inserer_ou_lire",
    "lire",
    "lire_par_cle",
    "lister",
]


def inserer(s: Session, **champs: Any) -> Outbox:
    o, _cree = inserer_ou_lire(s, **champs)
    return o


def inserer_ou_lire(s: Session, **champs: Any) -> tuple[Outbox, bool]:
    """Insertion ; si la clé d'idempotence vient d'être prise par une transaction concurrente
    (PostgreSQL), renvoie la ligne existante au lieu de laisser fuir ``IntegrityError`` (point de
    sauvegarde, D-1312)."""
    o = Outbox(**champs)
    cle = champs.get("idempotency_key")
    if not cle:
        s.add(o)
        s.flush()
        return o, True
    try:
        with s.begin_nested():
            s.add(o)
            s.flush()
    except IntegrityError:
        existant = lire_par_cle(s, cle)
        if existant is None:
            raise
        return existant, False
    return o, True


def lire(s: Session, action_id: str, *, verrou: bool = False) -> Outbox | None:
    q = select(Outbox).where(Outbox.id == action_id)
    if verrou:
        q = q.with_for_update()
    return s.execute(q).scalar_one_or_none()


def lire_par_cle(s: Session, cle: str) -> Outbox | None:
    return s.execute(select(Outbox).where(Outbox.idempotency_key == cle)).scalar_one_or_none()


def lister(
    s: Session,
    *,
    statuts: list[str] | None = None,
    kind: str | None = None,
    tenant_id: str | None = None,
    plateforme: bool | None = None,
    limite: int = 500,
) -> list[Outbox]:
    """Les ``limite`` actions **les plus récentes** (tri SQL décroissant avant la limite, D-1309), renvoyées
    en ordre chronologique."""
    q = select(Outbox).order_by(Outbox.cree_le.desc(), Outbox.id.desc()).limit(limite)
    if statuts:
        q = q.where(Outbox.statut.in_(statuts))
    if kind:
        q = q.where(Outbox.kind == kind)
    if tenant_id:
        q = q.where(Outbox.tenant_id == tenant_id)
    if plateforme is True:
        q = q.where(Outbox.tenant_id.is_(None))
    return list(reversed(list(s.execute(q).scalars())))


def autonomie(s: Session, kind: str) -> str:
    a = s.get(AutonomieSortie, kind)
    return a.mode if a else "manuel"


def definir_autonomie(s: Session, kind: str, mode: str, par: str) -> None:
    a = s.get(AutonomieSortie, kind)
    if a is None:
        s.add(AutonomieSortie(kind=kind, mode=mode, modifie_par=par, modifie_le=maintenant()))
    else:
        a.mode, a.modifie_par, a.modifie_le = mode, par, maintenant()
    s.flush()


def client_existe(s: Session, tenant_id: str) -> bool:
    t = s.get(Tenant, tenant_id)
    return t is not None and t.actif
