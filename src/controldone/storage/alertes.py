"""Alertes pour le fondateur (job mort, plafond de coût IA, sauvegarde…). Dédoublonnées par ``cle``.

Notifications poussées (D-3502) : ``services.notifications`` lit les alertes non encore traitées
(``notifiee_le`` nul) par ``a_notifier`` et inscrit chaque envoi dans ``notifications_alertes`` (une notification
par type et par jour) ; les fonctions ci-dessous sont sa seule porte d'accès à la base.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from controldone.storage.coltypes import maintenant
from controldone.storage.models import Alerte, NotificationAlerte

__all__ = ["EtatCanal", "NotificationEnvoyee", "a_notifier", "emettre_alerte", "enregistrer_notification",
           "etat_canaux", "etat_notification", "historique_notifications", "marquer_lue", "marquer_notifiees"]


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
    n.canaux = ",".join(canaux)[:100]  # « webhook:ok,courriel:echec » (D-4104) ; ancien format : « webhook »
    n.statut = "envoyee" if envoyee else "echec"
    if envoyee:
        n.envoyee_le = quand
    session.flush()
    return n.essais


# --- historique des notifications (lecture, D-4104) ------------------------------------------------------


@dataclass(frozen=True)
class NotificationEnvoyee:
    """Une ligne de l'historique : une notification par type d'alerte et par jour (ou un essai). Aucune donnée
    client, aucune URL ni adresse : type, nombre d'alertes regroupées, canaux et leur résultat."""

    id: int
    kind: str
    jour: str  # AAAA-MM-JJ (UTC) ; pour un essai, date de l'essai
    nombre: int
    statut: str  # envoyee | echec
    essais: int
    canaux: dict[str, str] = field(default_factory=dict)  # {"webhook": "ok" | "echec", …}
    premier_essai: datetime | None = None
    envoyee_le: datetime | None = None

    @property
    def envoyee(self) -> bool:
        return self.statut == "envoyee"


@dataclass(frozen=True)
class EtatCanal:
    """Santé d'un canal (``webhook``, ``courriel``) d'après l'historique : dernier succès, dernier échec."""

    canal: str
    dernier_succes: datetime | None = None
    dernier_echec: datetime | None = None

    @property
    def en_echec(self) -> bool:
        """Le dernier essai connu est un échec."""
        return self.dernier_echec is not None and (self.dernier_succes is None
                                                   or self.dernier_echec > self.dernier_succes)


def _canaux(brut: str, statut: str) -> dict[str, str]:
    sortie: dict[str, str] = {}
    for morceau in (brut or "").split(","):
        morceau = morceau.strip()
        if not morceau:
            continue
        nom, _, res = morceau.partition(":")
        sortie[nom] = res if res in ("ok", "echec") else ("ok" if statut == "envoyee" else "echec")
    return sortie


def _ligne(n: NotificationAlerte) -> NotificationEnvoyee:
    jour = n.cle.split(":", 1)[1][:10] if ":" in n.cle else ""
    return NotificationEnvoyee(id=n.id, kind=n.kind, jour=jour, nombre=n.nombre, statut=n.statut, essais=n.essais,
                               canaux=_canaux(n.canaux, n.statut), premier_essai=n.cree_le, envoyee_le=n.envoyee_le)


def historique_notifications(session: Session, *, limite: int = 50, depuis: datetime | None = None,
                             kind: str | None = None) -> list[NotificationEnvoyee]:
    """Notifications poussées, la plus récente d'abord (``limite`` bornée à 500)."""
    q = select(NotificationAlerte).order_by(NotificationAlerte.cree_le.desc(), NotificationAlerte.id.desc())
    if depuis is not None:
        q = q.where(NotificationAlerte.cree_le >= depuis)
    if kind:
        q = q.where(NotificationAlerte.kind == kind)
    return [_ligne(n) for n in session.execute(q.limit(max(1, min(int(limite), 500)))).scalars()]


def etat_canaux(session: Session, *, depuis: datetime | None = None, limite: int = 500) -> dict[str, EtatCanal]:
    """État de chaque canal vu dans l'historique récent (``{canal: EtatCanal}``). L'heure retenue est
    l'envoi réussi (``envoyee_le``) ou, faute de mieux, le premier essai du jour."""
    succes: dict[str, datetime] = {}
    echecs: dict[str, datetime] = {}
    for n in historique_notifications(session, limite=limite, depuis=depuis):
        quand = n.envoyee_le or n.premier_essai
        if quand is None:
            continue
        for canal, res in n.canaux.items():
            cible = succes if res == "ok" else echecs
            if canal not in cible or quand > cible[canal]:
                cible[canal] = quand
    return {c: EtatCanal(c, succes.get(c), echecs.get(c)) for c in sorted({*succes, *echecs})}
