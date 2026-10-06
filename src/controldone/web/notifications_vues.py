"""Historique des notifications poussées au fondateur (webhook / ntfy, courriel ; D-3502, D-4104) : page
``/admin/notifications`` (bloc I3, D-4304).

Lecture par l'API du bloc production, ``services.notifications.historique`` (lecture seule, aucune URL, aucun
jeton ni aucune adresse dans le résultat). La page ajoute seulement le mode d'exécution (pour dire pourquoi rien
ne part hors production) et la pagination de l'historique."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ["JOURS", "LIMITE", "VueNotifications", "lire"]

#: Fenêtre et plafond de l'historique affiché (l'API borne la limite à 500).
JOURS = 90
LIMITE = 500


@dataclass
class VueNotifications:
    mode: str
    historique: Any  # services.notifications.HistoriqueNotifications


def lire(db: Any) -> VueNotifications:
    from controldone.services.notifications import ConfigNotifications, historique

    config = ConfigNotifications.depuis_env()
    return VueNotifications(
        mode=config.mode, historique=historique(db, limite=LIMITE, jours=JOURS, config=config)
    )
