"""Alertes pour le fondateur (job mort, plafond de coût IA, sauvegarde…). Dédoublonnées par ``cle``.

Notifications poussées (D-3502) : ``services.notifications`` lit les alertes non encore traitées
(``notifiee_le`` nul) par ``a_notifier`` et inscrit chaque envoi dans ``notifications_alertes`` (une notification
par type et par jour) ; les fonctions ci-dessous sont sa seule porte d'accès à la base.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from controldone.storage.coltypes import maintenant
from controldone.storage.models import Alerte, NotificationAlerte

__all__ = ["a_notifier", "emettre_alerte", "enregistrer_notification", "etat_notification", "marquer_lue",
           "marquer_notifiees"]


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


def a_notifier(session: Session, *, depuis: datetime, quand: datetime | None = None,
               limite: int = 5000) -> dict[str, list[int]]:
    """Alertes non lues et non traitées, groupées par type : ``{kind: [id…]}``. Celles d'avant ``depuis`` (ou déjà
    lues) sont marquées traitées sans envoi : activer les notifications n'envoie pas l'historique."""
    quand = quand or maintenant()
    groupes: dict[str, list[int]] = defaultdict(list)
    anciennes: list[int] = []
    for aid, kind, cree_le, lue_le in session.execute(
            select(Alerte.id, Alerte.kind, Alerte.cree_le, Alerte.lue_le)
            .where(Alerte.notifiee_le.is_(None)).order_by(Alerte.id).limit(limite)):
        if lue_le is not None or cree_le < depuis:
            anciennes.append(aid)
        else:
            groupes[kind].append(aid)
    marquer_notifiees(session, anciennes, quand)
    return dict(groupes)


def marquer_notifiees(session: Session, ids: list[int], quand: datetime | None = None) -> None:
    for i in range(0, len(ids), 500):
        session.execute(update(Alerte).where(Alerte.id.in_(ids[i:i + 500]))
                        .values(notifiee_le=quand or maintenant()))


def etat_notification(session: Session, cle: str) -> tuple[str | None, int]:
    """``(statut, essais)`` de la notification ``cle`` (``<kind>:<AAAA-MM-JJ>``), ``(None, 0)`` si aucune."""
    n = session.execute(select(NotificationAlerte).where(NotificationAlerte.cle == cle)).scalar_one_or_none()
    return (n.statut, n.essais) if n is not None else (None, 0)


def enregistrer_notification(session: Session, *, cle: str, kind: str, nombre: int, canaux: list[str],
                             envoyee: bool, quand: datetime | None = None) -> int:
    """Inscrit un essai d'envoi ; renvoie le nombre d'essais de la journée pour ce type."""
    quand = quand or maintenant()
    n = session.execute(select(NotificationAlerte).where(NotificationAlerte.cle == cle)).scalar_one_or_none()
    if n is None:
        n = NotificationAlerte(cle=cle, kind=kind, nombre=0, essais=0, cree_le=quand)
        session.add(n)
    n.essais += 1
    n.nombre = max(n.nombre, nombre)
    n.canaux = ",".join(canaux)[:100]
    n.statut = "envoyee" if envoyee else "echec"
    if envoyee:
        n.envoyee_le = quand
    session.flush()
    return n.essais
