"""Garde-fous du cloisonnement, appliqués à **toute** session SQLAlchemy (écouteurs globaux).

Défense en profondeur, en plus des filtres explicites de ``TenantScope`` :

1. ``do_orm_execute`` : toute requête ORM (SELECT, UPDATE, DELETE) touchant une table client
   (``TenantMixin``) reçoit automatiquement le critère ``tenant_id = <client lié à la session>``.
   Une session non liée à un client (ni système, ni opérateur) qui touche une table client est refusée
   (``AccesRefuse``). Les INSERT en masse de l'ORM sont refusés dans une session liée à un client.
2. ``before_flush`` : tout objet client ajouté, modifié ou supprimé doit appartenir au client lié à la
   session ; ``tenant_id`` ne peut jamais changer ; une session opérateur est en lecture seule sur les
   tables client ; les tables ``AppendOnly`` refusent modification et suppression (sauf effacement RGPD
   en session système).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import event, inspect
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

from controldone.storage.erreurs import AccesRefuse
from controldone.storage.models import AppendOnly, AuditLog, TenantMixin

__all__ = ["CLE_EFFACEMENT", "CLE_OPERATEUR", "CLE_SYSTEME", "CLE_TENANT", "installer"]

CLE_TENANT = "controldone_tenant"
CLE_SYSTEME = "controldone_systeme"  # session plateforme (worker, purge, file sortante) : non filtrée
CLE_OPERATEUR = "controldone_operateur"  # lecture transversale du fondateur, auditée, sans écriture client
CLE_EFFACEMENT = "controldone_effacement_rgpd"  # autorise la suppression des lignes append-only du client

_installe = False


def _touche_tables_client(state: ORMExecuteState) -> bool:
    return any(issubclass(m.class_, TenantMixin) for m in state.all_mappers)


def _filtrer(state: ORMExecuteState) -> None:
    if not (state.is_select or state.is_update or state.is_delete or state.is_insert):
        return
    if not _touche_tables_client(state):
        return
    info = state.session.info
    if info.get(CLE_SYSTEME):
        return
    tenant = info.get(CLE_TENANT)
    if info.get(CLE_OPERATEUR) and tenant is None:
        if not state.is_select:
            raise AccesRefuse(
                "session opérateur : écriture directe interdite (passer par OperatorScope.client)"
            )
        return
    if tenant is None:
        raise AccesRefuse("accès aux données client hors TenantScope")
    if state.is_insert:
        raise AccesRefuse("insertion en masse interdite dans une session cloisonnée")
    state.statement = state.statement.options(
        with_loader_criteria(TenantMixin, lambda cls: cls.tenant_id == tenant, include_aliases=True)
    )


def _verifier_flush(session: Session, flush_context: Any, instances: Any) -> None:
    info = session.info
    systeme = bool(info.get(CLE_SYSTEME))
    tenant = info.get(CLE_TENANT)
    operateur = bool(info.get(CLE_OPERATEUR)) and tenant is None
    for obj in session.dirty:
        if isinstance(obj, AppendOnly) and session.is_modified(obj, include_collections=False):
            raise AccesRefuse(f"{type(obj).__name__} : table append-only, modification interdite")
    for obj in session.deleted:
        if isinstance(obj, AuditLog):
            raise AccesRefuse("journal d'audit : suppression interdite")
        if isinstance(obj, AppendOnly) and not (systeme and info.get(CLE_EFFACEMENT)):
            raise AccesRefuse(f"{type(obj).__name__} : table append-only, suppression interdite")
    if systeme:
        return
    for groupe in (session.new, session.dirty, session.deleted):
        for obj in groupe:
            if not isinstance(obj, TenantMixin):
                continue
            if operateur or tenant is None:
                raise AccesRefuse("écriture de données client hors TenantScope")
            if obj.tenant_id != tenant:
                raise AccesRefuse("écriture refusée : objet d'un autre client")
            if obj not in session.new:
                hist = inspect(obj).attrs.tenant_id.history
                if hist.deleted and any(v != tenant for v in hist.deleted if v is not None):
                    raise AccesRefuse("changement de client interdit")


def installer() -> None:
    """Installe les écouteurs globaux (idempotent ; appelé à l'import de ``controldone.storage``)."""
    global _installe
    if _installe:
        return
    event.listen(Session, "do_orm_execute", _filtrer)
    event.listen(Session, "before_flush", _verifier_flush)
    _installe = True
