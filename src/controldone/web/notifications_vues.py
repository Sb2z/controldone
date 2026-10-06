"""Historique des notifications poussées au fondateur (webhook, courriel ; D-3502) : page ``/admin/notifications``
(bloc I3).

Lecture par une **interface mince** (``historique``, ``etat_canaux``) : aujourd'hui
``storage.listes_sql.notifications_page`` ; à remplacer par l'API de lecture du bloc production quand elle sera
livrée, sans toucher au gabarit. Rien d'affiché ne vient d'un client : type d'alerte, nombre, canaux, état, essais
et horodatages. La configuration des canaux est résumée **sans** l'URL du webhook ni les adresses (nom du canal
seulement)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from controldone.auth.roles import Acteur

__all__ = ["EtatCanal", "ResumeConfig", "etat_canaux", "historique", "resume_config"]


def historique(pf: Any, fondateur: Acteur, *, decalage: int, limite: int) -> tuple[list[dict[str, Any]], int]:
    """Notifications, plus récentes d'abord : ``(lignes, total)``. Chaque ligne : ``kind``, ``nombre``,
    ``canaux`` (liste), ``statut`` (``envoyee`` | ``echec``), ``essais``, ``cree_le``, ``envoyee_le``."""
    from controldone.storage.listes_sql import notifications_page

    with pf.db.operateur(fondateur) as op:
        return notifications_page(op, decalage=decalage, limite=limite)


@dataclass
class EtatCanal:
    nom: str
    dernier_succes: datetime | None = None
    dernier_echec: datetime | None = None

    @property
    def en_echec(self) -> bool:
        return self.dernier_echec is not None and (self.dernier_succes is None
                                                   or self.dernier_echec > self.dernier_succes)


def etat_canaux(lignes: list[dict[str, Any]]) -> list[EtatCanal]:
    """Dernier envoi réussi et dernier échec de chaque canal, d'après les notifications récentes (``lignes``,
    plus récentes d'abord). Une notification réussie inscrit les canaux qui ont réussi, une notification en échec
    ceux qui ont échoué (``services.notifications.notifier_alertes``)."""
    canaux: dict[str, EtatCanal] = {}
    for n in lignes:
        quand = n["envoyee_le"] or n["cree_le"]
        for nom in n["canaux"]:
            c = canaux.setdefault(nom, EtatCanal(nom))
            if n["statut"] == "envoyee":
                c.dernier_succes = c.dernier_succes or quand
            else:
                c.dernier_echec = c.dernier_echec or n["cree_le"]
    return sorted(canaux.values(), key=lambda c: c.nom)


@dataclass
class ResumeConfig:
    actif: bool
    mode: str
    canaux: list[str] = field(default_factory=list)
    erreurs: list[str] = field(default_factory=list)
    types: list[str] | None = None


def resume_config() -> ResumeConfig:
    """Configuration des notifications **vue par ce processus** (variables ``CONTROLDONE_NOTIF_*``) : canaux par
    leur nom, erreurs de configuration (noms de variables seulement)."""
    from controldone.services.notifications import ConfigNotifications

    cfg = ConfigNotifications.depuis_env()
    return ResumeConfig(actif=cfg.actif, mode=cfg.mode, canaux=[c.nom for c in cfg.canaux],
                        erreurs=list(cfg.erreurs), types=sorted(cfg.types) if cfg.types is not None else None)
